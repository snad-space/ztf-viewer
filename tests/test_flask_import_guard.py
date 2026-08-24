"""Guard that ``flask`` never creeps back into the package.

``ztf_viewer`` runs entirely on FastAPI/Starlette now; ``flask`` is only a transitive
dependency (via ``dash``), not something any module here should import. This is a plain
passing assertion, not an ``xfail``: it holds today, and the point of the test is to catch a
future reintroduction.
"""

import ast
import pathlib

import ztf_viewer

PACKAGE_ROOT = pathlib.Path(ztf_viewer.__file__).parent


def _source_files():
    return sorted(PACKAGE_ROOT.rglob("*.py"))


def _parse(path):
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _rel(path):
    return path.relative_to(PACKAGE_ROOT.parent).as_posix()


def _flask_import_sites(path):
    """``"path:line import ..."`` for every ``import flask``/``from flask import ...`` in `path`."""
    sites = []
    for node in ast.walk(_parse(path)):
        if isinstance(node, ast.Import):
            if any(alias.name == "flask" or alias.name.startswith("flask.") for alias in node.names):
                sites.append(f"{_rel(path)}:{node.lineno} {ast.unparse(node)}")
        elif isinstance(node, ast.ImportFrom) and (
            node.module == "flask" or (node.module is not None and node.module.startswith("flask."))
        ):
            sites.append(f"{_rel(path)}:{node.lineno} {ast.unparse(node)}")
    return sites


def test_flask_is_not_imported_anywhere():
    """No module under ``ztf_viewer/`` imports ``flask``."""
    offenders = []
    for path in _source_files():
        offenders.extend(_flask_import_sites(path))
    assert not offenders, "flask imported under ztf_viewer/:\n  " + "\n  ".join(offenders)


def test_scan_detects_a_flask_import(tmp_path):
    """Sanity check that the scan itself works, against a throwaway module."""
    module = tmp_path / "has_flask.py"
    module.write_text("import flask\n", encoding="utf-8")

    imports = [node for node in ast.walk(_parse(module)) if isinstance(node, ast.Import)]
    assert any(
        alias.name == "flask" for node in imports for alias in node.names
    ), "scan found no flask import in a module that has one — did it break?"

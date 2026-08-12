"""Guard that Flask coupling stays confined to ``ztf_viewer/web.py`` (F4/F5 in
``plans/001_async_dash.md``, reassigned to this branch by PR #626).

``ztf_viewer/web.py`` is the seam a later PR (``aio-starlette-web``) will swap to Starlette
without touching any call site. That only works if nothing else in the package imports
``flask`` directly. This is a plain passing assertion, not an ``xfail``: after ``aio-deflask``
it simply holds, and the point of the test is to catch a future reintroduction.
"""

import ast
import pathlib

import ztf_viewer

PACKAGE_ROOT = pathlib.Path(ztf_viewer.__file__).parent
ALLOWED_FILE = PACKAGE_ROOT / "web.py"


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
        elif isinstance(node, ast.ImportFrom):
            if node.module == "flask" or (node.module is not None and node.module.startswith("flask.")):
                sites.append(f"{_rel(path)}:{node.lineno} {ast.unparse(node)}")
    return sites


def test_flask_is_only_imported_by_web_py():
    """No module under ``ztf_viewer/`` imports ``flask`` except ``ztf_viewer/web.py``."""
    offenders = []
    for path in _source_files():
        if path == ALLOWED_FILE:
            continue
        offenders.extend(_flask_import_sites(path))
    assert not offenders, "flask imported outside ztf_viewer/web.py:\n  " + "\n  ".join(offenders)


def test_web_py_still_imports_flask():
    """Sanity check that the scan itself works: web.py is expected to import flask."""
    assert _flask_import_sites(ALLOWED_FILE), "ztf_viewer/web.py no longer imports flask — did the scan break?"

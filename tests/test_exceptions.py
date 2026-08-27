"""Tests for ``ztf_viewer.exceptions``.

The subprocess test is the point of this file: ``CatalogUnavailable`` used to import
``ztf_viewer.catalogs.conesearch`` just to run an ``isinstance`` check, and that package
constructs every query object at import, some of which reach the network. A CDS outage therefore
broke the whole suite at *collection*, not at test time. Only a fresh interpreter can show that
the import is gone, since by the time any other test runs the package is already in
``sys.modules``.
"""

import subprocess
import sys

from ztf_viewer.exceptions import CatalogUnavailable

_NO_CONESEARCH_IMPORT = """
import sys
from ztf_viewer.exceptions import CatalogUnavailable

CatalogUnavailable("boom")

leaked = [name for name in sys.modules if name.startswith("ztf_viewer.catalogs.conesearch")]
assert not leaked, f"constructing CatalogUnavailable imported {leaked}"
"""


def test_constructing_the_exception_does_not_import_the_conesearch_package():
    result = subprocess.run(
        [sys.executable, "-c", _NO_CONESEARCH_IMPORT],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "CACHE_TYPE": "memory", "UNAVAILABLE_CATALOGS_CACHE_TYPE": "memory"},
    )
    assert result.returncode == 0, result.stderr


def test_bare_message_is_preserved_without_a_catalog():
    assert str(CatalogUnavailable("boom")) == "boom"


def test_catalog_is_named_by_its_query_name():
    class FakeQuery:
        query_name = "Fake"

    assert "Fake" in str(CatalogUnavailable("detail", catalog=FakeQuery(), prolongate=False))


def test_an_object_without_query_name_is_ignored():
    # `alerce.py` passes `catalog="Alerce"`, a plain string; it has never been recognised as a
    # catalog here, and this pins that the duck-typed check did not change that.
    assert str(CatalogUnavailable("x", catalog="Alerce")) == "x"


def test_marking_a_catalog_unavailable_is_opt_out():
    from ztf_viewer.catalogs.unavailable_catalogs import unavailable_catalogs

    class FakeQuery:
        query_name = "NotMarked"

    CatalogUnavailable("detail", catalog=FakeQuery(), prolongate=False)
    assert "NotMarked" not in unavailable_catalogs

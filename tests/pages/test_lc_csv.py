"""`get_csv`'s per-OID fan-out: concurrency and exception-filtering semantics.

`get_csv` gathers `find_ztf_oid.get_lc`/`get_meta` and `ztf_ref.get` across every requested OID.
These tests pin two things a rewrite of that fan-out could silently break: the per-OID work
actually overlaps in wall time, and only `NotFound`/`CatalogUnavailable` from `ztf_ref.get` are
swallowed -- everything else must propagate.
"""

import asyncio
import time
from unittest.mock import patch

import pytest

from ztf_viewer import config

# `ztf_viewer.catalogs` builds `unavailable_catalogs` at import time, against Redis unless the
# config says otherwise. Force the in-memory backend before that import happens at all --
# `tests/conftest.py`'s per-test hook runs too late for a module-level import during collection.
config.CACHE_TYPE = "memory"
config.UNAVAILABLE_CATALOGS_CACHE_TYPE = "memory"

from ztf_viewer.exceptions import CatalogUnavailable, NotFound
from ztf_viewer.pages import lc_csv

OIDS = ["1", "2", "3", "4", "5"]
DELAY = 0.2


def _lc(oid):
    return [{"mjd": 58000.0, "mag": 18.0, "magerr": 0.05, "clrcoeff": -0.1}]


async def test_get_csv_per_oid_fanout_is_concurrent():
    async def fake_get_lc(oid, dr, min_mjd=None, max_mjd=None):
        await asyncio.sleep(DELAY)
        return _lc(oid)

    async def fake_get_meta(oid, dr):
        return {"filter": "zg"}

    async def fake_ref_get(oid, dr):
        raise NotFound

    with (
        patch.object(lc_csv.find_ztf_oid, "get_lc", fake_get_lc),
        patch.object(lc_csv.find_ztf_oid, "get_meta", fake_get_meta),
        patch.object(lc_csv.ztf_ref, "get", fake_ref_get),
    ):
        start = time.perf_counter()
        await lc_csv.get_csv("dr24", OIDS)
        elapsed = time.perf_counter() - start
    # Serial would take len(OIDS) * DELAY; concurrent should stay close to one DELAY.
    assert elapsed < len(OIDS) * DELAY / 2


async def test_get_csv_swallows_ref_not_found_and_catalog_unavailable():
    async def fake_get_lc(oid, dr, min_mjd=None, max_mjd=None):
        return _lc(oid)

    async def fake_get_meta(oid, dr):
        return {"filter": "zg"}

    async def fake_ref_get(oid, dr):
        raise CatalogUnavailable("stub: boom")

    with (
        patch.object(lc_csv.find_ztf_oid, "get_lc", fake_get_lc),
        patch.object(lc_csv.find_ztf_oid, "get_meta", fake_get_meta),
        patch.object(lc_csv.ztf_ref, "get", fake_ref_get),
    ):
        csv = await lc_csv.get_csv("dr24", ["1"])
    assert ",,\r\n" in csv or csv.strip().endswith(",")


async def test_get_csv_unexpected_ref_exception_is_not_swallowed():
    async def fake_get_lc(oid, dr, min_mjd=None, max_mjd=None):
        return _lc(oid)

    async def fake_get_meta(oid, dr):
        return {"filter": "zg"}

    async def fake_ref_get(oid, dr):
        raise ValueError("not one of the swallowed types")

    with (
        patch.object(lc_csv.find_ztf_oid, "get_lc", fake_get_lc),
        patch.object(lc_csv.find_ztf_oid, "get_meta", fake_get_meta),
        patch.object(lc_csv.ztf_ref, "get", fake_ref_get),
        pytest.raises(ValueError, match="not one of the swallowed types"),
    ):
        await lc_csv.get_csv("dr24", ["1"])


async def test_get_csv_raises_not_found_when_lc_is_missing():
    async def fake_get_lc(oid, dr, min_mjd=None, max_mjd=None):
        return None

    async def fake_get_meta(oid, dr):
        return {"filter": "zg"}

    async def fake_ref_get(oid, dr):
        raise NotFound

    with (
        patch.object(lc_csv.find_ztf_oid, "get_lc", fake_get_lc),
        patch.object(lc_csv.find_ztf_oid, "get_meta", fake_get_meta),
        patch.object(lc_csv.ztf_ref, "get", fake_ref_get),
        pytest.raises(NotFound),
    ):
        await lc_csv.get_csv("dr24", ["1"])

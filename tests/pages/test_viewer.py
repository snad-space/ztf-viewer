"""Characterization snapshots for `ztf_viewer.pages.viewer` callbacks.

Dash callbacks are ordinary functions: call them directly with hand-built inputs, stub the
upstream calls they make, and pin the returned component tree by serializing it the way Dash
itself would (`plotly.utils.PlotlyJSONEncoder`, which dispatches to a component's own
`to_plotly_json()`). There is no replay layer here, so this covers only callbacks whose output is
a pure-enough function of stubbed inputs -- not anything that would need a recorded upstream
payload to be interesting.

The highest-value part is `get_summary`'s per-catalog failure handling: each catalog in its two
loops is queried independently and a failure in one must not affect the others. A rewrite of that
loop (e.g. into a concurrent fan-out) has to preserve exactly which exceptions are swallowed and
which are not; these snapshots are how a future rewrite proves it still does.

Everything here runs against stub catalogs and stub upstream calls -- no network, no real catalog
data. Anything Simbad-derived would have unstable column order (set iteration, per-process) and
is out of scope for exactly that reason.
"""

import inspect
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from astropy.table import Table
from dash.exceptions import PreventUpdate
from plotly.utils import PlotlyJSONEncoder

from ztf_viewer import config

# `ztf_viewer.pages.viewer` pulls in `ztf_viewer.catalogs`, whose `unavailable_catalogs` connects
# to Redis eagerly at import time when configured for it. Force the in-memory backend before that
# import happens at all, rather than relying on `tests/conftest.py`'s per-test hook, which only
# takes effect once a test starts -- too late for module-level imports during collection.
config.CACHE_TYPE = "memory"
config.UNAVAILABLE_CATALOGS_CACHE_TYPE = "memory"

from ztf_viewer.catalogs import unavailable_catalogs  # noqa: E402
from ztf_viewer.exceptions import CatalogUnavailable, NotFound  # noqa: E402
from ztf_viewer.pages import viewer  # noqa: E402

# Callback registration leaves coroutine functions unwrapped, but unwrap anyway: it's a no-op if
# there's nothing to unwrap, and the body under test is the innermost one either way.
get_summary = inspect.unwrap(viewer.get_summary)
get_metadata = inspect.unwrap(viewer.get_metadata)
get_layout = inspect.unwrap(viewer.get_layout)
set_features_list = inspect.unwrap(viewer.set_features_list)
set_lc_table = inspect.unwrap(viewer.set_lc_table)
set_figure_link = viewer.set_figure_link  # a plain function, never wrapped

_GOLDEN_DIR = Path(__file__).parent.parent / "golden" / "pages_viewer"


def assert_matches_golden(name: str, component) -> None:
    """Compare `component`'s Dash-JSON serialization against a committed snapshot.

    Set the ``UPDATE_CALLBACK_GOLDEN=1`` environment variable to (re)write the snapshot instead
    of asserting against it.
    """
    payload = json.dumps(component, cls=PlotlyJSONEncoder, indent=2, sort_keys=True) + "\n"
    path = _GOLDEN_DIR / f"{name}.json"
    if os.environ.get("UPDATE_CALLBACK_GOLDEN"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload)
        return
    if not path.exists():
        pytest.fail(f"No golden snapshot at {path}; run with UPDATE_CALLBACK_GOLDEN=1 to create it.")
    assert payload == path.read_text(), f"{name!r} drifted from its committed snapshot at {path}"


# ---------------------------------------------------------------------------------------------
# get_summary -- the failure paths of its two per-catalog loops.
# ---------------------------------------------------------------------------------------------


class _StubCatalogQuery:
    """A `_BaseCatalogQuery`-shaped stand-in whose `find()` does exactly what a test wants."""

    def __init__(self, name, *, table=None, exc=None):
        self.query_name = name
        self._table = table
        self._exc = exc
        self._prob_class_columns = {}

    async def find(self, ra, dec, radius_arcsec):
        if self._exc is not None:
            raise self._exc
        return self._table


class _UnavailableCheckingCatalogQuery(_StubCatalogQuery):
    """Mirrors `_BaseCatalogQuery._raise_if_unavailable_async` against the real, memory-backed set."""

    async def find(self, ra, dec, radius_arcsec):
        if self.query_name in unavailable_catalogs:
            raise CatalogUnavailable(self.query_name, prolongate=False)
        return await super().find(ra, dec, radius_arcsec)


def _stub_table(*, objname="Stub Object", type_="SN Ia", distance=None, redshift=None):
    table = Table()
    table["separation"] = [4.94]
    table["__objname"] = [objname]
    table["__type"] = [type_]
    if distance is not None:
        table["__distance"] = distance
    if redshift is not None:
        table["__redshift"] = redshift
    return table


def _radius_inputs(catalog_names, radius=3.0):
    ids = [dict(type="search-radius", index=name) for name in catalog_names]
    values = [radius] * len(ids)
    return ids, values


@pytest.fixture
def summary_upstreams(monkeypatch):
    """Stub every `get_summary` upstream that isn't one of the catalog-loop stubs under test."""

    async def fake_get_coord(oid, dr):
        return 10.0, 20.0

    async def fake_get_sky_coord(oid, dr):
        from astropy.coordinates import SkyCoord

        return SkyCoord(ra=10.0, dec=20.0, unit="deg")

    async def fake_get_coord_string(oid, dr, frame=None):
        return "10.00000 +20.00000" if frame is None else "00h40m00s +20d00m00s"

    monkeypatch.setattr(viewer.find_ztf_oid, "get_coord", fake_get_coord)
    monkeypatch.setattr(viewer.find_ztf_oid, "get_sky_coord", fake_get_sky_coord)
    monkeypatch.setattr(viewer.find_ztf_oid, "get_coord_string", fake_get_coord_string)

    async def fake_light_curve_features(oid, dr, version="latest", **kwargs):
        raise NotFound

    monkeypatch.setattr(viewer, "light_curve_features", fake_light_curve_features)

    async def fake_get_plot_data(oid, dr, other_oids=frozenset()):
        return {"main": [{"filter": "zg", "mag": 18.0}, {"filter": "zr", "mag": 17.4}]}

    monkeypatch.setattr(viewer, "get_plot_data", fake_get_plot_data)

    def fake_ebv(coord):
        raise CatalogUnavailable("stub: csfd unavailable")

    monkeypatch.setattr(viewer.csfd, "ebv", fake_ebv)

    class _NotFoundGaiaEdr3:
        async def find(self, ra, dec, radius):
            raise NotFound

    monkeypatch.setattr(viewer, "get_catalog_query", lambda name: _NotFoundGaiaEdr3())


def _run_get_summary(catalogs, summary_upstreams):
    del summary_upstreams  # only needed for its monkeypatching side effect
    ids, values = _radius_inputs(catalogs)
    return get_summary(
        oid="633207400004730",
        dr="dr24",
        different_filter=None,
        different_field=None,
        radius_ids=ids,
        radius_values=values,
    )


async def test_get_summary_catalog_raises_not_found(summary_upstreams):
    with patch.object(viewer, "catalog_query_objects", lambda: {"stub": _StubCatalogQuery("stub", exc=NotFound())}):
        div = await _run_get_summary(["stub"], summary_upstreams)
    assert_matches_golden("get_summary_catalog_raises_not_found", div)


async def test_get_summary_catalog_raises_catalog_unavailable(summary_upstreams):
    stub = _StubCatalogQuery("stub", exc=CatalogUnavailable("stub: boom"))
    with patch.object(viewer, "catalog_query_objects", lambda: {"stub": stub}):
        div = await _run_get_summary(["stub"], summary_upstreams)
    assert_matches_golden("get_summary_catalog_raises_catalog_unavailable", div)


async def test_get_summary_catalog_raises_key_error(summary_upstreams):
    stub = _StubCatalogQuery("stub", exc=KeyError("missing-column"))
    with patch.object(viewer, "catalog_query_objects", lambda: {"stub": stub}):
        div = await _run_get_summary(["stub"], summary_upstreams)
    assert_matches_golden("get_summary_catalog_raises_key_error", div)


async def test_get_summary_catalog_in_unavailable_catalogs(summary_upstreams):
    stub = _UnavailableCheckingCatalogQuery("stub-unavailable-catalog")
    unavailable_catalogs.add(stub.query_name)
    try:
        with patch.object(viewer, "catalog_query_objects", lambda: {"stub": stub}):
            div = await _run_get_summary(["stub"], summary_upstreams)
    finally:
        unavailable_catalogs.remove(stub.query_name)
    assert_matches_golden("get_summary_catalog_in_unavailable_catalogs", div)


async def test_get_summary_mixed_success_and_failures(summary_upstreams):
    catalogs = {
        "not-found": _StubCatalogQuery("Not Found Catalog", exc=NotFound()),
        "unavailable": _StubCatalogQuery("Unavailable Catalog", exc=CatalogUnavailable("stub: boom")),
        "key-error": _StubCatalogQuery("Key Error Catalog", exc=KeyError("missing-column")),
        "success": _StubCatalogQuery(
            "Success Catalog",
            table=_stub_table(objname="Stub SN 2020xyz", type_="SN Ia", distance=[100.0], redshift=[0.02]),
        ),
    }
    with patch.object(viewer, "catalog_query_objects", lambda: catalogs):
        div = await _run_get_summary(list(catalogs), summary_upstreams)
    assert_matches_golden("get_summary_mixed_success_and_failures", div)


# ---------------------------------------------------------------------------------------------
# get_layout -- only the cheap, upstream-free branch: object not found at all.
# ---------------------------------------------------------------------------------------------


async def test_get_layout_404_when_object_not_found():
    async def fake_find(oid, dr):
        raise NotFound

    with patch.object(viewer.find_ztf_oid, "find", fake_find):
        div = await get_layout("/dr24/view/1", search="")
    assert_matches_golden("get_layout_404_when_object_not_found", div)


# ---------------------------------------------------------------------------------------------
# get_metadata -- stub `find_ztf_oid` and `ztf_ref`, the only two upstreams it reaches.
# ---------------------------------------------------------------------------------------------


_STUB_META = {
    "nobs": 42,
    "ngoodobs": 40,
    "filter": "zg",
    "fieldid": 796,
    "rcid": 12,
}


async def test_get_metadata_without_reference_image():
    async def fake_get_meta(oid, dr):
        return dict(_STUB_META)

    async def fake_get_coord_string(oid, dr, frame=None):
        return "10.00000 +20.00000"

    async def fake_ztf_ref_get(oid, dr):
        raise NotFound

    with (
        patch.object(viewer.find_ztf_oid, "get_meta", fake_get_meta),
        patch.object(viewer.find_ztf_oid, "get_coord_string", fake_get_coord_string),
        patch.object(viewer.ztf_ref, "get", fake_ztf_ref_get),
    ):
        div = await get_metadata(oid="633207400004730", dr="dr24")
    assert_matches_golden("get_metadata_without_reference_image", div)


async def test_get_metadata_with_reference_image():
    async def fake_get_meta(oid, dr):
        return dict(_STUB_META)

    async def fake_get_coord_string(oid, dr, frame=None):
        return "10.00000 +20.00000"

    async def fake_ztf_ref_get(oid, dr):
        return {"mag": 18.5, "magzp": 26.325, "sigmag": 0.05, "flags": 0}

    with (
        patch.object(viewer.find_ztf_oid, "get_meta", fake_get_meta),
        patch.object(viewer.find_ztf_oid, "get_coord_string", fake_get_coord_string),
        patch.object(viewer.ztf_ref, "get", fake_ztf_ref_get),
    ):
        div = await get_metadata(oid="633207400004730", dr="dr24")
    assert_matches_golden("get_metadata_with_reference_image", div)


# ---------------------------------------------------------------------------------------------
# set_features_list -- thin wrapper around `light_curve_features`.
# ---------------------------------------------------------------------------------------------


async def test_set_features_list_success():
    features = {"amplitude": 1.2345, "period_0_magn": 3.4567}
    with patch.object(viewer, "light_curve_features", AsyncMock(return_value=features)):
        div = await set_features_list(oid="633207400004730", dr="dr24", version="latest", min_mjd=None, max_mjd=None)
    assert_matches_golden("set_features_list_success", div)


async def test_set_features_list_not_found():
    with patch.object(viewer, "light_curve_features", AsyncMock(side_effect=NotFound)):
        result = await set_features_list(oid="633207400004730", dr="dr24", version="latest", min_mjd=None, max_mjd=None)
    assert result == "Not available"


async def test_set_features_list_prevents_update_when_range_is_backwards():
    with pytest.raises(PreventUpdate):
        await set_features_list(oid="633207400004730", dr="dr24", version="latest", min_mjd=100.0, max_mjd=50.0)


# ---------------------------------------------------------------------------------------------
# set_lc_table -- thin wrapper around `find_ztf_oid.get_lc`.
# ---------------------------------------------------------------------------------------------


async def test_set_lc_table_success():
    lc = [{"mjd": 58000.0, "mag": 18.1, "magerr": 0.05, "clrcoeff": -0.1}]
    with patch.object(viewer.find_ztf_oid, "get_lc", AsyncMock(return_value=lc)):
        data = await set_lc_table(oid="633207400004730", dr="dr24", min_mjd=None, max_mjd=None)
    assert data == lc


async def test_set_lc_table_prevents_update_when_range_is_backwards():
    with pytest.raises(PreventUpdate):
        await set_lc_table(oid="633207400004730", dr="dr24", min_mjd=100.0, max_mjd=50.0)


# ---------------------------------------------------------------------------------------------
# set_figure_link -- a plain function, no upstream at all.
# ---------------------------------------------------------------------------------------------


def test_set_figure_link_full():
    href = set_figure_link("633207400004730", "dr24", "Title", None, None, 58000.0, 59000.0, "full", None, None, "png")
    assert href == "/dr24/figure/633207400004730?title=Title&min_mjd=58000.0&max_mjd=59000.0&format=png"


def test_set_figure_link_folded():
    href = set_figure_link("633207400004730", "dr24", "Title", None, None, None, None, "folded", 3.5, 0.25, "pdf")
    assert href == "/dr24/figure/633207400004730/folded/3.5?title=Title&format=pdf&offset=-0.875"


def test_set_figure_link_prevents_update_without_period_when_folded():
    with pytest.raises(PreventUpdate):
        set_figure_link("633207400004730", "dr24", "Title", None, None, None, None, "folded", None, None, "png")


def test_set_figure_link_prevents_update_when_range_is_backwards():
    with pytest.raises(PreventUpdate):
        set_figure_link("633207400004730", "dr24", "Title", None, None, 59000.0, 58000.0, "full", None, None, "png")


def test_set_figure_link_raises_for_unknown_type():
    with pytest.raises(ValueError, match="lc_type"):
        set_figure_link("633207400004730", "dr24", "Title", None, None, None, None, "bogus", None, None, "png")

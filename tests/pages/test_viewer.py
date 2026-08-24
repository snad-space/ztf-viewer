"""Assertion-based tests for `ztf_viewer.pages.viewer` callbacks.

Dash callbacks are ordinary functions: call them directly with hand-built inputs, stub the
upstream calls they make, and assert on what comes back.

The highest-value part is `get_summary`'s per-catalog failure handling: each catalog in its two
loops is queried independently and a failure in one must not affect the others. A rewrite of that
loop (e.g. into a concurrent fan-out) has to preserve exactly which exceptions are swallowed and
which are not. That claim is asserted two ways here:

- For the failure paths themselves, by calling `get_summary` twice -- once with a catalog that
  fails, once with that catalog simply absent -- and asserting the two outputs are identical.
  A failing catalog must be indistinguishable from one that was never queried.
- For the mixed success/failure case, by projecting the returned component tree down to its
  visible text and meaningful `href`s and comparing that against an inline literal, so the
  expectation is readable in the diff instead of living in a committed JSON file.

Everything here runs against stub catalogs and stub upstream calls -- no network, no real catalog
data. Anything Simbad-derived would have unstable column order (set iteration, per-process) and
is out of scope for exactly that reason.
"""

import contextlib
import inspect
import json
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


def _dump(component) -> str:
    """Serialize a Dash component the way Dash itself would, for comparing two live results."""
    return json.dumps(component, cls=PlotlyJSONEncoder, sort_keys=True)


def _project(node):
    """Reduce a Dash component tree to the text and hrefs it renders.

    Drops `style` and every other cosmetic prop, but keeps order, nesting, and -- for links --
    both the visible text and the `href`, so which value came from which catalog stays visible
    and assertable.
    """
    if node is None or isinstance(node, str):
        return node
    if isinstance(node, (int, float)):
        return str(node)
    if isinstance(node, (list, tuple)):
        return [_project(child) for child in node]
    href = getattr(node, "href", None)
    text = _project(getattr(node, "children", None))
    return {"text": text, "href": href} if href is not None else text


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


def _other_succeeding_catalog():
    """A catalog that always succeeds, used to prove failing catalogs don't disturb their peers."""
    return _StubCatalogQuery("Other Catalog", table=_stub_table(objname="Other Object", type_="SN II"))


@contextlib.contextmanager
def _failing_catalog(exc):
    yield {"stub": _StubCatalogQuery("stub", exc=exc), "other": _other_succeeding_catalog()}


@contextlib.contextmanager
def _catalog_in_unavailable_catalogs():
    stub = _UnavailableCheckingCatalogQuery("stub-unavailable-catalog")
    unavailable_catalogs.add(stub.query_name)
    try:
        yield {"stub": stub, "other": _other_succeeding_catalog()}
    finally:
        unavailable_catalogs.remove(stub.query_name)


@pytest.mark.parametrize(
    "make_failing_catalogs",
    [
        lambda: _failing_catalog(NotFound()),
        lambda: _failing_catalog(CatalogUnavailable("stub: boom")),
        lambda: _failing_catalog(KeyError("missing-column")),
        _catalog_in_unavailable_catalogs,
    ],
    ids=["not_found", "catalog_unavailable", "key_error", "in_unavailable_catalogs"],
)
async def test_get_summary_failing_catalog_matches_catalog_absent(make_failing_catalogs, summary_upstreams):
    """A catalog that fails must render identically to a catalog that was never queried at all,
    and must not disturb the catalogs that do succeed."""
    with make_failing_catalogs() as catalogs:
        with patch.object(viewer, "catalog_query_objects", lambda: catalogs):
            failing = await _run_get_summary(list(catalogs), summary_upstreams)

    absent_catalogs = {"other": _other_succeeding_catalog()}
    with patch.object(viewer, "catalog_query_objects", lambda: absent_catalogs):
        absent = await _run_get_summary(list(absent_catalogs), summary_upstreams)

    assert _dump(failing) == _dump(absent)


async def test_get_summary_propagates_exception_not_in_the_swallow_list(summary_upstreams):
    """Only NotFound/CatalogUnavailable/KeyError are expected per-catalog failures; anything else
    is a bug in the catalog and must propagate rather than be silently swallowed."""
    stub = _StubCatalogQuery("stub", exc=RuntimeError("boom"))
    with patch.object(viewer, "catalog_query_objects", lambda: {"stub": stub}):
        with pytest.raises(RuntimeError):
            await _run_get_summary(["stub"], summary_upstreams)


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

    success_link = {"text": "Success Catalog", "href": "#success"}
    antares_href = (
        "https://antares.noirlab.edu/loci?query=%7B%22filters%22%3A+%5B%7B%22type%22%3A+%22sky_distance%22%2C+"
        "%22field%22%3A+%7B%22distance%22%3A+%220.0008333333333333334+degree%22%2C+%22htm16%22%3A+%7B%22center%22"
        "%3A+%2210.0+20.0%22%7D%7D%2C+%22text%22%3A+%22Cone+Search+for+ZTF+DR+633207400004730+3%5Cu2033%22%7D%5D%7D"
    )
    assert _project(div) == [
        ["Name", ": ", ["Stub SN 2020xyz (4.940″ ", success_link, ")"]],
        ["Type", ": ", ["SN Ia (4.940″ ", success_link, ")"]],
        ["Distance", ": ", ["100.000 (z=0.020, 4.940″ ", success_link, ")"]],
        ["Average mag (including neighbourhood)", ": ", "zg  18.00", ", ", "zr  17.40", ", ", "(zg–zr)  0.60"],
        [
            "Search in brokers",
            ": ",
            {"text": "ALeRCE", "href": "https://alerce.online/?ra=10.0&dec=20.0&radius=3&page=1"},
            ", ",
            {"text": "Antares", "href": antares_href},
            ", ",
            {"text": "Fink", "href": "https://ztf.fink-portal.org/?action=conesearch&ra=10.0&dec=20.0&radius=3"},
            ", ",
            {"text": "MARS", "href": "https://mars.lco.global/?cone=10.0%2C20.0%2C0.0008333333333333334"},
        ],
        ["Coordinates", ": ", "Eq 10.00000 +20.00000", ", ", "Gal 00h40m00s +20d00m00s"],
    ]


# ---------------------------------------------------------------------------------------------
# get_layout -- only the cheap, upstream-free branch: object not found at all.
# ---------------------------------------------------------------------------------------------


async def test_get_layout_404_when_object_not_found():
    async def fake_find(oid, dr):
        raise NotFound

    with patch.object(viewer.find_ztf_oid, "find", fake_find):
        div = await get_layout("/dr24/view/1", search="")
    assert _project(div) == ["404", "Object 1 is not found in ZTF DR24"]


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
    assert _project(div) == [
        "**nobs**: 42",
        "**ngoodobs**: 40",
        "**filter**: zg",
        "**coord_string**: 10.00000 +20.00000",
        "**fieldid**: 796",
        "**rcid**: 12",
    ]


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
    assert _project(div) == [
        "**nobs**: 42",
        "**ngoodobs**: 40",
        "**filter**: zg",
        "**coord_string**: 10.00000 +20.00000",
        "**fieldid**: 796",
        "**rcid**: 12",
        "**ref_mag**: 44.825",
        "**ref_magerr**: 0.050",
        "**ref_flags**: 0",
    ]


# ---------------------------------------------------------------------------------------------
# set_features_list -- thin wrapper around `light_curve_features`.
# ---------------------------------------------------------------------------------------------


async def test_set_features_list_success():
    features = {"amplitude": 1.2345, "period_0_magn": 3.4567}
    with patch.object(viewer, "light_curve_features", AsyncMock(return_value=features)):
        div = await set_features_list(oid="633207400004730", dr="dr24", version="latest", min_mjd=None, max_mjd=None)
    assert _project(div) == ["**amplitude**: 1.234", "**period_0_magn**: 3.457"]


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

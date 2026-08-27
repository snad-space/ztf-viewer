"""Guards that a callback converted to ``async def`` this cycle doesn't leave a blocking call
directly in its body.

A coroutine callback is registered as-is and runs inline on the event loop, so anything
synchronous inside its body blocks the loop unless routed through a thread. Every callback below
still reaches a client that stayed synchronous on purpose (an unconverted conesearch ``find`` or
an astroquery client); this test pins that each such call is routed through ``asyncio.to_thread``
rather than called bare.

A fully general static check (walk every ``async def`` in the app and flag any call that isn't
either awaited or wrapped) is impractical here — it would need to know which callables are safe
to call inline (pure computation) versus which are blocking I/O, and that distinction isn't
recoverable from the AST alone. So this only covers the specific call sites this change touches.
"""

import asyncio
import inspect
import threading
from datetime import UTC, datetime

import httpx
import pytest

from ztf_viewer import config

config.CACHE_TYPE = "memory"
config.UNAVAILABLE_CATALOGS_CACHE_TYPE = "memory"

import ztf_viewer.__main__ as main_module
from ztf_viewer.catalogs.snad.catalog import snad_catalog as real_snad_catalog
from ztf_viewer.exceptions import NotFound
from ztf_viewer.pages import viewer

# function (or unbound method) -> a substring of the sync call it must route through a thread
CALLBACKS_WITH_REMAINING_BLOCKING_CALLS = {
    viewer.update_skybot_for_graph_clicked: "SKYBOT_QUERY.find",
    viewer.set_vizier_list: "find_vizier.find",
}


@pytest.mark.parametrize("func", list(CALLBACKS_WITH_REMAINING_BLOCKING_CALLS), ids=lambda f: f.__qualname__)
def test_async_callback_is_a_coroutine_function(func):
    assert inspect.iscoroutinefunction(inspect.unwrap(func))


@pytest.mark.parametrize(
    "func,blocking_call",
    CALLBACKS_WITH_REMAINING_BLOCKING_CALLS.items(),
    ids=[f.__qualname__ for f in CALLBACKS_WITH_REMAINING_BLOCKING_CALLS],
)
def test_remaining_blocking_call_goes_through_to_thread(func, blocking_call):
    source = inspect.getsource(inspect.unwrap(func))
    assert blocking_call in source, f"expected {func.__qualname__} to still call {blocking_call}"
    assert "asyncio.to_thread" in source, f"{func.__qualname__} calls {blocking_call} without asyncio.to_thread"


# --------------------------------------------------------------------------------------------
# SNAD catalog: now a genuine async port (ztf_viewer/catalogs/snad/catalog.py), not a thread
# hop. These pin the inverse of what this file pinned before: the lookup runs on the event
# loop's own thread, not offloaded, and no `asyncio.to_thread` appears in the call sites.
# --------------------------------------------------------------------------------------------


def test_sky_coord_from_str_snad_lookup_runs_on_the_loop(monkeypatch):
    loop_thread_id = threading.get_ident()
    seen_thread_id = None

    class StubSource:
        @classmethod
        async def create(cls, name):
            nonlocal seen_thread_id
            seen_thread_id = threading.get_ident()
            self = cls()
            self.coord = f"coord-for-{name}"
            return self

    monkeypatch.setattr(main_module, "SnadCatalogSource", StubSource)

    result = asyncio.run(main_module.sky_coord_from_str("SNAD123"))

    assert result == "coord-for-SNAD123"
    assert seen_thread_id == loop_thread_id


def test_sky_coord_from_str_reraises_not_found_as_value_error(monkeypatch):
    class StubSource:
        @classmethod
        async def create(cls, name):
            raise NotFound(name)

    monkeypatch.setattr(main_module, "SnadCatalogSource", StubSource)

    with pytest.raises(ValueError):
        asyncio.run(main_module.sky_coord_from_str("SNAD123"))


def test_sky_coord_from_str_does_not_mask_an_unrelated_key_error(monkeypatch):
    """A KeyError unrelated to the name lookup (e.g. surfacing from deep in the refresh
    path) must not be reported as an unknown SNAD ID.
    """

    class StubSource:
        @classmethod
        async def create(cls, name):
            raise KeyError("last-modified")

    monkeypatch.setattr(main_module, "SnadCatalogSource", StubSource)

    with pytest.raises(KeyError):
        asyncio.run(main_module.sky_coord_from_str("SNAD123"))


def test_oid_from_input_does_not_mask_an_unrelated_key_error(monkeypatch):
    class StubSource:
        @classmethod
        async def create(cls, name):
            raise KeyError("last-modified")

    monkeypatch.setattr(main_module, "SnadCatalogSource", StubSource)

    with pytest.raises(KeyError):
        asyncio.run(main_module.oid_from_input("SNAD123"))


def test_oid_from_input_snad_lookup_runs_on_the_loop_without_to_thread(monkeypatch):
    loop_thread_id = threading.get_ident()
    seen_thread_id = None

    class StubSource:
        @classmethod
        async def create(cls, name):
            nonlocal seen_thread_id
            seen_thread_id = threading.get_ident()
            self = cls()
            self.ztf_oid = 123
            return self

    monkeypatch.setattr(main_module, "SnadCatalogSource", StubSource)

    result = asyncio.run(main_module.oid_from_input("SNAD123"))

    assert result == "123"
    assert seen_thread_id == loop_thread_id

    source = inspect.getsource(inspect.unwrap(main_module.oid_from_input))
    assert "asyncio.to_thread" not in source


def test_set_title_snad_lookup_runs_on_the_loop(monkeypatch):
    loop_thread_id = threading.get_ident()
    seen_thread_id = None

    async def stub_get_coord(oid, dr):
        return 10.0, 20.0

    async def stub_search_region(ra, dec, radius_arcsec):
        nonlocal seen_thread_id
        seen_thread_id = threading.get_ident()
        return "SNAD1"

    monkeypatch.setattr(viewer.find_ztf_oid, "get_coord", stub_get_coord)
    monkeypatch.setattr(viewer.snad_catalog, "search_region", stub_search_region)

    result = asyncio.run(viewer.set_title("oid", "dr"))

    assert result == "SNAD1 — oid"
    assert seen_thread_id == loop_thread_id

    source = inspect.getsource(inspect.unwrap(viewer.set_title))
    assert "asyncio.to_thread" not in source


def test_oid_from_input_swallows_not_found(monkeypatch):
    class StubSource:
        @classmethod
        async def create(cls, name):
            raise NotFound(name)

    monkeypatch.setattr(main_module, "SnadCatalogSource", StubSource)

    result = asyncio.run(main_module.oid_from_input("SNAD123"))

    assert result == "SNAD123"


# --------------------------------------------------------------------------------------------
# End-to-end: a real refresh through the real SnadCatalogSource, not a stub. A response with no
# ``last-modified`` header must not surface as "ID ... isn't found in the SNAD catalog"; a
# genuinely unknown SNAD name still must.
# --------------------------------------------------------------------------------------------

_SNAD_CSV_HEADER = "Name,R.A.,Dec.,OID,Discovery date (UT),mag,er_down,er_up,ref,er_ref,TNS,Type,Comments"
_SNAD_CSV_ROW = "SNAD999,10.0,20.0,42,2018-04-08 09:45:49,21.11,0.27,0.36,20.84,0.06,AT 2018abc,PSN,test"
_SNAD_CSV_BODY = f"{_SNAD_CSV_HEADER}\n{_SNAD_CSV_ROW}\n"


def test_sky_coord_from_str_survives_a_response_with_no_last_modified_header(monkeypatch):
    async def handler(request):
        # No "last-modified" header at all, unlike a normal snad.space response.
        return httpx.Response(200, content=_SNAD_CSV_BODY.encode())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr("ztf_viewer.catalogs.snad.catalog.get_client", lambda: client)
    monkeypatch.setattr(real_snad_catalog, "updated_at", datetime(1900, 1, 1, tzinfo=UTC))
    monkeypatch.setattr(real_snad_catalog, "_failed_at", None)

    result = asyncio.run(main_module.sky_coord_from_str("SNAD999"))

    assert result is not None
    asyncio.run(client.aclose())


def test_sky_coord_from_str_still_reports_a_genuinely_unknown_name(monkeypatch):
    async def handler(request):
        return httpx.Response(200, content=_SNAD_CSV_BODY.encode())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr("ztf_viewer.catalogs.snad.catalog.get_client", lambda: client)
    monkeypatch.setattr(real_snad_catalog, "updated_at", datetime(1900, 1, 1, tzinfo=UTC))
    monkeypatch.setattr(real_snad_catalog, "_failed_at", None)

    with pytest.raises(ValueError, match="isn't found in the SNAD catalog"):
        asyncio.run(main_module.sky_coord_from_str("SNADNOTAREALNAME"))

    asyncio.run(client.aclose())


def test_set_title_propagates_not_found(monkeypatch):
    async def stub_get_coord(oid, dr):
        return 10.0, 20.0

    async def stub_search_region(ra, dec, radius_arcsec):
        raise NotFound

    monkeypatch.setattr(viewer.find_ztf_oid, "get_coord", stub_get_coord)
    monkeypatch.setattr(viewer.snad_catalog, "search_region", stub_search_region)

    result = asyncio.run(viewer.set_title("oid", "dr"))

    assert result == "oid"


# --------------------------------------------------------------------------------------------
# Extinction (ztf_viewer/catalogs/extinction/): now a genuine async port, not a thread hop. As
# above, pin the inverse of what this file used to pin: the lookup runs on the event loop's own
# thread, and no `asyncio.to_thread` appears at the touched call sites.
# --------------------------------------------------------------------------------------------


def test_fit_lc_extinction_lookup_runs_on_the_loop_without_to_thread(monkeypatch):
    loop_thread_id = threading.get_ident()
    seen_thread_id = None

    async def stub_get_sky_coord(oid, dr):
        return object()

    async def stub_ebv(coord):
        nonlocal seen_thread_id
        seen_thread_id = threading.get_ident()
        return 0.1

    monkeypatch.setattr(viewer.find_ztf_oid, "get_sky_coord", stub_get_sky_coord)
    monkeypatch.setattr(viewer.csfd, "ebv", stub_ebv)

    result = asyncio.run(
        viewer.fit_lc(
            cur_oid="123",
            dr="dr24",
            different_filter=None,
            different_field=None,
            min_mjd=None,
            max_mjd=None,
            ref_mag_ids=[],
            ref_mag_values=[],
            ref_magerr_ids=[],
            ref_magerr_values=[],
            name_model=None,
        )
    )

    assert seen_thread_id == loop_thread_id
    assert result[1] == {}

    source = inspect.getsource(inspect.unwrap(viewer.fit_lc))
    assert "asyncio.to_thread" not in source


def test_get_summary_extinction_lookups_have_no_to_thread():
    """`get_summary` is exercised end-to-end in `tests/pages/test_viewer.py`; this pins the
    narrower claim that its two extinction lookups (csfd.ebv, bayestar) are plain awaits.
    """
    source = inspect.getsource(inspect.unwrap(viewer.get_summary))
    assert "await csfd.ebv(coord)" in source
    assert "await bayestar(" in source
    assert "asyncio.to_thread" not in source

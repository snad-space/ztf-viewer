"""Guards that a callback converted to ``async def`` this cycle doesn't leave a blocking call
directly in its body.

A coroutine callback is registered as-is and runs inline on the event loop, so anything
synchronous inside its body blocks the loop unless routed through a thread. Every callback below
still reaches a client that stayed synchronous on purpose (an unconverted conesearch ``find``, an
astroquery client, or a still-sync extinction lookup); this test pins that each such call is
routed through ``asyncio.to_thread`` rather than called bare.

A fully general static check (walk every ``async def`` in the app and flag any call that isn't
either awaited or wrapped) is impractical here — it would need to know which callables are safe
to call inline (pure computation) versus which are blocking I/O, and that distinction isn't
recoverable from the AST alone. So this only covers the specific call sites this change touches.
"""

import asyncio
import inspect
import threading

import pytest

from ztf_viewer import config

config.CACHE_TYPE = "memory"
config.UNAVAILABLE_CATALOGS_CACHE_TYPE = "memory"

import ztf_viewer.__main__ as main_module
from ztf_viewer.exceptions import NotFound
from ztf_viewer.pages import viewer

# function (or unbound method) -> a substring of the sync call it must route through a thread
CALLBACKS_WITH_REMAINING_BLOCKING_CALLS = {
    viewer.fit_lc: "csfd.ebv",
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


def test_sky_coord_from_str_reraises_key_error_as_value_error(monkeypatch):
    class StubSource:
        @classmethod
        async def create(cls, name):
            raise KeyError(name)

    monkeypatch.setattr(main_module, "SnadCatalogSource", StubSource)

    with pytest.raises(ValueError):
        asyncio.run(main_module.sky_coord_from_str("SNAD123"))


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


def test_set_title_propagates_not_found(monkeypatch):
    async def stub_get_coord(oid, dr):
        return 10.0, 20.0

    async def stub_search_region(ra, dec, radius_arcsec):
        raise NotFound

    monkeypatch.setattr(viewer.find_ztf_oid, "get_coord", stub_get_coord)
    monkeypatch.setattr(viewer.snad_catalog, "search_region", stub_search_region)

    result = asyncio.run(viewer.set_title("oid", "dr"))

    assert result == "oid"

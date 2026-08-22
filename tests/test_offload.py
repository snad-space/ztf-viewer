"""Tests for the per-upstream bounded thread offload (``ztf_viewer/offload.py``).

The load-bearing one is ``test_stalled_upstream_does_not_block_an_unrelated_one`` -- the
acceptance criterion for bounding sync third-party clients (astroquery, alerce, antares_client)
behind per-upstream semaphores rather than one shared, unbounded ``asyncio.to_thread`` pool. Both
timing-sensitive tests below synchronize with ``threading.Event`` so they are deterministic: a
broken semaphore makes them hang (and time out), not flake.
"""

import asyncio
import threading

from ztf_viewer import config, offload


async def test_bare_to_thread_when_upstream_is_none():
    """``upstream=None`` behaves like a plain ``asyncio.to_thread``: no semaphore involved."""
    assert await offload.to_thread(None, lambda x: x * 2, 21) == 42


async def test_stalled_upstream_does_not_block_an_unrelated_one(monkeypatch):
    """One upstream stuck mid-call must not consume another upstream's thread budget."""
    monkeypatch.setitem(config.UPSTREAM_THREAD_LIMITS, "test-stalled", 1)
    monkeypatch.setitem(config.UPSTREAM_THREAD_LIMITS, "test-fast", 1)

    started = threading.Event()
    release = threading.Event()

    def blocking_stalled():
        started.set()
        release.wait(timeout=5)
        return "stalled"

    stalled_task = asyncio.create_task(offload.to_thread("test-stalled", blocking_stalled))
    # Wait for the stalled call to actually be running in its thread -- not a fixed sleep.
    await asyncio.to_thread(started.wait, 5)

    # A different upstream's semaphore must still be free.
    fast_result = await asyncio.wait_for(offload.to_thread("test-fast", lambda: "fast"), timeout=5)
    assert fast_result == "fast"

    release.set()
    assert await stalled_task == "stalled"


async def test_same_upstream_limit_is_enforced(monkeypatch):
    """A second call to an upstream whose limit is one thread must find the semaphore held."""
    monkeypatch.setitem(config.UPSTREAM_THREAD_LIMITS, "test-solo", 1)

    started = threading.Event()
    release = threading.Event()

    def blocking():
        started.set()
        release.wait(timeout=5)
        return "done"

    task = asyncio.create_task(offload.to_thread("test-solo", blocking))
    await asyncio.to_thread(started.wait, 5)

    semaphore = offload._semaphore_registry("test-solo").get()
    assert semaphore.locked()

    release.set()
    assert await task == "done"
    assert not semaphore.locked()


async def test_semaphore_size_comes_from_config(monkeypatch):
    """The number of concurrent slots for an upstream is exactly its configured limit."""
    monkeypatch.setitem(config.UPSTREAM_THREAD_LIMITS, "test-sized", 2)
    semaphore = offload._semaphore_registry("test-sized").get()

    assert not semaphore.locked()
    await semaphore.acquire()
    assert not semaphore.locked()  # one of two slots taken
    await semaphore.acquire()
    assert semaphore.locked()  # both slots taken
    semaphore.release()
    semaphore.release()


def test_offload_works_across_two_successive_event_loops(monkeypatch):
    """Simulates Flask's per-request loop: a second, fresh loop must not raise even though the
    semaphore built for the first loop -- itself loop-affine -- is long gone."""
    monkeypatch.setitem(config.UPSTREAM_THREAD_LIMITS, "test-cross-loop", 2)

    async def body():
        return await offload.to_thread("test-cross-loop", lambda: "ok")

    assert asyncio.run(body()) == "ok"
    assert asyncio.run(body()) == "ok"


def test_every_class_tagged_upstream_has_a_configured_limit():
    """Every ``_query_region_upstream``/``_light_curve_upstream`` used by a catalog class, plus
    the standalone Vizier/MOCServer/Skybot/Sesame call sites, must resolve in
    ``config.UPSTREAM_THREAD_LIMITS`` -- otherwise the first real call raises a ``KeyError``
    instead of degrading gracefully."""
    from ztf_viewer.catalogs.conesearch._base import _BaseVizierQuery
    from ztf_viewer.catalogs.conesearch.alerce import AlerceQuery
    from ztf_viewer.catalogs.conesearch.antares import AntaresQuery
    from ztf_viewer.catalogs.conesearch.gaia_dr3 import GaiaDr3Query
    from ztf_viewer.catalogs.conesearch.simbad import SimbadQuery

    used_upstreams = {
        _BaseVizierQuery._query_region_upstream,
        SimbadQuery._query_region_upstream,
        AlerceQuery._query_region_upstream,
        AntaresQuery._query_region_upstream,
        AntaresQuery._light_curve_upstream,
        GaiaDr3Query._light_curve_upstream,
        "mocserver",  # catalogs/vizier.py VizierCatalogDetails.description
        "skybot",  # catalogs/skybot.py SkybotQuery.find
        "sesame",  # __main__.py get_icrs_coordinates
    }
    for upstream in used_upstreams:
        assert upstream in config.UPSTREAM_THREAD_LIMITS, upstream


def test_gaia_query_region_and_light_curve_use_different_upstreams():
    """`_query_region` (inherited from `_BaseVizierQuery`) hits Vizier; `light_curve` hits the
    separate Gaia archive -- one class, two upstreams, so a single class attribute isn't enough."""
    from ztf_viewer.catalogs.conesearch.gaia_dr3 import GaiaDr3Query

    assert GaiaDr3Query._query_region_upstream == "vizier"
    assert GaiaDr3Query._light_curve_upstream == "gaia"


async def test_skybot_find_routes_through_the_skybot_semaphore(monkeypatch):
    from ztf_viewer.catalogs.skybot import SkybotQuery

    seen = {}

    async def fake_to_thread(upstream, func, *args, **kwargs):
        seen["upstream"] = upstream
        return func(*args, **kwargs)

    monkeypatch.setattr("ztf_viewer.offload.to_thread", fake_to_thread)
    monkeypatch.setattr(SkybotQuery, "_find_sync", lambda self, *a, **k: "sentinel")

    query = SkybotQuery.__new__(SkybotQuery)  # skip __init__'s astroquery.imcce.Skybot() build
    assert await query.find(1.0, 2.0, 59000.0, radius_arcsec=10.0) == "sentinel"
    assert seen["upstream"] == "skybot"


async def test_find_vizier_routes_through_the_vizier_semaphore(monkeypatch):
    from ztf_viewer.catalogs.vizier import FindVizier

    seen = {}

    async def fake_to_thread(upstream, func, *args, **kwargs):
        seen["upstream"] = upstream
        return func(*args, **kwargs)

    monkeypatch.setattr("ztf_viewer.offload.to_thread", fake_to_thread)
    monkeypatch.setattr(FindVizier, "_find_sync", lambda self, *a, **k: "sentinel")

    query = FindVizier.__new__(FindVizier)  # skip __init__'s astroquery.vizier.Vizier() build
    assert await query.find(1.0, 2.0, 10.0) == "sentinel"
    assert seen["upstream"] == "vizier"


async def test_vizier_catalog_details_routes_through_the_mocserver_semaphore(monkeypatch):
    from ztf_viewer.catalogs.vizier import VizierCatalogDetails

    seen = {}

    async def fake_to_thread(upstream, func, *args, **kwargs):
        seen["upstream"] = upstream
        return func(*args, **kwargs)

    monkeypatch.setattr("ztf_viewer.offload.to_thread", fake_to_thread)
    monkeypatch.setattr(
        VizierCatalogDetails, "_query_cds_sync", staticmethod(lambda catalog_id: {"obs_description": "d"})
    )

    assert await VizierCatalogDetails.description("some-catalog") == "d"
    assert seen["upstream"] == "mocserver"


async def test_alerce_add_prob_class_columns_routes_through_the_alerce_semaphore(monkeypatch):
    """Regression test: this call used to run inline on the event loop with no offload at all --
    `_query_region` was offloaded, but `add_prob_class_columns` is invoked separately, straight
    from `find()`, and was missed."""
    from ztf_viewer.catalogs.conesearch.alerce import AlerceQuery

    seen = {}

    async def fake_to_thread(upstream, func, *args, **kwargs):
        seen["upstream"] = upstream
        return func(*args, **kwargs)

    monkeypatch.setattr("ztf_viewer.offload.to_thread", fake_to_thread)
    monkeypatch.setattr(
        AlerceQuery, "_add_prob_class_columns_sync", lambda self, table: seen.setdefault("table", table)
    )

    # object.__new__, not AlerceQuery.__new__: `_BaseCatalogQuery.__new__` requires a
    # `query_name` and registers the instance in a class-level dict, neither of which this test
    # needs -- it only exercises `add_prob_class_columns`.
    query = object.__new__(AlerceQuery)
    await query.add_prob_class_columns("a-table")
    assert seen["upstream"] == "alerce"
    assert seen["table"] == "a-table"

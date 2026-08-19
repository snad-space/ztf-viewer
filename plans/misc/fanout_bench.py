"""Baseline for the `get_summary` per-catalog fan-out (`ztf_viewer/pages/viewer.py`).

`get_summary` loops `for catalog, query in catalog_query_objects().items(): table = await
query.find(...)`, serially awaiting each catalog's cone-search query. This harness reproduces
that loop shape over **stub** catalogs -- each `find()` is `sleep(delay)` then return -- rather
than a recording, because the delay is the point and should be explicit and tunable, not baked
into a fixture. It is not a test: it prints a wall-clock number and makes no assertion. The
assertion that concurrent elapsed is ~delay, not ~N*delay, belongs to the PR that makes it true
by replacing this loop with `asyncio.gather`.

Drives the loop shape rather than the real `get_summary`, because the latter also touches dust
maps, light-curve fetches, and broker link building -- machinery unrelated to the fan-out and
irrelevant to what this measures. The loop reproduced here is `get_summary`'s first pass (the one
that builds the summary table); the second pass, over the same catalogs for ML classifications,
hits `find()`'s `@cache()` and is nearly free in production, so it is not modeled here.

An `asyncio.gather` run is included alongside the serial one purely as an illustrative reference
for the size of the win -- it is not `aio-gather`'s implementation and proves nothing on its own.

Run: python plans/misc/fanout_bench.py
Run: python plans/misc/fanout_bench.py --catalogs 19 --delay 0.5
"""

import argparse
import asyncio
import time

# ~19 mirrors today's catalog_query_objects(); see ztf_viewer/catalogs/conesearch/__init__.py.
DEFAULT_CATALOGS = 19
# Large enough that N*delay serial is obviously not delay concurrent, small enough to run fast.
DEFAULT_DELAY = 0.5


class _StubCatalogQuery:
    """Stands in for a `_BaseCatalogQuery` instance: same `find(ra, dec, radius)` shape."""

    def __init__(self, name, delay):
        self.query_name = name
        self._delay = delay

    async def find(self, ra, dec, radius_arcsec):
        await asyncio.sleep(self._delay)
        return {"ra": ra, "dec": dec, "radius_arcsec": radius_arcsec, "catalog": self.query_name}


def _stub_catalogs(n, delay):
    return {f"stub-catalog-{i}": _StubCatalogQuery(f"Stub Catalog {i}", delay) for i in range(n)}


async def _serial_fanout(catalogs, ra, dec, radius_arcsec):
    """Mirrors `get_summary`'s current loop: await each catalog's `find()` in turn."""
    results = {}
    for name, query in catalogs.items():
        results[name] = await query.find(ra, dec, radius_arcsec)
    return results


async def _concurrent_fanout(catalogs, ra, dec, radius_arcsec):
    """Illustrative only -- the real conversion is a separate PR, not this harness."""
    names = list(catalogs)
    values = await asyncio.gather(*(catalogs[name].find(ra, dec, radius_arcsec) for name in names))
    return dict(zip(names, values))


def _timed(coro_factory):
    async def run():
        start = time.perf_counter()
        await coro_factory()
        return time.perf_counter() - start

    return asyncio.run(run())


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--catalogs", type=int, default=DEFAULT_CATALOGS, help="number of stub catalogs")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY, help="per-catalog find() delay, seconds")
    args = parser.parse_args()

    catalogs = _stub_catalogs(args.catalogs, args.delay)
    ra, dec, radius_arcsec = 180.0, 0.0, 5.0

    serial = _timed(lambda: _serial_fanout(catalogs, ra, dec, radius_arcsec))
    concurrent = _timed(lambda: _concurrent_fanout(catalogs, ra, dec, radius_arcsec))

    print(f"{args.catalogs} stub catalogs, {args.delay:.3f}s delay each\n")
    print(f"{'mode':22s} {'elapsed':>10s} {'expected':>10s}")
    print("-" * 46)
    print(f"{'serial (today)':22s} {serial:9.3f}s {args.catalogs * args.delay:9.3f}s")
    print(f"{'gather (reference)':22s} {concurrent:9.3f}s {args.delay:9.3f}s")


if __name__ == "__main__":
    main()

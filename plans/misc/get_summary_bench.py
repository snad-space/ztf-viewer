"""Cold `get_summary` wall-clock, against real upstreams -- not stubs.

`plans/misc/fanout_bench.py` times the loop *shape* over sleep stubs and imports nothing from
`ztf_viewer`; it cannot measure the real change. This script calls the real, unwrapped
`ztf_viewer.pages.viewer.get_summary` for a real object, against the real ~19 cone-search
catalogs, the real light-curve-features API, and the real dust maps -- the same call a page load
makes.

"Cold" means the in-memory cache is cleared before every timed call (`CACHE_TYPE=memory` is forced
below so there is a cache to clear without a Redis instance). It does not flush any upstream's own
cache/CDN.

Run each timed sample as its **own process**, not via `--runs N>1` in one process: a failing
catalog gets recorded in the in-memory `unavailable_catalogs` set on its first failure, so a
second call in the same process skips it near-instantly instead of retrying it -- fast, but no
longer cold for that catalog. `--runs` exists for a quick illustrative range, not for the
comparison number.

Compare before/after by running this script once per checkout, each as a fresh process: check out
the pre-change code for a "before" measurement, the post-change code for "after". Both must be run
with the same OID, DR, radius and catalog set -- only the loop should differ.

Run: python plans/misc/get_summary_bench.py
Run: python plans/misc/get_summary_bench.py --oid 633207400004730 --dr dr24 --runs 1
"""

import argparse
import asyncio
import inspect
import statistics
import sys
import time
from pathlib import Path

# Run as a script, `ztf_viewer` would otherwise resolve through the venv's editable-install
# pointer (whatever checkout it was `pip install -e`d from) rather than this checkout -- put this
# repo root first so the code under test is actually the one being edited.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ztf_viewer import config

# Force the in-memory cache backend before any `ztf_viewer` submodule imports it, the same way
# tests/pages/test_viewer.py does -- a Redis-backed cache would carry a hit across "cold" runs.
config.CACHE_TYPE = "memory"
config.UNAVAILABLE_CATALOGS_CACHE_TYPE = "memory"

DEFAULT_OID = "633207400004730"  # the app's own placeholder example (ztf_viewer/__main__.py)
DEFAULT_DR = "dr24"
DEFAULT_RADIUS_ARCSEC = 10.0


async def _time_one_call(get_summary, oid, dr, radius_ids, radius_values):
    from ztf_viewer import cache

    cache.clear_memory_caches()
    start = time.perf_counter()
    await get_summary(
        oid=oid,
        dr=dr,
        different_filter=None,
        different_field=None,
        radius_ids=radius_ids,
        radius_values=radius_values,
    )
    return time.perf_counter() - start


async def _run(oid, dr, radius_arcsec, n_runs):
    from ztf_viewer.catalogs.conesearch import catalog_query_objects
    from ztf_viewer.pages import viewer

    get_summary = inspect.unwrap(viewer.get_summary)
    catalogs = list(catalog_query_objects())
    radius_ids = [{"type": "search-radius", "index": name} for name in catalogs]
    radius_values = [radius_arcsec] * len(catalogs)

    print(f"oid={oid} dr={dr} catalogs={len(catalogs)} radius_arcsec={radius_arcsec} runs={n_runs}\n")

    elapsed = []
    for i in range(n_runs):
        t = await _time_one_call(get_summary, oid, dr, radius_ids, radius_values)
        elapsed.append(t)
        print(f"run {i + 1}/{n_runs}: {t:.3f}s")

    print(f"\nmin={min(elapsed):.3f}s  median={statistics.median(elapsed):.3f}s  max={max(elapsed):.3f}s")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--oid", default=DEFAULT_OID)
    parser.add_argument("--dr", default=DEFAULT_DR)
    parser.add_argument("--radius-arcsec", type=float, default=DEFAULT_RADIUS_ARCSEC)
    parser.add_argument("--runs", type=int, default=1)
    args = parser.parse_args()

    asyncio.run(_run(args.oid, args.dr, args.radius_arcsec, args.runs))


if __name__ == "__main__":
    main()

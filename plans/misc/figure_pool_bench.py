"""Does moving figure rendering off `asyncio.to_thread` and onto the process pool stop a
concurrent figure flood from starving unrelated event-loop work?

`plans/misc/gil_bench.py` already showed matplotlib Agg PNG barely scales on threads (1.25x
on 4) while the PGF/LaTeX PDF path scales well (3.33x, because it waits on a LaTeX child
process and releases the GIL). This script asks the follow-on question directly: while N
concurrent figure renders are in flight, does an unrelated coroutine on the same loop keep
making progress?

The workload goes through the real render path, `ztf_viewer.figure_render.plot_data`, over a
synthetic light curve shaped like `get_plot_data`'s output (only the keys the renderer reads),
so no network or cache is needed to run this. Two offload strategies are compared per format:

  - "thread"  -- `asyncio.to_thread`, the mechanism before this change.
  - "process" -- `ztf_viewer.procpool.run_in_process`, this change.

While the flood runs, a heartbeat coroutine repeatedly does `await asyncio.sleep(0)` on the
same loop, standing in for "any other request being served concurrently". Its metric is the
worst gap between two ticks: how long the loop went unresponsive because of the flood.

Run: python plans/misc/figure_pool_bench.py
Run: python plans/misc/figure_pool_bench.py --renders 4 --n-obs 800 --formats png,pdf
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path

# Run as a script, `ztf_viewer` would otherwise resolve through the venv's editable-install
# pointer rather than this checkout -- put this repo root first, matching get_summary_bench.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ztf_viewer.figure_render import plot_data
from ztf_viewer.procpool import run_in_process, shutdown_pool

OID = 1
FILTERS = ["zg", "zr", "zi"]


def _synthetic_lc(n_obs: int) -> dict:
    """A light curve shaped like one entry of `get_plot_data`'s output -- only the keys
    `plot_data` actually reads."""
    obs = [
        {
            "mjd": 58000.0 + i * 0.3,
            "mag": 18.0 + 0.5 * ((i % 7) - 3),
            "magerr": 0.05 + 0.01 * (i % 5),
            "filter": FILTERS[i % len(FILTERS)],
        }
        for i in range(n_obs)
    ]
    return {OID: obs}


async def _heartbeat(stop_event: asyncio.Event) -> list[float]:
    """Ticks on the loop as fast as it's allowed to; records the gap since the last tick."""
    gaps = []
    last = time.perf_counter()
    while not stop_event.is_set():
        await asyncio.sleep(0)
        now = time.perf_counter()
        gaps.append(now - last)
        last = now
    return gaps


async def _flood_thread(data: dict, fmt: str, n: int) -> None:
    await asyncio.gather(*(asyncio.to_thread(plot_data, OID, data, fmt=fmt) for _ in range(n)))


async def _flood_process(data: dict, fmt: str, n: int) -> None:
    await asyncio.gather(*(run_in_process(plot_data, OID, data, fmt=fmt) for _ in range(n)))


async def _measure(flood, data: dict, fmt: str, n: int) -> tuple[float, float, int]:
    stop_event = asyncio.Event()
    heartbeat_task = asyncio.create_task(_heartbeat(stop_event))
    t0 = time.perf_counter()
    await flood(data, fmt, n)
    elapsed = time.perf_counter() - t0
    stop_event.set()
    gaps = await heartbeat_task
    return elapsed, max(gaps) if gaps else 0.0, len(gaps)


async def _run_all(n_obs: int, renders: int, formats: list[str]) -> None:
    data = _synthetic_lc(n_obs)

    # Warm up: first thread call pays interpreter/font-cache warmup, first process call pays
    # the child's cold import, matplotlib rcParam setup -- neither should count against either
    # strategy's flood measurement below.
    await asyncio.to_thread(plot_data, OID, data, fmt="png")
    await run_in_process(plot_data, OID, data, fmt="png")

    print(f"{renders} concurrent renders, {n_obs} observations each\n")
    print(f"{'format':6s} {'strategy':18s} {'flood':>10s} {'max heartbeat gap':>20s} {'heartbeat ticks':>16s}")
    print("-" * 76)
    for fmt in formats:
        for label, flood in (("thread (before)", _flood_thread), ("process (after)", _flood_process)):
            elapsed, max_gap, ticks = await _measure(flood, data, fmt, renders)
            print(f"{fmt:6s} {label:18s} {elapsed:9.3f}s {max_gap * 1000:17.1f}ms {ticks:16d}")

    shutdown_pool()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--renders", type=int, default=4, help="number of concurrent figure renders per strategy")
    parser.add_argument("--n-obs", type=int, default=800, help="observations per synthetic light curve")
    parser.add_argument("--formats", type=str, default="png,pdf", help="comma-separated formats to test")
    args = parser.parse_args()

    formats = [f.strip() for f in args.formats.split(",") if f.strip()]
    asyncio.run(_run_all(args.n_obs, args.renders, formats))


if __name__ == "__main__":
    main()

"""Does `THREAD_POOL_SIZE` (default 16) hold up once several page loads run concurrently?

`plans/001_async_dash.md`'s `aio-gather` Progress entry leaves this open twice: "the PR found no
load-bearing reason to change [`THREAD_POOL_SIZE`] ... but did not build the concurrent-multi-
page-load test that would actually stress pool *width* ... this is a reviewer call recorded here,
not a measurement." This script is that test.

**What this drives, and why not the real catalog clients.** Sandbox network reachability is
broken here -- `get_summary_bench.py`'s own Progress entry records a plain, non-concurrent
`requests.get()` to Vizier failing at the socket level in this environment -- so a benchmark that
calls real astroquery/alerce/antares clients would mostly measure connection-refused latency, not
pool contention, and the numbers would not transfer anywhere. Instead this drives the *real*
production pool-sizing mechanics -- a `concurrent.futures.ThreadPoolExecutor(max_workers=...)`
installed via `loop.set_default_executor`, exactly what `ztf_viewer.__main__._size_thread_pools`
does -- against a **synthetic blocking-I/O stand-in**: `time.sleep(delay)` behind
`asyncio.to_thread`. `gil_bench.py` already established that `time.sleep` is a fair proxy for
blocking socket I/O (it releases the GIL for its whole duration, same as a blocking `requests`
call sitting in `recv()`), which is what every sync catalog client here actually does. **What
this does NOT prove:** real per-catalog latency, real astroquery/alerce parsing cost, or anything
about upstream fairness (a stalled real upstream vs. a fixed-delay stub behave differently under
timeout/retry). It proves how the pool *itself* behaves under width pressure -- queueing, not
upstream cost -- which is exactly the gap the Progress entry names.

**Fan-out shape.** One page load's `get_summary` gathers ~19 catalogs concurrently (`aio-gather`);
grepping `ztf_viewer/catalogs/conesearch/*.py` for catalogs whose `_query_region` has no `async`
override (wrapped by `_ensure_coroutine` -> `asyncio.to_thread`) finds 9: antares, alerce,
astrocats, fink, otter, ogle, colibri, simbad, tns. `set_tables` separately offloads a Vizier
`find()` and catalog-description lookups (`viewer.py:2140,2148`), and dust-map lookups
(`viewer.py:919,1532,1541`) run in their own concurrent callbacks. So one page load puts roughly
ten thread-offloaded calls in flight at once, not one -- `--sync-calls-per-load` defaults to that
estimate and is documented as an estimate, not a measurement.

**Queueing delay, made visible.** Each stubbed call records its own submit time (in the coroutine,
before handing off) and its start time (inside the thread, first line of the function body).
`queue_delay = start - submit` is time spent waiting for a free pool slot; the rest is the
`delay` argument itself, i.e. simulated "execution". Reported as p50/p95/max across all calls in
a sweep point, not just a mean -- the tail is the part that matters once N exceeds pool width.

**Process pool.** `PROCESS_POOL_SIZE` (default 2) is included for honesty: it is the narrower
resource -- half the width of the thread pool's default -- and the plan's own `## Open questions`
records it queueing ~1s behind two concurrent renders. This uses the real
`ztf_viewer.procpool._ProcessPool` class (not the module singleton, so the sweep can vary
`max_workers` without touching production state) against a synthetic CPU+sleep stand-in for a
figure render or CSV assembly.

Run: python plans/misc/pool_width_bench.py
Run: python plans/misc/pool_width_bench.py --pool-sizes 8,16,32 --concurrency 1,2,4,8,16 --delay 0.3
Run: python plans/misc/pool_width_bench.py --skip-process-pool
"""

import argparse
import asyncio
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Run as a script, `ztf_viewer` would otherwise resolve through the venv's editable-install
# pointer rather than this checkout -- matches get_summary_bench.py / figure_pool_bench.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ztf_viewer.procpool import _ProcessPool

DEFAULT_POOL_SIZES = [8, 16, 32]
DEFAULT_CONCURRENCY = [1, 2, 4, 8, 16]
# Order-of-magnitude stand-in for a blocking catalog round trip; matches fanout_bench.py's own
# DEFAULT_DELAY choice for the same reason -- large enough that serialization is obvious, small
# enough that a full sweep still runs in seconds.
DEFAULT_DELAY = 0.3
# See the module docstring's "Fan-out shape" paragraph -- an estimate, not a measurement.
DEFAULT_SYNC_CALLS_PER_LOAD = 10

DEFAULT_PROCESS_POOL_SIZES = [2, 4]
DEFAULT_PROCESS_CONCURRENCY = [1, 2, 4, 8]
DEFAULT_PROCESS_DELAY = 0.2


def _blocking_call(delay: float) -> tuple[float, float]:
    """Runs in a pool thread. Returns (start, end) so the caller can derive queue delay."""
    start = time.perf_counter()
    time.sleep(delay)
    end = time.perf_counter()
    return start, end


def _process_call(delay: float) -> tuple[float, float]:
    """Runs in a pool *process* -- module-level and picklable, per `procpool.py`'s own rule."""
    start = time.perf_counter()
    # A little real CPU work alongside the sleep, so this isn't purely a GIL-release stand-in --
    # a figure render or CSV assembly does real arithmetic between its I/O-shaped waits.
    total = 0
    for i in range(200_000):
        total += i * i
    time.sleep(delay)
    end = time.perf_counter()
    return start, end


async def _timed_thread_call(delay: float) -> tuple[float, float, float]:
    submit = time.perf_counter()
    start, end = await asyncio.to_thread(_blocking_call, delay)
    return submit, start, end


async def _timed_process_call(pool: _ProcessPool, delay: float) -> tuple[float, float, float]:
    submit = time.perf_counter()
    start, end = await pool.run(_process_call, delay)
    return submit, start, end


def _summarize(samples: list[tuple[float, float, float]]) -> dict:
    queue_delays = [start - submit for submit, start, _ in samples]
    exec_times = [end - start for _, start, end in samples]
    quantiles = statistics.quantiles(queue_delays, n=100) if len(queue_delays) > 1 else queue_delays * 100
    return {
        "n": len(samples),
        "queue_p50": quantiles[49] if len(quantiles) >= 50 else queue_delays[0],
        "queue_p95": quantiles[94] if len(quantiles) >= 95 else max(queue_delays),
        "queue_max": max(queue_delays),
        "exec_mean": statistics.mean(exec_times),
    }


async def _run_thread_sweep_point(pool_size: int, n_loads: int, calls_per_load: int, delay: float) -> dict:
    executor = ThreadPoolExecutor(max_workers=pool_size, thread_name_prefix="pool-width-bench")
    loop = asyncio.get_running_loop()
    loop.set_default_executor(executor)
    try:
        # Thread spin-up is near-instant, but warm anyway so every pool_size/n_loads point
        # starts from the same state -- consistent with the process-pool warm-up below.
        await _timed_thread_call(0.0)
        total_calls = n_loads * calls_per_load
        wall_start = time.perf_counter()
        samples = await asyncio.gather(*(_timed_thread_call(delay) for _ in range(total_calls)))
        wall = time.perf_counter() - wall_start
    finally:
        executor.shutdown(wait=True)
    summary = _summarize(samples)
    summary["wall"] = wall
    return summary


async def _run_process_sweep_point(pool_size: int, n_concurrent: int, delay: float) -> dict:
    pool = _ProcessPool(max_workers=pool_size)
    # `aio-profile`'s Progress entry measured a ~560ms cold start per worker process (import,
    # matplotlib rcParam setup, etc. in the real case). Warm every worker first so the timed
    # samples below measure queueing for a hot pool, not spawn cost -- that cost is real and
    # already documented, not something this sweep needs to rediscover.
    await asyncio.gather(*(pool.run(_process_call, 0.0) for _ in range(pool_size)))
    wall_start = time.perf_counter()
    samples = await asyncio.gather(*(_timed_process_call(pool, delay) for _ in range(n_concurrent)))
    wall = time.perf_counter() - wall_start
    pool.shutdown()
    summary = _summarize(samples)
    summary["wall"] = wall
    return summary


async def _run_thread_sweep(pool_sizes, concurrency, calls_per_load, delay) -> None:
    print(f"THREAD POOL -- {calls_per_load} thread-offloaded calls/page load, {delay:.2f}s each\n")
    header = (
        f"{'pool':>5s} {'loads':>6s} {'calls':>6s} "
        f"{'queue p50':>10s} {'queue p95':>10s} {'queue max':>10s} {'exec~':>8s} {'wall':>8s}"
    )
    print(header)
    print("-" * len(header))
    for pool_size in pool_sizes:
        for n_loads in concurrency:
            summary = await _run_thread_sweep_point(pool_size, n_loads, calls_per_load, delay)
            print(
                f"{pool_size:5d} {n_loads:6d} {summary['n']:6d} "
                f"{summary['queue_p50'] * 1000:9.1f}ms {summary['queue_p95'] * 1000:9.1f}ms "
                f"{summary['queue_max'] * 1000:9.1f}ms {summary['exec_mean']:7.3f}s {summary['wall']:7.3f}s"
            )
        print()


async def _run_process_sweep(pool_sizes, concurrency, delay) -> None:
    print(f"PROCESS POOL -- 1 CPU+sleep render per submission, {delay:.2f}s sleep each\n")
    header = f"{'pool':>5s} {'concur':>6s} " f"{'queue p50':>10s} {'queue p95':>10s} {'queue max':>10s} {'wall':>8s}"
    print(header)
    print("-" * len(header))
    for pool_size in pool_sizes:
        for n in concurrency:
            summary = await _run_process_sweep_point(pool_size, n, delay)
            print(
                f"{pool_size:5d} {n:6d} "
                f"{summary['queue_p50'] * 1000:9.1f}ms {summary['queue_p95'] * 1000:9.1f}ms "
                f"{summary['queue_max'] * 1000:9.1f}ms {summary['wall']:7.3f}s"
            )
        print()


def _parse_int_list(s: str) -> list[int]:
    return [int(x.strip()) for x in s.split(",") if x.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pool-sizes", type=_parse_int_list, default=DEFAULT_POOL_SIZES)
    parser.add_argument(
        "--concurrency", type=_parse_int_list, default=DEFAULT_CONCURRENCY, help="concurrent page loads"
    )
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY, help="per thread-offloaded call, seconds")
    parser.add_argument("--sync-calls-per-load", type=int, default=DEFAULT_SYNC_CALLS_PER_LOAD)
    parser.add_argument("--skip-process-pool", action="store_true")
    parser.add_argument("--process-pool-sizes", type=_parse_int_list, default=DEFAULT_PROCESS_POOL_SIZES)
    parser.add_argument("--process-concurrency", type=_parse_int_list, default=DEFAULT_PROCESS_CONCURRENCY)
    parser.add_argument("--process-delay", type=float, default=DEFAULT_PROCESS_DELAY)
    args = parser.parse_args()

    asyncio.run(_run_thread_sweep(args.pool_sizes, args.concurrency, args.sync_calls_per_load, args.delay))

    if not args.skip_process_pool:
        asyncio.run(_run_process_sweep(args.process_pool_sizes, args.process_concurrency, args.process_delay))


if __name__ == "__main__":
    main()

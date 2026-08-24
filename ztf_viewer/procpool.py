"""A process-wide ``ProcessPoolExecutor`` for CPU-bound offload.

Unlike the resources in :mod:`ztf_viewer.loop_registry`, a ``ProcessPoolExecutor`` is not
loop-affine: it does not open anything against ``asyncio.get_running_loop()`` at construction
time, and ``loop.run_in_executor`` (or wrapping ``.submit()`` with ``asyncio.wrap_future``, as
below) accepts an executor built long before that loop existed. So the loop-registry pattern
does not apply here, for the same reason ``ztf_viewer/__main__.py``'s ``_thread_pool`` is one per
process rather than one per loop: keying it by loop would spawn a fresh set of child processes
every time a new loop asked for one, which is exactly what a per-request loop model would do on
every single request. One pool for the life of the process is what a process pool means.

The pool is still built lazily rather than at import time: constructing ``ProcessPoolExecutor``
does not itself spawn workers (they start on first submit), but nothing needs it before the
first CPU-bound offload, and every test run and ``--help`` invocation would rather not import a
multiprocessing-adjacent module for nothing.
"""

import asyncio
import threading
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from typing import Callable, TypeVar

from ztf_viewer.config import PROCESS_POOL_SIZE

_T = TypeVar("_T")

_pool: ProcessPoolExecutor | None = None
_pool_lock = threading.Lock()


def get_pool() -> ProcessPoolExecutor:
    """Return the process-wide pool, building it on first use."""
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ProcessPoolExecutor(max_workers=PROCESS_POOL_SIZE)
        return _pool


async def run_in_process(fn: Callable[..., _T], *args, **kwargs) -> _T:
    """Await ``fn(*args, **kwargs)`` run in the process pool.

    ``fn`` must be a module-level function with no captured state: the spawn start method
    (macOS default; the container forks, but code must not rely on that) re-imports the
    target module in the child, so closures, lambdas and bound methods cannot cross the
    pickling boundary a process pool requires.

    A crash in the child (killed, segfaults, etc.) raises ``BrokenProcessPool`` here rather
    than hanging, matching a normal exception's behaviour. Once broken, every future submitted
    to the same executor fails the same way, so a broken pool is dropped and rebuilt on the
    next call rather than left to poison every request after the one that broke it.
    """
    pool = get_pool()
    future = pool.submit(fn, *args, **kwargs)
    try:
        return await asyncio.wrap_future(future)
    except BrokenProcessPool:
        _drop_pool(pool)
        raise


def _drop_pool(broken: ProcessPoolExecutor) -> None:
    global _pool
    with _pool_lock:
        if _pool is broken:
            _pool = None


def shutdown_pool() -> None:
    """Shut down the pool if one was ever built. Idempotent.

    Meant for a Starlette ``"shutdown"`` handler, alongside ``aclose_client``. Unlike that
    function, this must not build a pool just to close it: opening an ``httpx.AsyncClient``
    costs nothing before the first request, but spawning worker processes is real work.
    """
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.shutdown(wait=True, cancel_futures=True)
            _pool = None

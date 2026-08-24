"""A process-wide ``ProcessPoolExecutor`` for CPU-bound offload.

Unlike the resources in :mod:`ztf_viewer.loop_registry`, a ``ProcessPoolExecutor`` is not
loop-affine: it does not open anything against ``asyncio.get_running_loop()`` at construction
time, and wrapping ``.submit()``'s future with ``asyncio.wrap_future`` accepts an executor built
long before that loop existed. So the loop-registry pattern does not apply here, for the same
reason ``ztf_viewer/__main__.py``'s ``_thread_pool`` is one per process rather than one per loop:
keying it by loop would spawn a fresh set of child processes every time a new loop asked for one,
which is exactly what a per-request loop model would do on every single request. One pool for the
life of the process is what a process pool means.

The pool is built at import time, not lazily: constructing ``ProcessPoolExecutor`` does not
itself spawn workers (they start on first submit), so there is no import-time cost to defer.
"""

import asyncio
import threading
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool

from ztf_viewer.config import PROCESS_POOL_SIZE


class _ProcessPool:
    """Owns one ``ProcessPoolExecutor`` and rebuilds it if a child crash breaks it.

    A crash in the child (killed, segfaults, OOM-killed -- plausible for matplotlib/LaTeX
    rendering) raises ``BrokenProcessPool`` to the caller that hit it, and permanently poisons
    that executor: every future submitted to it afterwards fails the same way. Left alone, one
    crash would fail every later request that reaches this pool, so a break replaces the
    executor instead.
    """

    def __init__(self, max_workers: int) -> None:
        self._max_workers = max_workers
        self._executor = ProcessPoolExecutor(max_workers=max_workers)
        self._lock = threading.Lock()

    async def run[T](self, fn: Callable[..., T], *args, **kwargs) -> T:
        executor = self._executor
        future = executor.submit(fn, *args, **kwargs)
        try:
            return await asyncio.wrap_future(future)
        except BrokenProcessPool:
            self._replace(executor)
            raise

    def _replace(self, broken: ProcessPoolExecutor) -> None:
        """Dispose of `broken` and build its replacement, unless another caller already did."""
        with self._lock:
            if self._executor is not broken:
                return
            broken.shutdown(wait=True, cancel_futures=True)
            self._executor = ProcessPoolExecutor(max_workers=self._max_workers)

    def shutdown(self) -> None:
        """Idempotent: ``Executor.shutdown`` tolerates repeat calls on its own."""
        with self._lock:
            self._executor.shutdown(wait=True, cancel_futures=True)


_pool = _ProcessPool(PROCESS_POOL_SIZE)


async def run_in_process[T](fn: Callable[..., T], *args, **kwargs) -> T:
    """Await ``fn(*args, **kwargs)`` run in the process pool.

    ``fn`` must be a module-level function with no captured state: the spawn start method
    (macOS default; the container forks, but code must not rely on that) re-imports the
    target module in the child, so closures, lambdas and bound methods cannot cross the
    pickling boundary a process pool requires.
    """
    return await _pool.run(fn, *args, **kwargs)


def shutdown_pool() -> None:
    """Shut down the process pool. Idempotent.

    Meant for a Starlette ``"shutdown"`` handler, alongside ``aclose_client``.
    """
    _pool.shutdown()

"""A process-wide ``ProcessPoolExecutor`` for CPU-bound offload.

Unlike the resources in :mod:`ztf_viewer.loop_registry`, a ``ProcessPoolExecutor`` is not
loop-affine: it does not open anything against ``asyncio.get_running_loop()`` at construction
time, and wrapping ``.submit()``'s future with ``asyncio.wrap_future`` accepts an executor built
long before that loop existed. So the loop-registry pattern does not apply here, for the same
reason ``ztf_viewer/__main__.py``'s ``_thread_pool`` is one per process rather than one per loop:
keying it by loop would spawn a fresh set of child processes every time a new loop asked for one,
which is exactly what a per-request loop model would do on every single request. One pool for the
life of the process is what a process pool means.

The executor is built on first use, not at import. A pool worker re-imports the module holding
the function it was handed, and if that module reaches this one, an import-time executor would
have every child build its own.
"""

import asyncio
import threading
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool

from ztf_viewer.config import PROCESS_POOL_SIZE


class _ProcessPool:
    """Owns one ``ProcessPoolExecutor``, rebuilding it when a child crash breaks it.

    ``BrokenProcessPool`` poisons an executor permanently, so the break is raised to the caller
    that hit it and the executor is replaced rather than left to fail every later call.
    """

    def __init__(self, max_workers: int) -> None:
        self._max_workers = max_workers
        self._executor: ProcessPoolExecutor | None = None
        self._lock = threading.Lock()

    def _get(self) -> ProcessPoolExecutor:
        with self._lock:
            if self._executor is None:
                self._executor = ProcessPoolExecutor(max_workers=self._max_workers)
            return self._executor

    async def run[T](self, fn: Callable[..., T], *args, **kwargs) -> T:
        executor = self._get()
        future = executor.submit(fn, *args, **kwargs)
        try:
            return await asyncio.wrap_future(future)
        except BrokenProcessPool:
            self._discard(executor)
            raise

    def _discard(self, broken: ProcessPoolExecutor) -> None:
        """Shut `broken` down and clear it, unless another caller replaced it first."""
        with self._lock:
            if self._executor is not broken:
                return
            self._executor = None
        # Outside the lock: shutdown waits on the broken executor's threads, and callers
        # asking for the replacement should not queue behind that.
        broken.shutdown(wait=True, cancel_futures=True)

    def shutdown(self) -> None:
        """Idempotent, and a no-op if the pool was never used."""
        with self._lock:
            executor = self._executor
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)


_pool = _ProcessPool(PROCESS_POOL_SIZE)


async def run_in_process[T](fn: Callable[..., T], *args, **kwargs) -> T:
    """Await ``fn(*args, **kwargs)`` run in the process pool.

    ``fn`` must be picklable and importable by name in the child: a module-level function, not a
    closure, lambda or bound method.
    """
    return await _pool.run(fn, *args, **kwargs)


def shutdown_pool() -> None:
    """Shut down the process pool. Idempotent."""
    _pool.shutdown()

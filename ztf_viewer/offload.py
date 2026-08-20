"""Bounded thread offload for third-party clients that stay synchronous by design.

`astroquery` (Vizier, Simbad, MOCServer, Skybot, Gaia), `alerce.core.Alerce` and
`antares_client.search` are not being ported to async I/O. They still have to run off the event
loop, via `asyncio.to_thread`, but a bare `asyncio.to_thread` call shares one pool
(`config.THREAD_POOL_SIZE`) with every other offloaded call in the process. One slow or hanging
upstream could fill that whole pool and stall catalogs that have nothing to do with it. Each
upstream therefore gets its own semaphore, sized from `config.UPSTREAM_THREAD_LIMITS`, bounding
how many of the shared pool's slots it can hold at once.

The semaphore is `_ThreadSafeSemaphore` rather than `asyncio.Semaphore`, so the bound holds
whichever thread or loop reaches it, and holds for the whole process rather than per loop.
"""

import asyncio
import threading
from collections import deque
from typing import Callable, Optional, TypeVar

from ztf_viewer import config

_T = TypeVar("_T")


class _ThreadSafeSemaphore:
    """An async semaphore whose counter is guarded by a real lock.

    `asyncio.Semaphore` protects its counter with nothing but the single-threaded event loop:
    `release()` never checks which loop it is on, and `acquire()` only checks on the contended
    path, so touching one from another thread corrupts the count in silence -- the bound stops
    holding with nothing raised and nothing logged. A semaphore only ever acquired uncontended is
    not even bound to a loop yet, so the first thread to contend it binds it to its own.

    Here the counter lives under a `threading.Lock` and waiters are woken through
    `call_soon_threadsafe`, so acquiring and releasing are correct from any thread and from any
    loop -- and one semaphore bounds the whole process instead of one per loop.

    Waiting still happens on the loop rather than in a thread, so a task queued behind a busy
    upstream does not hold one of the pool's slots while it waits.
    """

    def __init__(self, value: int):
        if value < 1:
            raise ValueError("semaphore value must be >= 1")
        self._value = value
        self._lock = threading.Lock()
        self._waiters: deque = deque()

    def locked(self) -> bool:
        with self._lock:
            return self._value == 0

    async def acquire(self) -> None:
        loop = asyncio.get_running_loop()
        with self._lock:
            if self._value > 0:
                self._value -= 1
                return
            future = loop.create_future()
            self._waiters.append(future)
        try:
            await future
        except asyncio.CancelledError:
            self._abandon(future)
            raise

    def release(self) -> None:
        with self._lock:
            waiter = self._next_waiter()
            if waiter is None:
                self._value += 1
                return
        # Outside the lock: call_soon_threadsafe takes the loop's own, and the callback takes ours.
        self._grant(waiter)

    def _next_waiter(self):
        """Pop the first waiter still worth waking. Call with the lock held."""
        while self._waiters:
            future = self._waiters.popleft()
            if not future.done():
                return future
        return None

    def _grant(self, future) -> None:
        def grant():
            if future.done():  # cancelled between the hand-off and this callback
                self.release()
                return
            future.set_result(True)

        try:
            future.get_loop().call_soon_threadsafe(grant)
        except RuntimeError:
            self.release()  # its loop is gone; the permit belongs to somebody else

    def _abandon(self, future) -> None:
        """Cancelled while waiting: leave the queue, or hand back a permit already granted."""
        with self._lock:
            if future in self._waiters:
                self._waiters.remove(future)
                return
        if future.done() and not future.cancelled():
            self.release()

    async def __aenter__(self) -> None:
        await self.acquire()

    async def __aexit__(self, *exc_info) -> None:
        self.release()


_semaphores: dict[str, _ThreadSafeSemaphore] = {}
_semaphores_lock = threading.Lock()


def _semaphore(upstream: str) -> _ThreadSafeSemaphore:
    """One semaphore per upstream, for the life of the process."""
    with _semaphores_lock:
        semaphore = _semaphores.get(upstream)
        if semaphore is None:
            semaphore = _semaphores[upstream] = _ThreadSafeSemaphore(config.UPSTREAM_THREAD_LIMITS[upstream])
        return semaphore


async def to_thread(upstream: Optional[str], func: Callable[..., _T], *args, **kwargs) -> _T:
    """Run `func` in a thread, bounded by `upstream`'s semaphore.

    `upstream=None` falls back to a bare `asyncio.to_thread`: nothing in this app calls it that
    way today, but it keeps `_ensure_coroutine`'s old behaviour available for a call site that
    has not been sorted into an upstream bucket yet.
    """
    if upstream is None:
        return await asyncio.to_thread(func, *args, **kwargs)
    async with _semaphore(upstream):
        return await asyncio.to_thread(func, *args, **kwargs)

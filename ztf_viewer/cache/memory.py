"""The in-process cache backend: a ``cachetools.TTLCache`` behind a lock.

Used in development and in tests.  Like every backend here it stores *serialized* values, so
a cached value never aliases the one the caller holds and the two backends cannot disagree
about what a cache round-trip does to a value.
"""

import asyncio
import threading
import weakref

from cachetools import TTLCache

from ztf_viewer.cache.decorator import make_async_cache
from ztf_viewer.loop_registry import LoopRegistry

# Every live memory backend, so that `clear_memory_caches()` can reach the ones captured by
# functions that were decorated at import time.
_BACKENDS: weakref.WeakSet = weakref.WeakSet()


class MemoryBackend:
    """A process-local TTL store.  Locked because Dash serves callbacks from a thread pool."""

    def __init__(self, maxsize, ttl):
        self._cache = TTLCache(maxsize, ttl=ttl)
        self._lock = threading.Lock()
        _BACKENDS.add(self)

    def clear(self):
        with self._lock:
            self._cache.clear()

    def get(self, key):
        with self._lock:
            return self._cache.get(key)

    def set(self, key, blob):
        with self._lock:
            self._cache[key] = blob


class AsyncMemoryBackend:
    """An async view over a (possibly shared) :class:`MemoryBackend`.

    Wrapping rather than reimplementing the store is what makes ``cache()`` and ``async_cache()``
    key-compatible for the memory backend: pass both the same ``MemoryBackend`` and a value one
    writes is a hit for the other.

    The critical section has no ``await`` in it, so the lock buys no extra safety over
    ``MemoryBackend``'s own thread lock today; it exists because a future caller may await while
    holding it, and because a lock is the cheapest guard against ever assuming otherwise.  It is
    created lazily, per running loop, rather than once in ``__init__`` — an ``asyncio.Lock``
    binds to whichever loop first uses it, and this must keep working across successive
    ``asyncio.run()`` calls (Flask's per-request loop model) — via
    :class:`~ztf_viewer.loop_registry.LoopRegistry`.
    """

    def __init__(self, backend: MemoryBackend):
        self._backend = backend
        self._locks = LoopRegistry(asyncio.Lock)

    async def get(self, key):
        async with self._locks.get():
            return self._backend.get(key)

    async def set(self, key, blob):
        async with self._locks.get():
            self._backend.set(key, blob)


def create_memory_backend(maxsize, ttl) -> MemoryBackend:
    return MemoryBackend(maxsize, ttl=ttl)


def create_async_memory_cache(backend: MemoryBackend):
    """Build ``async_cache()`` over an existing :class:`MemoryBackend` — see ``AsyncMemoryBackend``."""
    return make_async_cache(AsyncMemoryBackend(backend))


def clear_memory_caches():
    """Empty every in-process memory cache.

    Rebinding ``ztf_viewer.cache.cache`` cannot un-cache anything: the 19 ``@cache()`` sites
    captured a backend when their module was imported.  Tests need the entries gone between
    tests, which is what this does.
    """
    for backend in list(_BACKENDS):
        backend.clear()

"""The in-process cache backend: a ``cachetools.TTLCache`` behind a lock.

Used in development and in tests.  Like every backend here it stores *serialized* values, so
a cached value never aliases the one the caller holds and the two backends cannot disagree
about what a cache round-trip does to a value.
"""

import threading
import weakref

from cachetools import TTLCache

from ztf_viewer.cache.decorator import make_cache

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


def create_memory_cache(maxsize, ttl):
    return make_cache(MemoryBackend(maxsize, ttl=ttl))


def clear_memory_caches():
    """Empty every in-process memory cache.

    Rebinding ``ztf_viewer.cache.cache`` cannot un-cache anything: the 19 ``@cache()`` sites
    captured a backend when their module was imported.  Tests need the entries gone between
    tests, which is what this does.
    """
    for backend in list(_BACKENDS):
        backend.clear()

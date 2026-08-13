"""The application cache: ``from ztf_viewer.cache import cache``, then ``@cache()``.

The pieces live next door — :mod:`~ztf_viewer.cache.core` (keys and value codec),
:mod:`~ztf_viewer.cache.decorator` (the decorators), :mod:`~ztf_viewer.cache.memory` and
:mod:`~ztf_viewer.cache.redis` (the two stores).  This module is only the configuration: which
backend, how big, how long, and the single ``cache`` every call site imports.

Two backends, chosen by ``CACHE_TYPE``:

* ``redis`` — a plain ``StrictRedis``/``redis.asyncio.Redis`` pair with a per-entry TTL (production).
* ``memory`` — a process-local ``cachetools.TTLCache`` (development and tests).

``CACHE_TYPE``, ``TTL`` and ``_get_cache()`` are the seam ``tests/conftest.py`` and the cache
contract tests build a cache with; they must stay here, at module level. Each call builds a
fresh store, which is what lets a test rebuild with a different TTL.

``cache()`` dispatches on ``inspect.iscoroutinefunction`` (``ztf_viewer.cache.decorator``), so a
sync and an async function decorated here still share one store and are key-compatible.
"""

from ztf_viewer import config
from ztf_viewer.cache.decorator import make_cache, make_dispatching_cache
from ztf_viewer.cache.memory import clear_memory_caches, create_async_memory_cache, create_memory_backend
from ztf_viewer.cache.redis import create_async_redis_cache, create_redis_cache
from ztf_viewer.config import CACHE_TYPE

__all__ = ["TTL", "cache", "clear_memory_caches"]

TTL = 7 * 86400
MAXSIZE = 1 << 16

# `CACHE_TYPE` above is bound at import, but `ztf_viewer.config.CACHE_TYPE` is assigned at
# runtime by tests/conftest.py, and the cache contract tests patch both.  Remembering the
# import-time value lets `_get_cache()` honour whichever of the two was changed.
_CACHE_TYPE_AT_IMPORT = CACHE_TYPE


def _memory_cache():
    # One store behind both the sync and the async path, so a value written through one is a
    # hit for the other.
    backend = create_memory_backend(MAXSIZE, ttl=TTL)
    return make_dispatching_cache(make_cache(backend), create_async_memory_cache(backend))


def _redis_cache():
    # Redis needs no shared object: both clients point at the same server and share the key
    # scheme, so the two factories below already agree on a store.
    return make_dispatching_cache(create_redis_cache(ttl=TTL), create_async_redis_cache(ttl=TTL))


CACHE_CREATORS = {
    "redis": _redis_cache,
    "memory": _memory_cache,
}


def _cache_type():
    if CACHE_TYPE != _CACHE_TYPE_AT_IMPORT:
        return CACHE_TYPE
    return config.CACHE_TYPE


def _get_cache():
    """A fresh dispatching ``cache()`` decorator, built from the current config."""
    try:
        return CACHE_CREATORS[_cache_type().lower().strip()]()
    except KeyError as e:
        raise ValueError(f'CACHE_TYPE must be one of: {", ".join(CACHE_CREATORS)}') from e


cache = _get_cache()

"""The application cache: ``from ztf_viewer.cache import cache``, then ``@cache()``.

The pieces live next door — :mod:`~ztf_viewer.cache.core` (keys and value codec),
:mod:`~ztf_viewer.cache.decorator` (the decorator), :mod:`~ztf_viewer.cache.memory` and
:mod:`~ztf_viewer.cache.redis` (the two stores).  This module is only the configuration: which
backend, how big, how long, and the ``cache`` every call site imports.

Two backends, chosen by ``CACHE_TYPE``:

* ``redis`` — a plain ``StrictRedis`` with a per-entry TTL (production).
* ``memory`` — a process-local ``cachetools.TTLCache`` (development and tests).

``CACHE_TYPE``, ``TTL`` and ``_get_cache()`` are the seam ``tests/conftest.py`` and
``tests/test_cache_contract.py`` build a cache with; they must stay here, at module level.
"""

from ztf_viewer import config
from ztf_viewer.cache.memory import clear_memory_caches, create_memory_cache
from ztf_viewer.cache.redis import create_redis_cache
from ztf_viewer.config import CACHE_TYPE

__all__ = ["TTL", "cache", "clear_memory_caches"]

TTL = 7 * 86400
MAXSIZE = 1 << 16

# `CACHE_TYPE` above is bound at import, but `ztf_viewer.config.CACHE_TYPE` is assigned at
# runtime by tests/conftest.py, and tests/test_cache_contract.py patches both.  Remembering the
# import-time value lets `_get_cache()` honour whichever of the two was actually changed.
_CACHE_TYPE_AT_IMPORT = CACHE_TYPE

CACHE_CREATORS = {
    "redis": lambda: create_redis_cache(ttl=TTL),
    "memory": lambda: create_memory_cache(MAXSIZE, ttl=TTL),
}


def _cache_type():
    if CACHE_TYPE != _CACHE_TYPE_AT_IMPORT:
        return CACHE_TYPE
    return config.CACHE_TYPE


def _get_cache():
    try:
        return CACHE_CREATORS[_cache_type().lower().strip()]()
    except KeyError as e:
        raise ValueError(f'CACHE_TYPE must be one of: {", ".join(CACHE_CREATORS)}') from e


cache = _get_cache()

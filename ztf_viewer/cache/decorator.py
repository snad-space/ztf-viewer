"""The ``@cache()`` decorator itself, over any backend.

Keying and serialization live in :mod:`ztf_viewer.cache.core`; the stores live in
:mod:`ztf_viewer.cache.memory` and :mod:`ztf_viewer.cache.redis`.  A backend is anything with
``get(key)`` and ``set(key, blob)`` over pickled bytes.

This replaces ``redis_lru``/``cachetools.cached``, whose behaviour differed between backends in
five ways; ``tests/test_cache_contract.py`` is the spec.
"""

import functools
import inspect
import logging

from ztf_viewer.cache.core import (
    UncacheableArgument,
    UncacheableValue,
    cache_key_for_call,
    decode_value,
    encode_value,
    function_id,
)


def make_cache(backend):
    """Build the ``cache`` decorator factory over a backend."""

    def cache():
        def decorator(func):
            # Fail at import time, not on first call.
            function_id(func)

            if inspect.iscoroutinefunction(func):
                raise TypeError(
                    f"cache() cannot wrap the coroutine function {func.__qualname__}: it would cache the "
                    "coroutine object, which is exhausted after the first await. Use acache() instead."
                )

            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                try:
                    key = cache_key_for_call(func, wrapper, args, kwargs)
                except UncacheableArgument as e:
                    # A cache must never turn a legal call into an error, so bypass it.
                    logging.debug(f"not caching {func.__qualname__}: {e}")
                    return func(*args, **kwargs)

                blob = backend.get(key)
                if blob is not None:
                    return decode_value(blob)

                value = func(*args, **kwargs)
                try:
                    encoded = encode_value(value)
                except UncacheableValue as e:
                    logging.warning(f"not caching the result of {func.__qualname__}: {e}")
                    return value
                backend.set(key, encoded)
                return value

            return wrapper

        return decorator

    return cache

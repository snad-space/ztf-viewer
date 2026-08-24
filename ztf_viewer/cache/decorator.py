"""The public ``cache()`` decorator, plus the internal sync/async factories it dispatches to.

Keying and serialization live in :mod:`ztf_viewer.cache.core`; the stores live in
:mod:`ztf_viewer.cache.memory` and :mod:`ztf_viewer.cache.redis`.  A sync backend is anything
with ``get(key)``/``set(key, blob)`` over pickled bytes; an async backend is the same with
awaitable ``get``/``set``.

This replaces ``redis_lru``/``cachetools.cached``, whose behaviour differed between backends in
five ways; ``tests/test_cache_contract.py`` is the spec.

``make_cache``/``make_async_cache`` are internal: they build a decorator that only accepts one kind of
function, and are meant to be composed by ``make_dispatching_cache`` rather than handed out on
their own — a call site never has to pick between them, and so cannot pick wrong.

Each internal factory owns one :class:`~ztf_viewer.cache.single_flight.SingleFlight`/``AsyncSingleFlight``,
so concurrent identical misses across every site built from it coalesce onto a single call — the
key already disambiguates functions and arguments, so one flight table per backend is enough,
and the dispatcher composes the two factories unchanged.
"""

import functools
import inspect
import logging

logger = logging.getLogger(__name__)
from ztf_viewer.cache.core import (
    UncacheableArgument,
    UncacheableValue,
    cache_key_for_call,
    decode_value,
    encode_value,
    function_id,
)
from ztf_viewer.cache.single_flight import AsyncSingleFlight, SingleFlight


def make_cache(backend):
    """Build the internal sync-only decorator factory over a backend."""

    single_flight = SingleFlight()

    def cache():
        def decorator(func):
            # Fail at import time, not on first call.
            function_id(func)

            if inspect.iscoroutinefunction(func):
                raise TypeError(
                    f"cache() cannot wrap the coroutine function {func.__qualname__}: it would cache the "
                    "coroutine object, which is exhausted after the first await."
                )

            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                try:
                    key = cache_key_for_call(func, wrapper, args, kwargs)
                except UncacheableArgument as e:
                    # A cache must never turn a legal call into an error, so bypass it.
                    logger.debug(f"not caching {func.__qualname__}: {e}")
                    return func(*args, **kwargs)

                blob = backend.get(key)
                if blob is not None:
                    return decode_value(blob)

                def compute():
                    value = func(*args, **kwargs)
                    try:
                        encoded = encode_value(value)
                    except UncacheableValue as e:
                        logger.warning(f"not caching the result of {func.__qualname__}: {e}")
                        return value
                    backend.set(key, encoded)
                    return value

                return single_flight.run(key, compute)

            return wrapper

        return decorator

    return cache


def make_async_cache(backend):
    """Build the internal async-only decorator factory over an async backend."""

    single_flight = AsyncSingleFlight()

    def async_cache():
        def decorator(func):
            # Fail at import time, not on first call.
            function_id(func)

            if not inspect.iscoroutinefunction(func):
                raise TypeError(f"the async cache can only wrap a coroutine function, not {func!r}.")

            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                try:
                    key = cache_key_for_call(func, wrapper, args, kwargs)
                except UncacheableArgument as e:
                    logger.debug(f"not caching {func.__qualname__}: {e}")
                    return await func(*args, **kwargs)

                blob = await backend.get(key)
                if blob is not None:
                    return decode_value(blob)

                async def compute():
                    value = await func(*args, **kwargs)
                    try:
                        encoded = encode_value(value)
                    except UncacheableValue as e:
                        logger.warning(f"not caching the result of {func.__qualname__}: {e}")
                        return value
                    await backend.set(key, encoded)
                    return value

                return await single_flight.run(key, compute)

            return wrapper

        return decorator

    return async_cache


def make_dispatching_cache(sync_cache, async_cache):
    """Compose a sync and an async decorator factory into the one public ``cache()``.

    Routes by ``inspect.iscoroutinefunction(func)`` at decoration time, which sees through
    ``functools.partial``. This is what makes converting a cached function to ``async def``
    need no change to its ``@cache()`` line.
    """

    def cache():
        def decorator(func):
            if inspect.iscoroutinefunction(func):
                return async_cache()(func)
            return sync_cache()(func)

        return decorator

    return cache

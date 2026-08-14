"""Contract tests for the async path of ``ztf_viewer.cache.cache()``.

There is one public decorator now: ``cache()`` dispatches on ``inspect.iscoroutinefunction`` to an
internal sync or async factory (``ztf_viewer.cache.decorator.make_dispatching_cache``). This file
covers what is specific to the async side and to the dispatch itself, reusing
``ztf_viewer.cache.core`` unchanged (the same key derivation and value codec as the sync path,
already covered in full by ``tests/test_cache_contract.py``). What is specific here:

* the dispatch itself: ``cache()`` on an ``async def`` yields a coroutine function and caches the
  awaited value, never the coroutine object; ``cache()`` on a plain ``def`` still yields a plain
  function; a ``functools.partial`` of a coroutine function routes to the async path;
* cross-decorator key compatibility: a value written through a sync-wrapped site is a hit for an
  async-wrapped site on the same function/arguments, and vice versa. Observing this needs both
  wrapped from one ``cache()``, over one store, which is what ``ztf_viewer.cache._get_cache()``
  returns;
* that no loop-affine resource is created before a loop is running, so two successive
  ``asyncio.run()`` calls (simulating Flask's per-request loop) both work.

Parametrized over ``CACHE_TYPE`` in ``{memory, redis}`` the same way as
``tests/test_cache_contract.py``; see that file's module docstring for the ``pytest-redis``
setup notes.
"""

import asyncio
import threading

import pytest
import redis
import redis.asyncio

LONG_TTL = 3600
SHORT_TTL = 1


def _async_redis_client_factory(sync_client):
    """A zero-arg factory building an async client pointed at the same test server."""
    kwargs = sync_client.connection_pool.connection_kwargs
    # The real class, not the (possibly monkeypatched) module attribute — a factory built from
    # this must not recurse into its own monkeypatch of `redis.asyncio.Redis`.
    real_redis_cls = redis.asyncio.Redis

    def factory():
        return real_redis_cls(unix_socket_path=kwargs.get("path"), db=kwargs.get("db", 0))

    return factory


def _build_cache(request, monkeypatch, cache_type, ttl):
    """The shipped ``cache()`` decorator on the given backend/TTL.

    Goes through ``_get_cache()`` rather than assembling backends by hand, so the
    cross-decorator tests below check the wiring we actually ship.
    """
    from ztf_viewer import cache as cache_module
    from ztf_viewer import config

    monkeypatch.setattr(config, "CACHE_TYPE", cache_type, raising=False)
    monkeypatch.setattr(cache_module, "CACHE_TYPE", cache_type, raising=False)
    monkeypatch.setattr(cache_module, "TTL", ttl, raising=False)

    if cache_type == "redis":
        client = request.getfixturevalue("redisdb")
        # Captures the real class before the patch below, so the factory cannot recurse into it.
        async_factory = _async_redis_client_factory(client)
        monkeypatch.setattr(config, "REDIS_HOSTNAME", "localhost", raising=False)
        monkeypatch.setattr(cache_module, "REDIS_HOSTNAME", "localhost", raising=False)
        monkeypatch.setattr(redis, "StrictRedis", lambda *a, **kw: client)
        monkeypatch.setattr(redis.asyncio, "Redis", lambda *a, **kw: async_factory())

    return cache_module._get_cache()


@pytest.fixture(params=["memory", "redis"])
def cache_type(request):
    return request.param


@pytest.fixture
def cache(request, monkeypatch, cache_type):
    """A ``cache()`` decorator with a TTL long enough to be irrelevant."""
    return _build_cache(request, monkeypatch, cache_type, LONG_TTL)


@pytest.fixture
def short_ttl_cache(request, monkeypatch, cache_type):
    return _build_cache(request, monkeypatch, cache_type, SHORT_TTL)


class AsyncCounter:
    """A ``cache()``-wrapped coroutine that records how many times its body actually ran."""

    _NO_RESULT = object()

    def __init__(self, cache, result=_NO_RESULT, name="acounted"):
        self.calls = 0
        self._result = result

        async def counted(*args, **kwargs):
            self.calls += 1
            if self._result is self._NO_RESULT:
                return f"result-{self.calls}"
            return self._result

        counted.__name__ = name
        counted.__qualname__ = name
        self.func = cache()(counted)

    async def __call__(self, *args, **kwargs):
        return await self.func(*args, **kwargs)


async def assert_hit(counter, *args, **kwargs):
    before = counter.calls
    first = await counter(*args, **kwargs)
    assert counter.calls == before + 1, "first call should be a miss"
    second = await counter(*args, **kwargs)
    assert counter.calls == before + 1, "second call with equal arguments should be a hit"
    return first, second


# --------------------------------------------------------------------------------------------
# Hit / miss
# --------------------------------------------------------------------------------------------


async def test_hit_on_plain_arguments(cache):
    counter = AsyncCounter(cache)
    await assert_hit(counter, 633207400004353, "dr23")


async def test_different_args_do_not_hit(cache):
    counter = AsyncCounter(cache)
    await counter(1)
    await counter(2)
    assert counter.calls == 2


async def test_distinct_functions_do_not_collide(cache):
    """Same argument, two distinct @cache() sites must not collide just because the caller
    is now a coroutine."""
    a = AsyncCounter(cache, result="from-a", name="fn_a")
    b = AsyncCounter(cache, result="from-b", name="fn_b")
    assert await a(1) == "from-a"
    assert await b(1) == "from-b"


# --------------------------------------------------------------------------------------------
# TTL
# --------------------------------------------------------------------------------------------


async def test_entry_survives_until_ttl(short_ttl_cache):
    counter = AsyncCounter(short_ttl_cache)
    await counter(1)
    await counter(1)
    assert counter.calls == 1


async def test_entry_expires_after_ttl(short_ttl_cache):
    counter = AsyncCounter(short_ttl_cache)
    await counter(1)
    assert counter.calls == 1
    await asyncio.sleep(SHORT_TTL + 1.0)
    await counter(1)
    assert counter.calls == 2, "entry must be recomputed once the TTL has passed"


# --------------------------------------------------------------------------------------------
# Dispatch: cache() picks the wrapper kind by inspect.iscoroutinefunction
# --------------------------------------------------------------------------------------------


def test_cache_on_a_coroutine_function_yields_a_coroutine_function(cache):
    import inspect

    async def coro(x):
        return x

    wrapped = cache()(coro)
    assert inspect.iscoroutinefunction(wrapped)


def test_cache_on_a_plain_function_yields_a_plain_function(cache):
    import inspect

    def plain(x):
        return x

    wrapped = cache()(plain)
    assert not inspect.iscoroutinefunction(wrapped)
    assert wrapped(1) == 1


async def test_cache_on_a_coroutine_function_caches_the_awaited_value(cache):
    """A second hit must return the value, not an already-exhausted coroutine object."""
    counter = AsyncCounter(cache)
    first = await counter(1)
    second = await counter(1)
    assert first == second == "result-1"
    assert counter.calls == 1


def test_iscoroutinefunction_sees_through_partial():
    """The dispatcher's premise: a partial of a coroutine function still reads as one."""
    import functools
    import inspect

    async def coro(a, b):
        return a + b

    partial_coro = functools.partial(coro, 1)
    assert inspect.iscoroutinefunction(partial_coro)


def test_partial_of_a_coroutine_function_is_refused(cache):
    """A partial's bound arguments never reach the key, so it is refused before dispatch."""
    import functools

    async def coro(a, b):
        return a + b

    partial_coro = functools.partial(coro, 1)
    partial_coro.__name__ = partial_coro.__qualname__ = "partial_coro"

    with pytest.raises(TypeError, match="partial"):
        cache()(partial_coro)


# --------------------------------------------------------------------------------------------
# Uncacheable arguments bypass the cache, like the sync decorator
# --------------------------------------------------------------------------------------------


async def test_uncacheable_argument_bypasses_the_cache(cache):
    """A cache is transparent: a legal call must not become an error, nor a false hit."""
    counter = AsyncCounter(cache)
    unpicklable = lambda: None  # noqa: E731 - deliberately unpicklable
    assert await counter(unpicklable) == "result-1"
    assert await counter(unpicklable) == "result-2", "an uncacheable argument must never be cached as a hit"
    assert counter.calls == 2


# --------------------------------------------------------------------------------------------
# Cross-decorator key compatibility
# --------------------------------------------------------------------------------------------


def _make_matching_pair(qualname):
    """A sync and an async body with the same identity, so they key identically."""
    calls = {"sync": 0, "async": 0}

    def sync_body(x):
        calls["sync"] += 1
        return x * 2

    async def async_body(x):
        calls["async"] += 1
        return x * 2

    for f in (sync_body, async_body):
        f.__name__ = qualname
        f.__qualname__ = qualname

    return sync_body, async_body, calls


def test_sync_write_is_hit_for_async_read(request, monkeypatch, cache_type):
    cache_dec = _build_cache(request, monkeypatch, cache_type, LONG_TTL)
    sync_body, async_body, calls = _make_matching_pair("shared_site_a")

    wrapped_sync = cache_dec()(sync_body)
    wrapped_async = cache_dec()(async_body)

    assert wrapped_sync(21) == 42
    assert asyncio.run(wrapped_async(21)) == 42
    assert calls == {"sync": 1, "async": 0}, "the async caller must hit the sync-written entry"


def test_async_write_is_hit_for_sync_read(request, monkeypatch, cache_type):
    cache_dec = _build_cache(request, monkeypatch, cache_type, LONG_TTL)
    sync_body, async_body, calls = _make_matching_pair("shared_site_b")

    wrapped_sync = cache_dec()(sync_body)
    wrapped_async = cache_dec()(async_body)

    assert asyncio.run(wrapped_async(21)) == 42
    assert wrapped_sync(21) == 42
    assert calls == {"sync": 0, "async": 1}, "the sync caller must hit the async-written entry"


# --------------------------------------------------------------------------------------------
# Loop-affine resource discipline: two successive asyncio.run() calls both work
# --------------------------------------------------------------------------------------------


def test_two_successive_asyncio_run_calls_both_work(request, monkeypatch, cache_type):
    """Simulates Flask's per-request event loop. No client/pool/lock may be created before a
    loop is running, or bound past the loop that created it — a later change retrofits a real
    per-loop registry onto the per-loop dicts used here."""
    cache_dec = _build_cache(request, monkeypatch, cache_type, LONG_TTL)
    calls = []

    async def body(x):
        calls.append(x)
        return x * 2

    body.__name__ = body.__qualname__ = "loop_body"
    wrapped = cache_dec()(body)

    assert asyncio.run(wrapped(21)) == 42
    assert asyncio.run(wrapped(21)) == 42
    assert calls == [21], "the second asyncio.run() must reuse the cached value, not re-run the body"


# --------------------------------------------------------------------------------------------
# Cross-thread registry safety: many threads, each its own loop, populate the same
# LoopRegistry concurrently (a threading.Lock guards the get-and-create, not an asyncio one)
# --------------------------------------------------------------------------------------------

N_THREADS = 8


def _run_from_n_threads(touch):
    """Run ``touch()`` (a zero-arg coroutine function) via ``asyncio.run()`` on ``N_THREADS``
    threads that all reach the get-and-create at the same instant, via a barrier. Returns the
    per-thread (loop, result) pairs — the loops are kept alive so the WeakKeyDictionary entries
    they registered cannot be GC'd out before the caller inspects the registry."""
    barrier = threading.Barrier(N_THREADS)
    errors = []
    loops = [None] * N_THREADS
    outcomes = [None] * N_THREADS

    async def body():
        barrier.wait(timeout=5)
        return asyncio.get_running_loop(), await touch()

    def worker(i):
        try:
            loops[i], outcomes[i] = asyncio.run(body())
        except BaseException as e:  # noqa: BLE001 - collected, not swallowed
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert not errors, errors
    assert len(set(id(loop) for loop in loops)) == N_THREADS, "each thread must run its own loop"
    return loops, outcomes


def test_async_memory_backend_lock_registry_survives_concurrent_threads():
    """threading.Lock, not asyncio: the LoopRegistry is shared across threads, one loop each."""
    from ztf_viewer.cache.memory import AsyncMemoryBackend, create_memory_backend

    backend = AsyncMemoryBackend(create_memory_backend(1 << 16, ttl=3600))

    async def touch():
        return backend._locks.get()

    loops, locks = _run_from_n_threads(touch)

    assert len(backend._locks) == N_THREADS, "one registry entry per still-live loop"
    assert all(isinstance(lock, asyncio.Lock) for lock in locks)


def test_async_redis_backend_client_registry_survives_concurrent_threads():
    """threading.Lock, not asyncio: the LoopRegistry is shared across threads, one loop each."""
    from ztf_viewer.cache.redis import AsyncRedisBackend

    backend = AsyncRedisBackend(lambda: redis.asyncio.Redis(host="localhost"), ttl=3600)

    async def touch():
        return backend._clients.get()

    loops, clients = _run_from_n_threads(touch)

    assert len(backend._clients) == N_THREADS, "one registry entry per still-live loop"
    assert all(isinstance(client, redis.asyncio.Redis) for client in clients)

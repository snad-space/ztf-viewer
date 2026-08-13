import asyncio

import pytest
import redis.asyncio

from ztf_viewer.ttl_set import AsyncRedisTTLSet


def _async_client_factory(redisdb):
    """A zero-arg factory building an async client pointed at the same `pytest-redis` server."""
    kwargs = redisdb.connection_pool.connection_kwargs

    def factory():
        return redis.asyncio.Redis(unix_socket_path=kwargs.get("path"), db=kwargs.get("db", 0))

    return factory


@pytest.fixture
def ttl_set_factory(redisdb):
    def make(ttl):
        return AsyncRedisTTLSet(ttl=ttl, client_factory=_async_client_factory(redisdb))

    return make


async def test_clear(ttl_set_factory) -> None:
    ttl_set = ttl_set_factory(86400)
    await ttl_set.add(1)
    await ttl_set.add(2)
    await ttl_set.clear()
    assert await ttl_set.size() == 0


async def test_add(ttl_set_factory) -> None:
    ttl_set = ttl_set_factory(86400)
    await ttl_set.add(1)
    assert await ttl_set.size() == 1


async def test_remove(ttl_set_factory) -> None:
    ttl_set = ttl_set_factory(86400)
    await ttl_set.add(1)
    await ttl_set.remove(1)
    assert await ttl_set.size() == 0


async def test_contains(ttl_set_factory) -> None:
    ttl_set = ttl_set_factory(86400)
    await ttl_set.add(1)
    assert await ttl_set.contains(1)


async def test_values(ttl_set_factory) -> None:
    ttl_set = ttl_set_factory(86400)
    await ttl_set.add(1)
    assert set(await ttl_set.values()) == {1}


async def test_size(ttl_set_factory) -> None:
    ttl_set = ttl_set_factory(86400)
    await ttl_set.add(1)
    assert await ttl_set.size() == 1


async def test_size_0(ttl_set_factory) -> None:
    ttl_set = ttl_set_factory(86400)
    assert await ttl_set.size() == 0


async def test_multiple_add(ttl_set_factory) -> None:
    ttl_set = ttl_set_factory(86400)
    await ttl_set.add(1)
    await ttl_set.add(1)
    assert await ttl_set.size() == 1


async def test_multiple_remove(ttl_set_factory) -> None:
    ttl_set = ttl_set_factory(86400)
    await ttl_set.add(1)
    await ttl_set.remove(1)
    with pytest.raises(KeyError):
        await ttl_set.remove(1)
    assert await ttl_set.size() == 0


async def test_multiple_values(ttl_set_factory) -> None:
    ttl_set = ttl_set_factory(86400)
    await ttl_set.add(1)
    await ttl_set.add(2)
    assert set(await ttl_set.values()) == {1, 2}


async def test_ttl(ttl_set_factory) -> None:
    ttl_set = ttl_set_factory(1)
    await ttl_set.add(1)
    assert await ttl_set.size() == 1
    await asyncio.sleep(2)
    assert await ttl_set.size() == 0


async def test_ttl_prolongation(ttl_set_factory, redisdb) -> None:
    ttl = 10
    ttl_set = ttl_set_factory(ttl)
    key = ttl_set._encode(1)

    await ttl_set.add(1)
    pttl_before = redisdb.pttl(key)

    await asyncio.sleep(0.3)
    pttl_after_wait = redisdb.pttl(key)
    assert pttl_after_wait < pttl_before

    await ttl_set.add(1)
    pttl_after_readd = redisdb.pttl(key)
    # Re-adding resets the TTL back up close to the full value.
    assert pttl_after_readd > pttl_after_wait
    assert (ttl * 1000 - 2000) < pttl_after_readd <= ttl * 1000


async def test_no_io_at_construction(redisdb) -> None:
    """Construction must not touch the network — building `client_factory` itself proves it was
    never called."""
    calls = []

    def factory():
        calls.append(1)
        return redis.asyncio.Redis(unix_socket_path=redisdb.connection_pool.connection_kwargs.get("path"))

    AsyncRedisTTLSet(ttl=1, client_factory=factory)
    assert calls == []


def test_two_successive_asyncio_run_calls_both_work(redisdb) -> None:
    """Simulates Flask's per-request event loop: the client must be rebuilt for the second
    loop rather than reused from the first, which would raise on a closed loop."""
    ttl_set = AsyncRedisTTLSet(ttl=86400, client_factory=_async_client_factory(redisdb))

    async def body():
        await ttl_set.add(1)
        return await ttl_set.contains(1)

    assert asyncio.run(body()) is True
    assert asyncio.run(body()) is True

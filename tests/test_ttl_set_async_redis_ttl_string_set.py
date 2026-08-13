import asyncio

import pytest
import redis.asyncio

from ztf_viewer.ttl_set import AsyncRedisTTLStringSet


def _async_client_factory(redisdb):
    """A zero-arg factory building an async client pointed at the same `pytest-redis` server."""
    kwargs = redisdb.connection_pool.connection_kwargs

    def factory():
        return redis.asyncio.Redis(unix_socket_path=kwargs.get("path"), db=kwargs.get("db", 0))

    return factory


@pytest.fixture
def ttl_set_factory(redisdb):
    def make(ttl):
        return AsyncRedisTTLStringSet(ttl=ttl, client_factory=_async_client_factory(redisdb))

    return make


async def test_clear(ttl_set_factory) -> None:
    ttl_set = ttl_set_factory(86400)
    await ttl_set.add("a")
    await ttl_set.add("b")
    await ttl_set.clear()
    assert await ttl_set.size() == 0


async def test_add(ttl_set_factory) -> None:
    ttl_set = ttl_set_factory(86400)
    await ttl_set.add("")
    assert await ttl_set.size() == 1


async def test_remove(ttl_set_factory) -> None:
    ttl_set = ttl_set_factory(86400)
    await ttl_set.add("a")
    await ttl_set.remove("a")
    assert await ttl_set.size() == 0


async def test_contains(ttl_set_factory) -> None:
    ttl_set = ttl_set_factory(86400)
    await ttl_set.add("")
    assert await ttl_set.contains("")


async def test_values(ttl_set_factory) -> None:
    ttl_set = ttl_set_factory(86400)
    await ttl_set.add("abc")
    assert set(await ttl_set.values()) == {"abc"}


async def test_size(ttl_set_factory) -> None:
    ttl_set = ttl_set_factory(86400)
    await ttl_set.add("X")
    assert await ttl_set.size() == 1


async def test_size_0(ttl_set_factory) -> None:
    ttl_set = ttl_set_factory(86400)
    assert await ttl_set.size() == 0


async def test_multiple_add(ttl_set_factory) -> None:
    ttl_set = ttl_set_factory(86400)
    await ttl_set.add("α")
    await ttl_set.add("α")
    assert await ttl_set.size() == 1


async def test_multiple_remove(ttl_set_factory) -> None:
    ttl_set = ttl_set_factory(86400)
    await ttl_set.add("Цирк")
    await ttl_set.remove("Цирк")
    with pytest.raises(KeyError):
        await ttl_set.remove("Цирк")
    assert await ttl_set.size() == 0


async def test_multiple_values(ttl_set_factory) -> None:
    ttl_set = ttl_set_factory(86400)
    await ttl_set.add("abc")
    await ttl_set.add("def")
    assert set(await ttl_set.values()) == {"abc", "def"}


async def test_ttl(ttl_set_factory) -> None:
    ttl_set = ttl_set_factory(1)
    await ttl_set.add("a")
    assert await ttl_set.size() == 1
    await asyncio.sleep(2)
    assert await ttl_set.size() == 0


async def test_ttl_prolongation(ttl_set_factory, redisdb) -> None:
    ttl = 10
    ttl_set = ttl_set_factory(ttl)
    key = ttl_set._encode("a")

    await ttl_set.add("a")
    pttl_before = redisdb.pttl(key)

    await asyncio.sleep(0.3)
    pttl_after_wait = redisdb.pttl(key)
    assert pttl_after_wait < pttl_before

    await ttl_set.add("a")
    pttl_after_readd = redisdb.pttl(key)
    # Re-adding resets the TTL back up close to the full value.
    assert pttl_after_readd > pttl_after_wait
    assert (ttl * 1000 - 2000) < pttl_after_readd <= ttl * 1000

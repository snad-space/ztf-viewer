import asyncio

import pytest
from cachetools import TTLCache

from ztf_viewer.ttl_set import AsyncLocalTTLSet


async def test_clear() -> None:
    ttl_set = AsyncLocalTTLSet(maxsize=2, ttl=86400)
    await ttl_set.add(1)
    await ttl_set.add(2)
    await ttl_set.clear()
    assert await ttl_set.size() == 0


async def test_add() -> None:
    ttl_set = AsyncLocalTTLSet(maxsize=1, ttl=86400)
    await ttl_set.add(1)
    assert await ttl_set.size() == 1


async def test_remove() -> None:
    ttl_set = AsyncLocalTTLSet(maxsize=1, ttl=86400)
    await ttl_set.add(1)
    await ttl_set.remove(1)
    assert await ttl_set.size() == 0


async def test_contains() -> None:
    ttl_set = AsyncLocalTTLSet(maxsize=1, ttl=86400)
    await ttl_set.add(1)
    assert await ttl_set.contains(1)


async def test_values() -> None:
    ttl_set = AsyncLocalTTLSet(maxsize=1, ttl=86400)
    await ttl_set.add(1)
    assert set(await ttl_set.values()) == {1}


async def test_size() -> None:
    ttl_set = AsyncLocalTTLSet(maxsize=1, ttl=86400)
    await ttl_set.add(1)
    assert await ttl_set.size() == 1


async def test_size_0() -> None:
    ttl_set = AsyncLocalTTLSet(maxsize=1, ttl=86400)
    assert await ttl_set.size() == 0


async def test_multiple_add() -> None:
    ttl_set = AsyncLocalTTLSet(maxsize=2, ttl=86400)
    await ttl_set.add(1)
    await ttl_set.add(1)
    assert await ttl_set.size() == 1


async def test_multiple_remove() -> None:
    ttl_set = AsyncLocalTTLSet(maxsize=2, ttl=86400)
    await ttl_set.add(1)
    await ttl_set.remove(1)
    with pytest.raises(KeyError):
        await ttl_set.remove(1)
    assert await ttl_set.size() == 0


async def test_multiple_values() -> None:
    ttl_set = AsyncLocalTTLSet(maxsize=2, ttl=86400)
    await ttl_set.add(1)
    await ttl_set.add(2)
    assert set(await ttl_set.values()) == {1, 2}


async def test_ttl() -> None:
    ttl_set = AsyncLocalTTLSet(maxsize=2, ttl=1)
    await ttl_set.add(1)
    assert await ttl_set.size() == 1
    await asyncio.sleep(2)
    assert await ttl_set.size() == 0


async def test_ttl_prolongation() -> None:
    clock = 0.0

    def fake_timer() -> float:
        return clock

    ttl = 2
    ttl_set = AsyncLocalTTLSet(maxsize=2, ttl=ttl)
    ttl_set._local.ttl_cache = TTLCache(maxsize=2, ttl=ttl, timer=fake_timer)

    await ttl_set.add(1)
    assert await ttl_set.size() == 1

    clock += 1.5  # most of the way to the original expiry
    await ttl_set.add(1)  # re-add resets the TTL

    clock += 1  # past the original expiry, before the new one
    assert await ttl_set.size() == 1

    clock += 1  # past the new expiry
    assert await ttl_set.size() == 0


async def test_wraps_an_existing_local_ttl_set() -> None:
    """The memory backend of `unavailable_catalogs` shares one `LocalTTLSet` between the sync
    and async accessors, so an entry either adds is visible to both."""
    from ztf_viewer.ttl_set import LocalTTLSet

    local = LocalTTLSet(maxsize=2, ttl=86400)
    ttl_set = AsyncLocalTTLSet(local=local)

    await ttl_set.add(1)
    assert 1 in local

    local.add(2)
    assert await ttl_set.contains(2)

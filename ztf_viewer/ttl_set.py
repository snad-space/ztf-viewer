"""TTL-bounded sets: a local in-memory backend and a Redis-backed one, each with an async variant.

The sync classes (`LocalTTLSet`, `RedisTTLSet`, `RedisTTLStringSet`) implement
`collections.abc.MutableSet`. The async ones (`AsyncLocalTTLSet`, `AsyncRedisTTLSet`,
`AsyncRedisTTLStringSet`) are deliberately not `MutableSet`s: `__contains__`, `__len__` and
`__iter__` cannot be made awaitable, so there is no async counterpart to that interface. Instead
they expose plain async methods with names chosen to read naturally with `await`: `add`,
`discard`, `remove`, `clear`, `contains`, `size`, `values`.
"""

import pickle
from abc import ABC, abstractmethod
from collections.abc import Callable, Hashable, Iterator, MutableSet
from typing import TypeVar

import redis.asyncio
from cachetools import TTLCache
from redis import StrictRedis

from ztf_viewer.loop_registry import LoopRegistry

_T_Base = TypeVar("_T_Base")


class _BaseTTLSet[T_Base](ABC, MutableSet[T_Base]):
    def __init__(self, ttl: int):
        super().__init__()
        self.ttl = ttl

    def discard(self, value: _T_Base) -> None:
        try:
            self.remove(value)
        except KeyError:
            pass

    @abstractmethod
    def remove(self, value: _T_Base) -> None:
        """Must raise valueError if no value is not found"""
        raise NotImplementedError

    @abstractmethod
    def clear(self) -> None:
        raise NotImplementedError


_T_Local = TypeVar("_T_Local", bound=Hashable)


class LocalTTLSet[T_Local: Hashable](_BaseTTLSet[T_Local]):
    def __init__(self, maxsize: int, ttl: int):
        super().__init__(ttl)
        self.ttl_cache = TTLCache(maxsize=maxsize, ttl=ttl)

    def add(self, value: _T_Local) -> None:
        self.ttl_cache[value] = None

    def remove(self, value: _T_Local) -> None:
        del self.ttl_cache[value]

    def clear(self) -> None:
        self.ttl_cache.clear()

    def __contains__(self, value: _T_Local) -> bool:
        return value in self.ttl_cache

    def __len__(self) -> int:
        return len(self.ttl_cache)

    def __iter__(self) -> Iterator[_T_Local]:
        return iter(self.ttl_cache)


# We don't need it to be hashable, we need it to be serializable only
_T_Redis = TypeVar("_T_Redis")


class RedisTTLSet[T_Redis](_BaseTTLSet[T_Redis]):
    def __init__(self, ttl: int, client: StrictRedis, prefix: str = "RedisTTLSet"):
        super().__init__(ttl)

        self.client = client

        self.prefix = prefix.encode()
        if b"*" in self.prefix:
            raise ValueError('prefix must not contain "*"')

    def _encode(self, value: _T_Redis) -> bytes:
        serialized = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        return self.prefix + serialized

    def _decode(self, key: bytes) -> _T_Redis:
        return pickle.loads(key.removeprefix(self.prefix))

    def discard(self, value: _T_Redis) -> None:
        key = self._encode(value)
        self.client.delete(key)

    def remove(self, value: _T_Redis) -> None:
        key = self._encode(value)
        if self.client.getdel(key) is None:
            raise KeyError(f"{value} not found")

    def clear(self) -> None:
        for key in self.client.keys(self.prefix + b"*"):
            self.client.delete(key)

    def add(self, value: _T_Redis) -> None:
        key = self._encode(value)
        self.client.setex(key, self.ttl, 0)

    def __contains__(self, value: _T_Redis) -> bool:
        key = self._encode(value)
        return self.client.exists(key) > 0

    def __len__(self) -> int:
        return len(self.client.keys(self.prefix + b"*"))

    def __iter__(self) -> Iterator[_T_Redis]:
        for key in self.client.keys(self.prefix + b"*"):
            yield self._decode(key)


class RedisTTLStringSet(RedisTTLSet[str]):
    def _encode(self, value: str) -> bytes:
        return self.prefix + value.encode()

    def _decode(self, key: bytes) -> str:
        return key.removeprefix(self.prefix).decode()


_T_AsyncLocal = TypeVar("_T_AsyncLocal", bound=Hashable)


class AsyncLocalTTLSet[T_AsyncLocal: Hashable]:
    """Async facade over :class:`LocalTTLSet`.

    `LocalTTLSet` is pure in-memory and never blocks, so there is nothing here to actually await
    — this exists only so a caller can use the same awaitable method names regardless of which
    backend `unavailable_catalogs` was configured with.
    """

    def __init__(self, local: LocalTTLSet[_T_AsyncLocal] | None = None, *, maxsize: int = 0, ttl: int = 0):
        self._local = local if local is not None else LocalTTLSet(maxsize=maxsize, ttl=ttl)

    async def add(self, value: _T_AsyncLocal) -> None:
        self._local.add(value)

    async def discard(self, value: _T_AsyncLocal) -> None:
        self._local.discard(value)

    async def remove(self, value: _T_AsyncLocal) -> None:
        self._local.remove(value)

    async def clear(self) -> None:
        self._local.clear()

    async def contains(self, value: _T_AsyncLocal) -> bool:
        return value in self._local

    async def size(self) -> int:
        return len(self._local)

    async def values(self) -> list[_T_AsyncLocal]:
        return list(self._local)


_T_AsyncRedis = TypeVar("_T_AsyncRedis")


class AsyncRedisTTLSet[T_AsyncRedis]:
    """Async counterpart to :class:`RedisTTLSet`, on ``redis.asyncio``.

    A connection pool is bound to the loop that created it, so the client is built lazily per
    running loop rather than once in ``__init__``, through
    :class:`~ztf_viewer.loop_registry.LoopRegistry`.

    Nothing here does I/O in ``__init__``.
    """

    def __init__(
        self,
        ttl: int,
        client_factory: Callable[[], redis.asyncio.Redis],
        prefix: str = "RedisTTLSet",
    ):
        self.ttl = ttl

        self.prefix = prefix.encode()
        if b"*" in self.prefix:
            raise ValueError('prefix must not contain "*"')

        self._clients = LoopRegistry(client_factory)

    def _client(self) -> redis.asyncio.Redis:
        return self._clients.get()

    def _encode(self, value: _T_AsyncRedis) -> bytes:
        serialized = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        return self.prefix + serialized

    def _decode(self, key: bytes) -> _T_AsyncRedis:
        return pickle.loads(key.removeprefix(self.prefix))

    async def add(self, value: _T_AsyncRedis) -> None:
        key = self._encode(value)
        # `set(..., ex=)` rather than the deprecated `setex`, matching the cache's Redis backend.
        await self._client().set(key, 0, ex=self.ttl)

    async def discard(self, value: _T_AsyncRedis) -> None:
        key = self._encode(value)
        await self._client().delete(key)

    async def remove(self, value: _T_AsyncRedis) -> None:
        key = self._encode(value)
        if await self._client().getdel(key) is None:
            raise KeyError(f"{value} not found")

    async def clear(self) -> None:
        client = self._client()
        for key in await client.keys(self.prefix + b"*"):
            await client.delete(key)

    async def contains(self, value: _T_AsyncRedis) -> bool:
        key = self._encode(value)
        return await self._client().exists(key) > 0

    async def size(self) -> int:
        client = self._client()
        return len(await client.keys(self.prefix + b"*"))

    async def values(self) -> list[_T_AsyncRedis]:
        client = self._client()
        return [self._decode(key) for key in await client.keys(self.prefix + b"*")]


class AsyncRedisTTLStringSet(AsyncRedisTTLSet[str]):
    def _encode(self, value: str) -> bytes:
        return self.prefix + value.encode()

    def _decode(self, key: bytes) -> str:
        return key.removeprefix(self.prefix).decode()

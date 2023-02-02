import pickle
from abc import ABC, abstractmethod
from collections.abc import MutableSet
from typing import Generic, Hashable, Iterator, TypeVar

import packaging.version
from cachetools import TTLCache
from redis import StrictRedis

_T_Base = TypeVar("_T_Base")


class _BaseTTLSet(ABC, MutableSet[_T_Base], Generic[_T_Base]):
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


class LocalTTLSet(_BaseTTLSet[_T_Local], Generic[_T_Local]):
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


class RedisTTLSet(_BaseTTLSet[_T_Redis], Generic[_T_Redis]):
    def __init__(self, ttl: int, client: StrictRedis, prefix: str = "RedisTTLSet"):
        super().__init__(ttl)

        self.client = client

        self.prefix = prefix.encode()
        if b"*" in self.prefix:
            raise ValueError('prefix must not contain "*"')

        self.redis_version = self.__redis_version(client)
        if self.redis_version < packaging.version.parse("6.2.0"):
            self.remove = self.__remove_pre_6_2_0
        else:
            self.remove = self.__remove_6_2_0

    @staticmethod
    def __redis_version(client: StrictRedis) -> packaging.version.Version:
        info = client.info()
        version = packaging.version.parse(info["redis_version"])
        return version

    def _encode(self, value: _T_Redis) -> bytes:
        serialized = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        return self.prefix + serialized

    def _decode(self, key: bytes) -> _T_Redis:
        return pickle.loads(key.removeprefix(self.prefix))

    def discard(self, value: _T_Redis) -> None:
        key = self._encode(value)
        self.client.delete(key)

    def remove(self, value: _T_Redis) -> None:
        # To be assigned in __init__ according to Redis version
        raise NotImplementedError

    def __remove_pre_6_2_0(self, value: _T_Redis) -> None:
        key = self._encode(value)
        if self.client.exists(key) == 0:
            raise KeyError(f"{value} not found")
        self.client.delete(key)

    def __remove_6_2_0(self, value: _T_Redis) -> None:
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

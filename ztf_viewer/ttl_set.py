from abc import ABC, abstractmethod
from collections.abc import MutableSet
from typing import Hashable, Iterator, TypeVar, Dict, Any

from cachetools import TTLCache
from redis import StrictRedis

_T = TypeVar("_T", bound=Hashable)


class _BaseTTLSet(ABC, MutableSet[_T]):
    def __init__(self, ttl: int):
        super().__init__()
        self.ttl = ttl

    def discard(self, value: _T) -> None:
        try:
            self.remove(value)
        except KeyError:
            pass

    @abstractmethod
    def remove(self, value: _T) -> None:
        """Must raise valueError if no value is not found"""
        raise NotImplemented

    @abstractmethod
    def clear(self) -> None:
        raise NotImplemented


class LocalTTLSet(_BaseTTLSet):
    def __init__(self, maxsize: int, ttl: int):
        super().__init__(ttl)
        self.ttl_cache = TTLCache(maxsize=maxsize, ttl=ttl)
        
    def add(self, value: _T) -> None:
        self.ttl_cache[value] = None

    def remove(self, value: _T) -> None:
        del self.ttl_cache[value]

    def clear(self) -> None:
        self.ttl_cache.clear()

    def __contains__(self, value: _T) -> bool:
        return value in self.ttl_cache

    def __len__(self) -> int:
        return len(self.ttl_cache)

    def __iter__(self) -> Iterator[_T]:
        return iter(self.ttl_cache)


class RedisTTLSet(_BaseTTLSet):
    def __init__(self, ttl: int, client: StrictRedis, prefix: str = 'RedisTTLSet'):
        super().__init__(ttl)

        self.client = client
        self.prefix = prefix

    def discard(self, value: _T) -> None:
        key = f'{self.prefix}{value}'
        self.client.delete(key)

    def remove(self, value: _T) -> None:
        key = f'{self.prefix}{value}'
        if self.client.getdel(key) is not None:
            raise KeyError(f'{value} not found')

    def clear(self) -> None:
        for key in self.client.keys(f'{self.prefix}*'):
            self.client.delete(key)

    def add(self, value: _T) -> None:
        key = f'{self.prefix}{value}'
        self.client.setex(key, self.ttl, 0)

    def __contains__(self, value: _T) -> bool:
        key = f'{self.prefix}{value}'
        return self.client.exists(key) > 0

    def __len__(self) -> int:
        return len(self.client.keys(f'{self.prefix}*'))

    def __iter__(self) -> Iterator[_T]:
        for key in self.client.keys(f'{self.prefix}*'):
            yield key.removeprefix(self.prefix)
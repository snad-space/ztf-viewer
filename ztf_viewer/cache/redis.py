"""The Redis cache backend: a plain ``StrictRedis`` with a per-entry TTL.

This is the production backend.  Eviction under memory pressure is Redis' own ``allkeys-lru``
(see ``docker-compose.yml``), so nothing here maintains an LRU of its own.

Despite the module name, ``import redis`` below is the third-party client: Python 3 imports are
absolute, so a submodule never shadows a top-level package for its siblings or for itself.  The
client class is looked up on the module at call time rather than imported by name, which is also
what lets a test point the backend at its own server.

The async backend needs no object-level sharing with the sync one for key-compatibility (unlike
the memory backend): both just point at the same Redis server and use the same key scheme
(``ztf_viewer.cache.core``), so a value either writes is a hit for the other.
"""

import asyncio
import threading
import weakref

import redis
import redis.asyncio

from ztf_viewer import config
from ztf_viewer.cache.decorator import make_async_cache, make_cache


class RedisBackend:
    def __init__(self, client, ttl):
        self._client = client
        self._ttl = ttl

    def get(self, key):
        return self._client.get(key)

    def set(self, key, blob):
        self._client.set(key, blob, ex=self._ttl)


def create_redis_cache(ttl):
    return make_cache(RedisBackend(redis.StrictRedis(config.REDIS_HOSTNAME), ttl=ttl))


class AsyncRedisBackend:
    """The async Redis store: a ``redis.asyncio.Redis`` client, built lazily per running loop.

    A connection pool is loop-affine — building it at import or construction time would bind it
    to whatever loop happens to be running then, and break on a second ``asyncio.run()`` (Flask's
    per-request loop model). ``client_factory`` is called again for each new running loop
    instead. A `weakref.WeakKeyDictionary` here is a stand-in for a per-loop registry a later
    change will retrofit onto this.
    """

    def __init__(self, client_factory, ttl):
        self._client_factory = client_factory
        self._ttl = ttl
        self._clients = weakref.WeakKeyDictionary()
        self._registry_lock = threading.Lock()

    def _client(self):
        loop = asyncio.get_running_loop()
        # threading.Lock, not asyncio: the WeakKeyDictionary itself is shared across threads, one loop each.
        with self._registry_lock:
            client = self._clients.get(loop)
            if client is None:
                client = self._clients[loop] = self._client_factory()
        return client

    async def get(self, key):
        return await self._client().get(key)

    async def set(self, key, blob):
        await self._client().set(key, blob, ex=self._ttl)


def create_async_redis_cache(ttl):
    return make_async_cache(AsyncRedisBackend(lambda: redis.asyncio.Redis(config.REDIS_HOSTNAME), ttl=ttl))

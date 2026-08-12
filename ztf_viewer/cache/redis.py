"""The Redis cache backend: a plain ``StrictRedis`` with a per-entry TTL.

This is the production backend.  Eviction under memory pressure is Redis' own ``allkeys-lru``
(see ``docker-compose.yml``), so nothing here maintains an LRU of its own.

Despite the module name, ``import redis`` below is the third-party client: Python 3 imports are
absolute, so a submodule never shadows a top-level package for its siblings or for itself.  The
client class is looked up on the module at call time rather than imported by name, which is also
what lets a test point the backend at its own server.
"""

import redis

from ztf_viewer import config
from ztf_viewer.cache.decorator import make_cache


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

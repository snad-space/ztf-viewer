import functools

from config import CACHE_TYPE


TTL = 7 * 86400
MAXSIZE = 1 << 16


def _create_redis_cache():
    from redis import StrictRedis
    from redis_lru import RedisLRU

    from config import REDIS_HOSTNAME

    redis_conn = StrictRedis(REDIS_HOSTNAME)
    redis_lru = RedisLRU(redis_conn, default_ttl=TTL, max_size=MAXSIZE)
    cache = functools.partial(redis_lru, ttl=TTL)
    return cache


def _crate_memory_cache():
    from cachetools import cached, TTLCache

    ttl_cache = TTLCache(MAXSIZE, ttl=TTL)
    cache = functools.partial(cached, cache=ttl_cache)
    return cache


CACHE_CREATORS = {
    'redis': _create_redis_cache,
    'memory': _crate_memory_cache,
}


def _get_cache():
    try:
        return CACHE_CREATORS[CACHE_TYPE.lower().strip()]()
    except KeyError as e:
        raise ValueError(f'CACHE_TYPE must be one of: {", ".join(CACHE_CREATORS)}') from e


cache = _get_cache()

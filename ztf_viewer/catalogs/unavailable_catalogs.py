import redis.asyncio
from redis import StrictRedis

from ztf_viewer.config import REDIS_HOSTNAME, UNAVAILABLE_CATALOGS_CACHE_TYPE
from ztf_viewer.ttl_set import AsyncLocalTTLSet, AsyncRedisTTLStringSet, LocalTTLSet, RedisTTLStringSet

TTL = 5 * 60  # 5 minutes
MAXSIZE = 1 << 10  # number of catalogs, we have much less


def _create_redis():
    redis_client = StrictRedis(REDIS_HOSTNAME)
    return RedisTTLStringSet(TTL, client=redis_client, prefix="unavailable_catalogs")


CREATORS = {
    "redis": _create_redis,
    "memory": lambda: LocalTTLSet(maxsize=MAXSIZE, ttl=TTL),
}


def _get_unavailable_catalogs():
    try:
        return CREATORS[UNAVAILABLE_CATALOGS_CACHE_TYPE.lower().strip()]()
    except KeyError as e:
        raise ValueError(f'UNAVAILABLE_CATALOGS_CACHE_TYPE must be one of: {", ".join(CREATORS)}') from e


unavailable_catalogs = _get_unavailable_catalogs()


def _create_async_redis():
    # No client at construction time: AsyncRedisTTLStringSet builds one lazily, per running loop.
    return AsyncRedisTTLStringSet(
        TTL, client_factory=lambda: redis.asyncio.Redis(REDIS_HOSTNAME), prefix="unavailable_catalogs"
    )


ASYNC_CREATORS = {
    "redis": _create_async_redis,
    "memory": lambda: AsyncLocalTTLSet(local=unavailable_catalogs),
}


def _get_unavailable_catalogs_async():
    try:
        return ASYNC_CREATORS[UNAVAILABLE_CATALOGS_CACHE_TYPE.lower().strip()]()
    except KeyError as e:
        raise ValueError(f'UNAVAILABLE_CATALOGS_CACHE_TYPE must be one of: {", ".join(ASYNC_CREATORS)}') from e


unavailable_catalogs_async = _get_unavailable_catalogs_async()

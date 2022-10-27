import functools

from ztf_viewer.config import UNAVAILABLE_CATALOGS_CACHE_TYPE, REDIS_HOSTNAME
from ztf_viewer.ttl_set import LocalTTLSet, RedisTTLStringSet

from redis import StrictRedis

TTL = 5 * 60  # 5 minutes
MAXSIZE = 1 << 10  # number of catalogs, we have much less


def _create_redis():
    redis_client = StrictRedis(REDIS_HOSTNAME)
    return RedisTTLStringSet(TTL, client=redis_client, prefix='unavailable_catalogs')


CREATORS = {
    'redis': _create_redis,
    'memory': lambda: LocalTTLSet(maxsize=MAXSIZE, ttl=TTL),
}


def _get_unavailable_catalogs():
    try:
        return CREATORS[UNAVAILABLE_CATALOGS_CACHE_TYPE.lower().strip()]()
    except KeyError as e:
        raise ValueError(f'UNAVAILABLE_CATALOGS_CACHE_TYPE must be one of: {", ".join(CREATORS)}') from e


unavailable_catalogs = _get_unavailable_catalogs()

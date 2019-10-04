import functools

import redis
import redis_lru


TTL = 7 * 86400
MAXSIZE = 1 << 16

REDIS_CONN = redis.StrictRedis('redis')
_RedisLRU = redis_lru.RedisLRU(REDIS_CONN, default_ttl=TTL, max_size=MAXSIZE)
cache = functools.partial(_RedisLRU, ttl=TTL)

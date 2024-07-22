import time

import pytest

from ztf_viewer.ttl_set import RedisTTLSet


def test_clear(redisdb) -> None:
    ttl_set = RedisTTLSet(client=redisdb, ttl=86400)
    ttl_set.add(1)
    ttl_set.add(2)
    ttl_set.clear()
    assert len(ttl_set) == 0


def test_add(redisdb) -> None:
    ttl_set = RedisTTLSet(client=redisdb, ttl=86400)
    ttl_set.add(1)
    assert len(ttl_set) == 1


def test_remove(redisdb) -> None:
    ttl_set = RedisTTLSet(client=redisdb, ttl=86400)
    ttl_set.add(1)
    ttl_set.remove(1)
    assert len(ttl_set) == 0


def test_contains(redisdb) -> None:
    ttl_set = RedisTTLSet(client=redisdb, ttl=86400)
    ttl_set.add(1)
    assert 1 in ttl_set


def test_iter(redisdb) -> None:
    ttl_set = RedisTTLSet(client=redisdb, ttl=86400)
    ttl_set.add(1)
    assert set(ttl_set) == {1}


def test_len(redisdb) -> None:
    ttl_set = RedisTTLSet(client=redisdb, ttl=86400)
    ttl_set.add(1)
    assert len(ttl_set) == 1


def test_len_0(redisdb) -> None:
    ttl_set = RedisTTLSet(client=redisdb, ttl=86400)
    assert len(ttl_set) == 0


def test_multiple_add(redisdb) -> None:
    ttl_set = RedisTTLSet(client=redisdb, ttl=86400)
    ttl_set.add(1)
    ttl_set.add(1)
    assert len(ttl_set) == 1


def test_multiple_remove(redisdb) -> None:
    ttl_set = RedisTTLSet(client=redisdb, ttl=86400)
    ttl_set.add(1)
    ttl_set.remove(1)
    with pytest.raises(KeyError):
        ttl_set.remove(1)
    assert len(ttl_set) == 0


def test_multiple_iter(redisdb) -> None:
    ttl_set = RedisTTLSet(client=redisdb, ttl=86400)
    ttl_set.add(1)
    ttl_set.add(2)
    assert set(ttl_set) == {1, 2}


def test_ttl(redisdb) -> None:
    ttl_set = RedisTTLSet(client=redisdb, ttl=1)
    ttl_set.add(1)
    assert len(ttl_set) == 1
    time.sleep(2)
    assert len(ttl_set) == 0


def test_ttl_prolongation(redisdb) -> None:
    ttl_set = RedisTTLSet(client=redisdb, ttl=2)
    ttl_set.add(1)
    assert len(ttl_set) == 1
    time.sleep(1)
    ttl_set.add(1)
    time.sleep(1)
    assert len(ttl_set) == 1
    time.sleep(2)
    assert len(ttl_set) == 0

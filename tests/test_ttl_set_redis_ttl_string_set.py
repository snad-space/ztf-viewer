import time

import pytest

from ztf_viewer.ttl_set import RedisTTLStringSet


def test_clear(redisdb) -> None:
    ttl_set = RedisTTLStringSet(client=redisdb, ttl=86400)
    ttl_set.add("a")
    ttl_set.add("b")
    ttl_set.clear()
    assert len(ttl_set) == 0


def test_add(redisdb) -> None:
    ttl_set = RedisTTLStringSet(client=redisdb, ttl=86400)
    ttl_set.add("")
    assert len(ttl_set) == 1


def test_remove(redisdb) -> None:
    ttl_set = RedisTTLStringSet(client=redisdb, ttl=86400)
    ttl_set.add("a")
    ttl_set.remove("a")
    assert len(ttl_set) == 0


def test_contains(redisdb) -> None:
    ttl_set = RedisTTLStringSet(client=redisdb, ttl=86400)
    ttl_set.add("")
    assert "" in ttl_set


def test_iter(redisdb) -> None:
    ttl_set = RedisTTLStringSet(client=redisdb, ttl=86400)
    ttl_set.add("abc")
    assert set(ttl_set) == {"abc"}


def test_len(redisdb) -> None:
    ttl_set = RedisTTLStringSet(client=redisdb, ttl=86400)
    ttl_set.add("X")
    assert len(ttl_set) == 1


def test_len_0(redisdb) -> None:
    ttl_set = RedisTTLStringSet(client=redisdb, ttl=86400)
    assert len(ttl_set) == 0


def test_multiple_add(redisdb) -> None:
    ttl_set = RedisTTLStringSet(client=redisdb, ttl=86400)
    ttl_set.add("α")
    ttl_set.add("α")
    assert len(ttl_set) == 1


def test_multiple_remove(redisdb) -> None:
    ttl_set = RedisTTLStringSet(client=redisdb, ttl=86400)
    ttl_set.add("Цирк")
    ttl_set.remove("Цирк")
    with pytest.raises(KeyError):
        ttl_set.remove("Цирк")
    assert len(ttl_set) == 0


def test_multiple_iter(redisdb) -> None:
    ttl_set = RedisTTLStringSet(client=redisdb, ttl=86400)
    ttl_set.add("abc")
    ttl_set.add("def")
    assert set(ttl_set) == {"abc", "def"}


def test_ttl(redisdb) -> None:
    ttl_set = RedisTTLStringSet(client=redisdb, ttl=1)
    ttl_set.add("a")
    assert len(ttl_set) == 1
    time.sleep(2)
    assert len(ttl_set) == 0


def test_ttl_prolongation(redisdb) -> None:
    ttl_set = RedisTTLStringSet(client=redisdb, ttl=2)
    ttl_set.add("a")
    assert len(ttl_set) == 1
    time.sleep(1)
    ttl_set.add("a")
    time.sleep(1)
    assert len(ttl_set) == 1
    time.sleep(1)
    assert len(ttl_set) == 0

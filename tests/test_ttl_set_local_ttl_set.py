import time

import pytest

from ztf_viewer.ttl_set import LocalTTLSet


def test_clear() -> None:
    ttl_set = LocalTTLSet(maxsize=2, ttl=86400)
    ttl_set.add(1)
    ttl_set.add(2)
    ttl_set.clear()
    assert len(ttl_set) == 0


def test_add() -> None:
    ttl_set = LocalTTLSet(maxsize=1, ttl=86400)
    ttl_set.add(1)
    assert len(ttl_set) == 1


def test_remove() -> None:
    ttl_set = LocalTTLSet(maxsize=1, ttl=86400)
    ttl_set.add(1)
    ttl_set.remove(1)
    assert len(ttl_set) == 0


def test_contains() -> None:
    ttl_set = LocalTTLSet(maxsize=1, ttl=86400)
    ttl_set.add(1)
    assert 1 in ttl_set


def test_iter() -> None:
    ttl_set = LocalTTLSet(maxsize=1, ttl=86400)
    ttl_set.add(1)
    assert set(ttl_set) == {1}


def test_len() -> None:
    ttl_set = LocalTTLSet(maxsize=1, ttl=86400)
    ttl_set.add(1)
    assert len(ttl_set) == 1


def test_len_0() -> None:
    ttl_set = LocalTTLSet(maxsize=1, ttl=86400)
    assert len(ttl_set) == 0


def test_multiple_add() -> None:
    ttl_set = LocalTTLSet(maxsize=2, ttl=86400)
    ttl_set.add(1)
    ttl_set.add(1)
    assert len(ttl_set) == 1


def test_multiple_remove() -> None:
    ttl_set = LocalTTLSet(maxsize=2, ttl=86400)
    ttl_set.add(1)
    ttl_set.remove(1)
    with pytest.raises(KeyError):
        ttl_set.remove(1)
    assert len(ttl_set) == 0


def test_multiple_iter() -> None:
    ttl_set = LocalTTLSet(maxsize=2, ttl=86400)
    ttl_set.add(1)
    ttl_set.add(2)
    assert set(ttl_set) == {1, 2}


def test_ttl() -> None:
    ttl_set = LocalTTLSet(maxsize=2, ttl=1)
    ttl_set.add(1)
    assert len(ttl_set) == 1
    time.sleep(2)
    assert len(ttl_set) == 0


def test_ttl_prolongation() -> None:
    ttl_set = LocalTTLSet(maxsize=2, ttl=2)
    ttl_set.add(1)
    assert len(ttl_set) == 1
    time.sleep(1)
    ttl_set.add(1)
    time.sleep(1)
    assert len(ttl_set) == 1
    time.sleep(1)
    assert len(ttl_set) == 0

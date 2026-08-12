"""Decorator-level tests for the sync ``cache()`` (plan 001, ``aio-cache-sync``).

``tests/test_cache_contract.py`` is the spec and covers hit/miss/TTL/value fidelity on both
backends.  This file covers what the spec deliberately does not: the guards and the escape
hatches that are properties of *this* implementation rather than of any cache.
"""

import pytest

from ztf_viewer import cache as cache_module


@pytest.fixture
def cache(monkeypatch):
    monkeypatch.setattr(cache_module, "CACHE_TYPE", "memory", raising=False)
    from ztf_viewer import config

    monkeypatch.setattr(config, "CACHE_TYPE", "memory", raising=False)
    return cache_module._get_cache()


def test_cache_rejects_a_coroutine_function(cache):
    """Plan 001, F3: caching a coroutine object hands out an exhausted awaitable."""

    async def coro():
        return 1

    with pytest.raises(TypeError):
        cache()(coro)


def test_cache_accepts_a_plain_function(cache):
    @cache()
    def plain():
        return 1

    assert plain() == 1


def test_wrapper_keeps_the_wrapped_function_metadata(cache):
    @cache()
    def documented(a, b):
        """Doc."""
        return a + b

    assert documented.__name__ == "documented"
    assert documented.__doc__ == "Doc."
    assert documented.__wrapped__.__name__ == "documented"


def test_an_unencodable_argument_bypasses_the_cache_instead_of_raising(cache):
    calls = []

    @cache()
    def counted(arg):
        calls.append(arg)
        return len(calls)

    unencodable = lambda: None  # noqa: E731 - a lambda cannot be pickled

    assert counted(unencodable) == 1
    assert counted(unencodable) == 2, "an uncacheable argument must bypass, not poison, the cache"


def test_an_unserializable_result_is_returned_but_not_cached(cache):
    calls = []

    @cache()
    def counted():
        calls.append(None)
        return lambda: len(calls)  # a lambda cannot be pickled

    assert counted()() == 1
    assert counted()() == 2
    assert len(calls) == 2


def test_clear_memory_caches_empties_already_decorated_functions(cache):
    calls = []

    @cache()
    def counted():
        calls.append(None)
        return len(calls)

    assert counted() == 1
    assert counted() == 1
    cache_module.clear_memory_caches()
    assert counted() == 2


def test_unknown_cache_type_is_rejected(monkeypatch):
    from ztf_viewer import config

    monkeypatch.setattr(cache_module, "CACHE_TYPE", "nonesuch", raising=False)
    monkeypatch.setattr(config, "CACHE_TYPE", "nonesuch", raising=False)
    with pytest.raises(ValueError, match="CACHE_TYPE must be one of"):
        cache_module._get_cache()

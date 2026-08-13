"""Decoration-time guard against callables ``function_id`` cannot key.

``function_id`` used to evaluate ``func.__name__`` eagerly even when ``__qualname__`` was
present, raising ``AttributeError`` on first call for anything missing it (defect 1); and a
``functools.partial`` labelled with both attributes passed silently but keyed on the wrapped
function only, dropping the bound arguments from the key and returning another partial's cached
value (defect 2). Both are now refused at decoration time with a ``TypeError``.
"""

import functools

import pytest

from ztf_viewer import cache as cache_module
from ztf_viewer.cache.core import function_id


@pytest.fixture
def cache(monkeypatch):
    monkeypatch.setattr(cache_module, "CACHE_TYPE", "memory", raising=False)
    from ztf_viewer import config

    monkeypatch.setattr(config, "CACHE_TYPE", "memory", raising=False)
    return cache_module._get_cache()


def body(a, b):
    return a + b


def test_bare_partial_is_refused_at_decoration_time(cache):
    p = functools.partial(body, 1)
    with pytest.raises(TypeError, match="partial"):
        cache()(p)


def test_labelled_partial_is_still_refused(cache):
    """Defect 2: labelled, a partial passes the attribute check but would still collide —
    the key never sees the bound argument, so two partials of the same function would share
    one cache entry and return each other's value."""
    p1 = functools.partial(body, 1)
    p2 = functools.partial(body, 100)
    for p in (p1, p2):
        p.__name__ = p.__qualname__ = "body"

    with pytest.raises(TypeError, match="partial"):
        cache()(p1)
    with pytest.raises(TypeError, match="partial"):
        cache()(p2)


def test_qualname_without_name_is_refused(cache):
    """Defect 1: today this raises AttributeError from inside the wrapper on first call."""

    class Fake:
        __qualname__ = "Fake"
        __module__ = "tests.test_cache_name_guard"

        def __call__(self, *a, **k):
            return None

    fake = Fake()
    assert not hasattr(fake, "__name__")

    with pytest.raises(TypeError):
        function_id(fake)
    with pytest.raises(TypeError):
        cache()(fake)


def test_ordinary_function_is_accepted_and_caches(cache):
    calls = []

    @cache()
    def plain(x):
        calls.append(x)
        return x * 2

    assert plain(3) == 6
    assert plain(3) == 6
    assert calls == [3]


def test_method_is_accepted_and_caches(cache):
    calls = []

    class Thing:
        @cache()
        def method(self, x):
            calls.append(x)
            return x * 2

    t = Thing()
    assert t.method(3) == 6
    assert t.method(3) == 6
    assert calls == [3]


def test_functools_wraps_decorated_function_is_accepted(cache):
    def outer(func):
        @functools.wraps(func)
        def inner(*args, **kwargs):
            return func(*args, **kwargs)

        return inner

    calls = []

    @cache()
    @outer
    def wrapped(x):
        calls.append(x)
        return x * 2

    assert wrapped(3) == 6
    assert wrapped(3) == 6
    assert calls == [3]

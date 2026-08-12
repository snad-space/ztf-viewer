"""Guards on how the cache decorators are applied (F3 in ``plans/001_async_dash.md``).

Both tests describe what is *supposed* to hold today, not a future state.

``@cache()`` wraps a function and stores its return value.  Applied to an
``async def`` it stores the **coroutine object** instead of the result, so the
second hit returns a coroutine that has already been awaited — which raises
rather than returning the cached value.  Nothing in the codebase does this yet,
and the first test makes sure it stays that way; the second asserts that the
decorator refuses outright, so the mistake cannot reach a review at all.

``test_sync_cache_rejects_a_coroutine_function`` fails on today's
``redis_lru``/``cachetools`` implementation, which accepts the coroutine
silently.  That is a real defect, fixed by the ``cache-sync`` branch.
"""

import ast
import pathlib

import pytest

import ztf_viewer

PACKAGE_ROOT = pathlib.Path(ztf_viewer.__file__).parent


def _source_files():
    return sorted(PACKAGE_ROOT.rglob("*.py"))


def _parse(path):
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _rel(path):
    return path.relative_to(PACKAGE_ROOT.parent).as_posix()


def _decorator_name(node):
    """``@cache()`` -> "cache", ``@foo.acache()`` -> "acache", anything else -> None."""
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def _cache_decorated_definitions():
    """``(decorator_name, is_async, "path:line function")`` for every @cache/@acache site."""
    found = []
    for path in _source_files():
        for node in ast.walk(_parse(path)):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                name = _decorator_name(decorator)
                if name in ("cache", "acache"):
                    found.append(
                        (name, isinstance(node, ast.AsyncFunctionDef), f"{_rel(path)}:{node.lineno} {node.name}")
                    )
    return found


def test_cache_decorators_are_applied_to_the_matching_function_kind():
    """No ``@cache()`` on an ``async def`` anywhere in the package (and no ``@acache()`` on a ``def``)."""
    sites = _cache_decorated_definitions()
    assert sites, "no @cache()/@acache() sites found — did the scan break?"
    wrong = [
        f"@{name}() on {'async def' if is_async else 'def'} {where}"
        for name, is_async, where in sites
        if (name == "cache") == is_async
    ]
    assert not wrong, "cache decorator applied to the wrong kind of function:\n  " + "\n  ".join(wrong)


# FAILS TODAY — fixed by `cache-sync`.  Today's cache() is cachetools/redis_lru and silently
# caches the coroutine object, returning an already-awaited coroutine on the second hit.
def test_sync_cache_rejects_a_coroutine_function():
    """The decorator itself refuses, so the AST scan above is a backstop and not the only guard."""
    from ztf_viewer.cache import cache

    async def coro():
        return 1

    with pytest.raises(TypeError):
        cache()(coro)

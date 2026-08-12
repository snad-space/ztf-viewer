"""Invariants that guard the async / FastAPI migration (``plans/001_async_dash.md``).

Most of the tests here are **false today by design**: they encode rules that the
migration establishes, so they are landed as ``xfail`` and flipped to hard
assertions by the PR named in the marker's ``reason``.  ``strict=True`` means a
test that unexpectedly starts *passing* fails the suite — that is the signal that
the guard is ready to be flipped (drop the marker in the same PR).

Three invariants live here, in one file, because they share one job: they are the
CI-visible checklist of migration rules, and a reader asking "what is enforced?"
should find a single answer.  They are also all cheap, except the callback-map
one, which needs the app imported (see ``dash_app``).
"""

import ast
import asyncio
import functools
import inspect
import pathlib

import pytest

import ztf_viewer

PACKAGE_ROOT = pathlib.Path(ztf_viewer.__file__).parent

# ``import flask`` / ``from flask import ...`` is allowed only here, after `aio-deflask`.
FLASK_ALLOWED = frozenset({PACKAGE_ROOT / "web.py"})


def _source_files():
    return sorted(PACKAGE_ROOT.rglob("*.py"))


def _parse(path):
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _rel(path):
    return path.relative_to(PACKAGE_ROOT.parent).as_posix()


def _unwrap(func):
    """Best-effort recovery of the user function behind Dash/functools wrappers."""
    seen = set()
    while id(func) not in seen:
        seen.add(id(func))
        if isinstance(func, functools.partial):
            func = func.func
        elif hasattr(func, "__wrapped__"):
            func = func.__wrapped__
        else:
            break
    return func


def _describe(func):
    unwrapped = _unwrap(func)
    module = getattr(unwrapped, "__module__", "?")
    name = getattr(unwrapped, "__qualname__", repr(unwrapped))
    return f"{module}.{name}"


@pytest.fixture(scope="session")
def dash_app():
    """The fully-registered Dash app.

    ``ztf_viewer.__main__`` is what registers every callback, so it has to be
    imported — a static scan of the source cannot see them.  It also cannot see
    the registration-layer shim that `aio-shim` will add, which is the whole
    point of asserting on the runtime ``callback_map``.  The import pulls in the
    catalog modules and costs a few seconds; it is session-scoped and used by a
    single test, and it does no I/O at import time.
    """
    import ztf_viewer.__main__  # noqa: F401
    from ztf_viewer.app import app

    return app


def _server_side_callbacks(app):
    """``callback_map`` entries that run in Python.

    Clientside callbacks (``app.clientside_callback``) have no ``"callback"``
    key — they are JavaScript and can never be coroutine functions.
    """
    return {cid: entry["callback"] for cid, entry in app.callback_map.items() if "callback" in entry}


# --------------------------------------------------------------------------------------
# Invariant 1 — every callback is a coroutine function (F1, F1a; flipped by `aio-shim`)
# --------------------------------------------------------------------------------------


def test_partial_registration_is_visible_as_coroutine():
    """F1a's load-bearing assumption, asserted rather than trusted.

    Four callbacks are registered as ``app.callback(...)(partial(f, ...))``
    (``ztf_viewer/pages/viewer.py`` ``find_neighbours`` x2, ``set_figure_link``
    x2) plus one per catalog from ``set_tables``.  Dash decides sync-vs-async
    dispatch with ``inspect.iscoroutinefunction(func)`` at registration time, so
    that call must see through ``functools.partial`` for the shim to work.
    """

    async def coro(a, b):
        return a, b

    def plain(a, b):
        return a, b

    assert inspect.iscoroutinefunction(functools.partial(coro, 1))
    assert inspect.iscoroutinefunction(functools.partial(functools.partial(coro, 1), 2))
    assert not inspect.iscoroutinefunction(functools.partial(plain, 1))


def test_callback_map_is_populated(dash_app):
    """Sanity: the invariant below must not pass vacuously on an empty map."""
    server_side = _server_side_callbacks(dash_app)
    assert len(server_side) > 40, "callbacks are not registered — did the app import change?"


@pytest.mark.xfail(
    strict=True,
    reason="every callback is a plain `def` today; flipped to a hard assert by `aio-shim`, "
    "which wraps sync callbacks at registration time (F1/F1a)",
)
def test_every_callback_is_a_coroutine_function(dash_app):
    """F1: a sync callback blocks the event loop under the FastAPI backend."""
    sync = [
        f"{cid} -> {_describe(func)}"
        for cid, func in _server_side_callbacks(dash_app).items()
        if not inspect.iscoroutinefunction(func)
    ]
    assert not sync, "callbacks that are not coroutine functions:\n  " + "\n  ".join(sorted(sync))


# --------------------------------------------------------------------------------------
# Invariant 2 — Flask is imported only by ztf_viewer/web.py (F4; flipped by `aio-deflask`)
# --------------------------------------------------------------------------------------


def _flask_importers():
    offenders = []
    for path in _source_files():
        if path in FLASK_ALLOWED:
            continue
        for node in ast.walk(_parse(path)):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(name == "flask" or name.startswith("flask.") for name in names):
                offenders.append(f"{_rel(path)}:{node.lineno}")
    return offenders


@pytest.mark.xfail(
    strict=True,
    reason="flask is imported by ztf_viewer/akb.py and the figure/lc_csv/favicon pages, and "
    "ztf_viewer/web.py does not exist yet; fixed by `aio-deflask`",
)
def test_flask_is_imported_only_by_web_module():
    """All Flask coupling lives behind ``ztf_viewer/web.py`` so the backend flip is a one-file swap."""
    offenders = _flask_importers()
    assert not offenders, "flask imported outside ztf_viewer/web.py:\n  " + "\n  ".join(offenders)


# --------------------------------------------------------------------------------------
# Invariant 3 — cache()/acache() are never applied to the wrong kind of function (F3)
# --------------------------------------------------------------------------------------


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
    """F3: a sync cache decorator on an ``async def`` caches the coroutine object."""
    sites = _cache_decorated_definitions()
    assert sites, "no @cache()/@acache() sites found — did the scan break?"
    wrong = [
        f"@{name}() on {'async def' if is_async else 'def'} {where}"
        for name, is_async, where in sites
        if (name == "cache") == is_async
    ]
    assert not wrong, "cache decorator applied to the wrong kind of function:\n  " + "\n  ".join(wrong)


@pytest.mark.xfail(
    strict=True,
    reason="today's cache() is cachetools/redis_lru and silently caches the coroutine object (F3); "
    "the TypeError guard arrives with `aio-cache-sync`",
)
def test_sync_cache_rejects_a_coroutine_function():
    from ztf_viewer.cache import cache

    async def coro():
        return 1

    with pytest.raises(TypeError):
        cache()(coro)


@pytest.mark.xfail(
    strict=True,
    reason="acache() does not exist yet; it arrives with `aio-cache-async`, which also makes it "
    "raise TypeError on a plain function (F3)",
)
def test_acache_rejects_a_plain_function():
    from ztf_viewer.cache import acache  # ImportError today -> xfail

    def plain():
        return 1

    with pytest.raises(TypeError):
        acache()(plain)

    async def coro():
        return 1

    assert asyncio.iscoroutinefunction(acache()(coro))

"""Every callback registered through ``ztf_viewer.callbacks.callback`` is a coroutine.

The FastAPI backend runs a synchronous callback inline on the event loop; a coroutine gets a
threadpool hop instead. Dash only checks ``inspect.iscoroutinefunction`` at registration time,
so this is what actually guards the backend flip.
"""

import asyncio
import functools
import inspect
import os
import subprocess
import sys
import threading
import types
from pathlib import Path

import pytest

import ztf_viewer
from ztf_viewer.callbacks import _to_coroutine_function, callback

_REPO_ROOT = Path(ztf_viewer.__file__).parent.parent


@pytest.fixture(scope="session")
def dash_app():
    """Import the fully wired app, forcing the in-memory cache backend first.

    Mirrors ``tests/test_golden_http.py``'s fixture: ``unavailable_catalogs`` connects to Redis
    eagerly at import time, so ``CACHE_TYPE`` must be set before ``ztf_viewer.__main__`` is
    first imported.
    """
    from ztf_viewer import config

    config.CACHE_TYPE = "memory"
    config.UNAVAILABLE_CATALOGS_CACHE_TYPE = "memory"

    import ztf_viewer.__main__ as main_module

    return main_module.app


def _split_by_side(callback_map):
    """Clientside entries have no "callback" key at all — split explicitly, don't KeyError."""
    server_side = {k: v for k, v in callback_map.items() if "callback" in v}
    clientside = {k: v for k, v in callback_map.items() if "callback" not in v}
    return server_side, clientside


def test_callback_map_is_populated(dash_app):
    """Anti-vacuity check: an empty map would make every other assertion here pass for free."""
    assert len(dash_app.callback_map) > 0


def test_every_server_side_callback_is_a_coroutine_function(dash_app):
    server_side, clientside = _split_by_side(dash_app.callback_map)

    assert len(server_side) > 0
    assert len(clientside) > 0

    non_coroutines = [
        callback_id for callback_id, entry in server_side.items() if not inspect.iscoroutinefunction(entry["callback"])
    ]
    assert not non_coroutines, f"synchronous entries in callback_map: {non_coroutines}"


def test_iscoroutinefunction_sees_through_nested_partial():
    """Load-bearing for the shim: 23 of 57 registrations are partial-based."""

    async def coro():
        pass

    partial_once = functools.partial(coro)
    partial_twice = functools.partial(partial_once, x=1)

    assert inspect.iscoroutinefunction(partial_once)
    assert inspect.iscoroutinefunction(partial_twice)

    def sync():
        pass

    assert not inspect.iscoroutinefunction(functools.partial(sync))


def test_shim_wraps_a_partial_of_a_sync_function():
    def add(a, b):
        return a + b

    wrapped = _to_coroutine_function(functools.partial(add, b=1))

    assert inspect.iscoroutinefunction(wrapped)


async def test_shim_leaves_a_coroutine_function_unwrapped():
    async def already_async():
        return "unchanged"

    assert _to_coroutine_function(already_async) is already_async


def test_callback_registers_a_coroutine_function_on_the_app(dash_app):
    """``callback`` is a drop-in replacement for ``app.callback``: register, then unwrap sync."""
    from dash import Input, Output

    def sync_body(_value):
        return "value"

    callback(Output("callback-shim-test-target", "children"), [Input("callback-shim-test-source", "value")])(sync_body)

    entry = dash_app.callback_map["callback-shim-test-target.children"]
    assert inspect.iscoroutinefunction(entry["callback"])


async def test_ctx_cookies_readable_from_offloaded_thread():
    """The AKB/login path reads ``dash.ctx.cookies``; the offload must not lose it."""
    import dash
    from dash._callback_context import context_value

    def read_cookie():
        return dash.ctx.cookies["akb_token"]

    wrapped = _to_coroutine_function(read_cookie)

    token = context_value.set(types.SimpleNamespace(cookies={"akb_token": "abc123"}))
    try:
        result = await wrapped()
    finally:
        context_value.reset(token)

    assert result == "abc123"


def test_no_runtime_warning_on_registration():
    """Registering every callback must not trip dash's async-dispatch ``RuntimeWarning``.

    Run in a subprocess so the check is independent of what other test modules already imported.
    """
    script = (
        "import warnings\n"
        'warnings.simplefilter("error", RuntimeWarning)\n'
        "from ztf_viewer import config\n"
        'config.CACHE_TYPE = "memory"\n'
        'config.UNAVAILABLE_CATALOGS_CACHE_TYPE = "memory"\n'
        "import ztf_viewer.__main__\n"
        'print("OK")\n'
    )
    env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT)}
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env=env,
        cwd=_REPO_ROOT,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_wrapper_offloads_to_a_different_thread():
    """A sync callback run inline on the loop would serialize the whole app; the wrapper must
    hand it to the executor instead."""
    wrapped = _to_coroutine_function(threading.get_ident)

    assert asyncio.run(wrapped()) != threading.get_ident()


def test_wrapper_works_across_successive_event_loops():
    """Flask builds a fresh loop per request, so the wrapper must not hold loop-affine state."""
    wrapped = _to_coroutine_function(lambda: "called")

    assert asyncio.run(wrapped()) == "called"
    assert asyncio.run(wrapped()) == "called"

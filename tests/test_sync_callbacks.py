"""Callbacks are registered directly with ``app.callback``; most are ``async def``.

A handful stayed plain ``def`` on purpose: pure presentation/formatting logic with no network,
disk, or cache access, so running them inline on the event loop costs less than a thread hop
would. Every name below was read and confirmed to do no blocking I/O. This test is not a static
blocking-I/O checker (that can't be done reliably from the AST) — it is a change detector: if a
callback's sync/async status changes, this fails and forces a human to re-review it for blocking
calls before extending the allowlist.
"""

import functools
import inspect
import os
import subprocess
import sys
from pathlib import Path

import pytest

import ztf_viewer

_REPO_ROOT = Path(ztf_viewer.__file__).parent.parent

# Reviewed: each of these does only in-memory formatting/URL-building, no I/O.
_ALLOWED_SYNC_CALLBACKS = {
    "show_fit_params",
    "show_error_message",
    "set_min_max_mjd",
    "update_min_max_mjd_radio",
    "show_fold_period_layout",
    "show_ref_mag_layout",
    "set_csv_link",
    "set_figure_link",
    "convert_astro_colibri_search_radius_to_arcsec",
    "dr_from_url",
    "set_dr_title",
}


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


def _underlying_name(func):
    """Peel Dash's ``add_context`` wrapper (via ``__wrapped__``) and any ``functools.partial``."""
    func = inspect.unwrap(func)
    while isinstance(func, functools.partial):
        func = func.func
    return func.__name__


def test_callback_map_is_populated(dash_app):
    """Anti-vacuity check: an empty map would make every other assertion here pass for free."""
    assert len(dash_app.callback_map) > 0


def test_only_reviewed_pure_callbacks_run_synchronously(dash_app):
    server_side, clientside = _split_by_side(dash_app.callback_map)

    assert len(server_side) > 0
    assert len(clientside) > 0

    sync_names = {
        _underlying_name(entry["callback"])
        for entry in server_side.values()
        if not inspect.iscoroutinefunction(entry["callback"])
    }
    assert sync_names == _ALLOWED_SYNC_CALLBACKS, (
        "a callback's sync/async status changed. Every plain `def` callback runs inline on the "
        "event loop with no thread hop, so a newly-sync callback must be checked for blocking "
        "I/O (network, disk, cache) before its name is added to _ALLOWED_SYNC_CALLBACKS"
    )


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
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout

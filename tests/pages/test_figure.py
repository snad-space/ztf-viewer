"""Unit tests for `ztf_viewer.pages.figure` and `ztf_viewer.figure_render`.

`tests/test_golden_http.py`'s figure tests hit the real ZTF DR API and are network-marked, so
they only assert the HTTP surface (status, mimetype, magic bytes) and skip cleanly when the
network is unavailable. These tests cover what that one can't, without any network dependency:

* the renderers against synthetic light curves, for both formats;
* that `ztf_viewer.figure_render` -- the module the process pool re-imports in every spawned
  child -- never builds the Dash app as an import side effect, the way `pages.figure` does;
* that a crashed pool worker surfaces to the HTTP caller as a 500, not a hang, through the real
  route and the real process pool (only `get_plot_data` and the renderer are stubbed).
"""

import shutil
import subprocess
import sys

import pytest

from ztf_viewer import config

config.CACHE_TYPE = "memory"
config.UNAVAILABLE_CATALOGS_CACHE_TYPE = "memory"

from ztf_viewer.figure_render import plot_data, plot_folded_data

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_PDF_MAGIC = b"%PDF-"


def _pgf_texsystem():
    import matplotlib

    return matplotlib.rcParams.get("pgf.texsystem", "xelatex")


def _synthetic_lc(n=60):
    filters = ["zg", "zr", "zi"]
    return {
        1: [
            {"mjd": 58000.0 + i, "mag": 18.0 + 0.1 * (i % 5), "magerr": 0.05, "filter": filters[i % 3]}
            for i in range(n)
        ]
    }


def _synthetic_folded_lc(n=60, period=1.5):
    lc = _synthetic_lc(n)
    for obs_list in lc.values():
        for obs in obs_list:
            obs["folded_time"] = obs["mjd"] % period
            obs["phase"] = obs["folded_time"] / period
    return lc


def test_plot_data_renders_png():
    img = plot_data(1, _synthetic_lc(), fmt="png")
    assert img.startswith(_PNG_MAGIC)


def test_plot_data_renders_pdf():
    texsystem = _pgf_texsystem()
    if shutil.which(texsystem) is None:
        pytest.skip(f"LaTeX ({texsystem}) is not available locally; PDF rendering shells out to it")
    img = plot_data(1, _synthetic_lc(), fmt="pdf")
    assert img.startswith(_PDF_MAGIC)


def test_plot_folded_data_renders_png():
    img = plot_folded_data(1, _synthetic_folded_lc(), period=1.5, fmt="png")
    assert img.startswith(_PNG_MAGIC)


def test_figure_render_import_has_no_app_side_effects():
    """Spawn's re-import of a submitted function's module must stay cheap and side-effect-free:
    a fresh interpreter that only imports `figure_render` must never pull in Dash or the app."""
    code = (
        "import sys; import ztf_viewer.figure_render; " "print('dash' in sys.modules, 'ztf_viewer.app' in sys.modules)"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "False False"


def _crash_render(*args, **kwargs):
    import os

    os._exit(1)


async def _fake_get_plot_data(oid, dr, **kwargs):
    return _synthetic_lc()


def test_broken_pool_surfaces_as_500(monkeypatch):
    """A worker killed mid-render must reach the caller as a 500, not a hang or a 200 with a
    truncated body -- exercised through the real HTTP route and the real process pool.

    Uses its own client with ``raise_server_exceptions=False``: the shared `client` fixture's
    default (`True`) is a debug convenience that re-raises into the test instead of returning
    the response a real ASGI server would send, which is exactly the behaviour under test here.
    """
    from fastapi.testclient import TestClient

    import ztf_viewer.pages.figure as figure_module
    from tests.conftest import reset_shared_thread_pool

    monkeypatch.setattr(figure_module, "get_plot_data", _fake_get_plot_data)
    monkeypatch.setattr(figure_module, "plot_data", _crash_render)

    reset_shared_thread_pool()
    import ztf_viewer.__main__ as main_module

    with TestClient(main_module.app.server, raise_server_exceptions=False) as test_client:
        response = test_client.get("/dr24/figure/1")

    assert response.status_code == 500

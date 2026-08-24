"""The app serves its own index and its `static/` directory.

Imports `ztf_viewer.app` rather than `ztf_viewer.__main__`: the latter also registers the six
plain routes, which are not ported yet and fail at import time.
"""

from pathlib import Path

import pytest
from dash import html
from fastapi.testclient import TestClient

import ztf_viewer
from ztf_viewer.app import app

_PACKAGE_ROOT = Path(ztf_viewer.__file__).parent


@pytest.fixture(scope="module")
def client():
    """A client over the shared `app`, with a throwaway layout restored afterwards.

    `app` is a module-level singleton, so assigning its layout here would otherwise outlive this
    file and race with whatever set it first.
    """
    from tests.conftest import reset_shared_process_pool, reset_shared_thread_pool

    original = app._layout, app._layout_is_function
    app.layout = html.Div("test")
    reset_shared_thread_pool()
    reset_shared_process_pool()
    try:
        with TestClient(app.server) as test_client:
            yield test_client
    finally:
        app._layout, app._layout_is_function = original


def test_index_renders(client):
    response = client.get("/")

    assert response.status_code == 200
    assert '<div id="react-entry-point"' in response.text


def test_static_logo_is_served(client):
    response = client.get("/static/img/logo.svg")

    assert response.status_code == 200
    assert "image/svg+xml" in response.headers.get("content-type", "")
    # What `_StaticFilesNoCache` exists for; the same assertion in `test_golden_http.py` covers
    # only a JS9 file, which exists in the image but not in a checkout.
    assert response.headers.get("Cache-Control") == "no-cache"


def test_static_js9_is_served(client):
    """JS9 is installed into `ztf_viewer/static/js9/` at image build time, so this only runs in
    CI's Docker build, not a local checkout."""
    js9_path = _PACKAGE_ROOT / "static" / "js9" / "js9.min.js"
    if not js9_path.exists():
        pytest.skip(f"JS9 not installed locally (built into the image at build time): {js9_path}")

    response = client.get("/static/js9/js9.min.js")

    assert response.status_code == 200
    assert "javascript" in response.headers.get("content-type", "")

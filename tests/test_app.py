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


@pytest.fixture
def snad_name(monkeypatch):
    """Name the object pages resolve, in place of the catalog and the API call behind it.

    Returns a setter, so a test says what the object is called and nothing here touches the
    network. Unset, an object has no SNAD name, which is the common case.
    """
    from ztf_viewer.catalogs.snad import catalog

    def set_name(name):
        async def stub(oid, dr):
            return name

        monkeypatch.setattr(catalog, "snad_name", stub)

    set_name(None)
    return set_name


def test_index_renders(client):
    response = client.get("/")

    assert response.status_code == 200
    assert '<div id="react-entry-point"' in response.text


def test_index_carries_the_link_preview_of_the_page_asked_for(client, snad_name):
    """`ztf_viewer.social` only reaches a reader if the index is built per request."""
    response = client.get("/dr17/view/633207400004730")

    assert response.status_code == 200
    assert '<meta property="og:title" content="633207400004730 — SNAD ZTF DR17 viewer">' in response.text
    assert '<meta property="og:image" content="http://testserver/dr17/card/633207400004730.webp">' in response.text


def test_index_of_a_named_object_leads_with_its_snad_name(client, snad_name):
    """The name is not in the pathname, so the index only carries it if something looked it up
    before Dash rendered the page."""
    snad_name("SNAD101")

    response = client.get("/dr17/view/633207400004730")

    assert '<meta property="og:title" content="SNAD101 — 633207400004730 — SNAD ZTF DR17 viewer">' in response.text
    assert "SNAD101" in response.text.split('name="description" content="')[1]


def test_index_still_renders_when_the_name_cannot_be_resolved(client, monkeypatch):
    """The lookup goes to an external API; a preview is never worth failing the page over."""
    from ztf_viewer.catalogs.snad import catalog

    async def boom(oid, dr):
        raise ConnectionError("no network")

    monkeypatch.setattr(catalog, "snad_name", boom)

    response = client.get("/dr17/view/633207400004730")

    assert response.status_code == 200
    assert '<meta property="og:title" content="633207400004730 — SNAD ZTF DR17 viewer">' in response.text


def test_index_of_a_page_without_a_light_curve_previews_the_site_card(client):
    response = client.get("/")

    assert '<meta property="og:image" content="http://testserver/card.webp">' in response.text
    assert '<meta name="twitter:card" content="summary_large_image">' in response.text


def test_the_logo_the_cards_are_drawn_with_is_served(client):
    response = client.get("/static/img/logo.png")

    assert response.status_code == 200
    assert "image/png" in response.headers.get("content-type", "")


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

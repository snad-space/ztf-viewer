"""Golden HTTP-surface tests.

Pin the parts of route responses this repository actually controls: status codes, headers,
content types, ``Content-Disposition``, CSV header rows/column sets, and file magic bytes.
Anything that is really a third party's payload (exact CSV data rows, exact PNG/PDF bytes,
the full Dash index HTML) is out of scope — it would go red for reasons outside this repo.

Split by what a test needs:

* Hermetic (no network): the ``/static`` mount, ``/health``, ``/favicon.ico``, the index, the
  no-object-lookup page routes (``/login``, ``/tags``, ``/anomalies``) — these are Dash's static
  index shell for any unmatched pathname, so hitting them makes no network call at all — and the
  CSV route registration order (which handler a path resolves to, not what it returns).
* ``@pytest.mark.network``: the CSV and figure routes, which look up a real object through the
  ZTF DR light-curve API (and, for figures, run matplotlib/LaTeX). A transport failure there is
  converted to a skip by ``tests/conftest.py``, not a failure.

Left out entirely, and why:

* Byte-exact CSV data rows and byte-exact PNG/PDF content — pure network/library payload, not
  ours to pin (matplotlib and LaTeX output is not reproducible across versions either).
* The Pan-STARRS and Gaia CSV "friends" of ``/dr24/csv/<oid>``: they share the same
  ``_lc_to_csv_response`` helper in ``ztf_viewer/pages/lc_csv.py`` as the Antares route exercised
  below, which already covers that code path.
* Full Dash index HTML snapshots for any page route — Dash's index is not a stable golden and
  would churn on every Dash upgrade for reasons with nothing to do with this repo's routing.
"""

import shutil
from pathlib import Path

import pytest

import ztf_viewer

_PACKAGE_ROOT = Path(ztf_viewer.__file__).parent

# A real, stable ZTF object also used as the worked example on the front page
# (`ztf_viewer/__main__.py`) and in `tests/catalogs/test_ztf_ref.py`.
_OID = 633207400004730
_DR = "dr24"

# A real Antares locus near a known ZTF object (`tests/catalogs/conesearch/test_antares.py`'s
# coordinates), resolved once against the live API.
_ANTARES_LOCUS_ID = "ANT2020g7nq"


def _load_app():
    """Import and return the Dash ``app``, forcing the in-memory cache backends first.

    ``ztf_viewer.catalogs.unavailable_catalogs`` connects to Redis *eagerly* at import time
    (``RedisTTLStringSet.__init__`` calls ``client.info()``), so ``CACHE_TYPE`` /
    ``UNAVAILABLE_CATALOGS_CACHE_TYPE`` must already be ``"memory"`` before
    ``ztf_viewer.__main__`` (which pulls in ``ztf_viewer.catalogs``) is imported for the first
    time.

    Called at module level, below, rather than lazily inside a fixture: pytest imports every
    test module before running any test, so this runs before any other module's fixture can
    build a ``TestClient`` around the same shared ``ztf_viewer.app.app`` and trigger the ASGI
    lifespan -- which registers Dash's ``{path:path}`` catch-all. Do that before the six routes
    below are registered and the catch-all shadows every one of them for the rest of the session.
    """
    from ztf_viewer import config

    config.CACHE_TYPE = "memory"
    config.UNAVAILABLE_CATALOGS_CACHE_TYPE = "memory"

    import ztf_viewer.__main__ as main_module

    return main_module.app


_APP = _load_app()


@pytest.fixture(scope="session")
def dash_app():
    return _APP


@pytest.fixture(scope="session")
def client(dash_app):
    """An ASGI test client for the Dash server.

    Constructed as a context manager so ASGI lifespan actually runs -- without it, Dash never
    registers its catch-all route and every page route 404s.
    """
    from fastapi.testclient import TestClient

    with TestClient(dash_app.server) as test_client:
        yield test_client


def _body(response):
    return response.content


def _content_type(response):
    return response.headers.get("content-type", "")


# --------------------------------------------------------------------------------------------
# 1. /static -- the single highest-value test: catches a bare app with no /static route at all,
#    and the Flask-vs-Starlette cache-header difference.
# --------------------------------------------------------------------------------------------


def test_static_logo_is_mounted(client):
    """`/static/img/logo.svg` always exists in the repo, so this runs everywhere (unlike the JS9
    test below) and is the cheapest possible guard that the /static mount exists at all.
    """
    response = client.get("/static/img/logo.svg")

    assert response.status_code == 200
    assert "image/svg+xml" in _content_type(response)
    assert response.headers.get("ETag")


def test_static_js9_js9_min_js(client):
    """JS9 is installed into `ztf_viewer/static/js9/` at image build time, so the file exists in
    CI's Docker build but generally not in a local checkout. Skip locally with a clear reason;
    this must genuinely run in CI.

    The header assertions are the real regression net: a missing /static route would 404 into
    the Dash catch-all instead of returning 200, and a future ASGI backend's StaticFiles sends
    only ETag/Last-Modified where Flask 3.1's `send_file` sends `Cache-Control: no-cache` plus
    ETag/Last-Modified. Pin what we see today so losing the route or losing headers is caught.
    """
    js9_path = _PACKAGE_ROOT / "static" / "js9" / "js9.min.js"
    if not js9_path.exists():
        pytest.skip(f"JS9 not installed locally (built into the image at build time): {js9_path}")

    response = client.get("/static/js9/js9.min.js")

    assert response.status_code == 200
    assert "javascript" in _content_type(response)
    assert response.headers.get("Cache-Control") == "no-cache"
    assert response.headers.get("ETag")
    assert response.headers.get("Last-Modified")


# --------------------------------------------------------------------------------------------
# 2. Trivially-ours routes.
# --------------------------------------------------------------------------------------------


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert "text/plain" in _content_type(response)


def test_favicon_bytes_match_the_logo_file(client):
    """The favicon route (`ztf_viewer/pages/favicon.py`) just sends our own small logo file, so
    pinning the exact bytes is cheap and meaningful -- unlike the figure/CSV routes, this is not
    third-party payload.
    """
    response = client.get("/favicon.ico")

    assert response.status_code == 200
    assert "image/svg+xml" in _content_type(response)

    logo_path = _PACKAGE_ROOT / "static" / "img" / "logo.svg"
    assert _body(response) == logo_path.read_bytes()


def test_index(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in _content_type(response)
    # Not a full-HTML snapshot (Dash's index churns on every Dash upgrade); just confirm it's
    # actually the SPA shell and not, say, an empty error page.
    assert b'<div id="react-entry-point"' in _body(response)


# --------------------------------------------------------------------------------------------
# 3. Page routes that need no object lookup -- routed client-side by Dash, so the initial GET is
#    always just the same index shell as "/" above; no network call happens on this path.
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/login", "/tags", "/anomalies"])
def test_page_route_status_and_content_type(client, path):
    response = client.get(path)

    assert response.status_code == 200
    assert "text/html" in _content_type(response)


# --------------------------------------------------------------------------------------------
# 4. CSV endpoints -- pin the header row, column set and Content-Disposition filename that
#    `ztf_viewer/pages/lc_csv.py` authors. Never byte-compare the data rows -- those are the
#    service's numbers, not ours.
# --------------------------------------------------------------------------------------------


def test_specific_csv_routes_are_registered_before_the_generic_one(dash_app):
    """`/{dr}/csv/{oid}` has an int-typed `oid`, so `dr="panstarrs"`/`dr="gaia"` plus a numeric
    id would satisfy it too. Starlette matches routes in registration order and stops at the
    first match, so if the generic route were registered first it would silently shadow these
    two -- no network needed, this is purely about which handler a path resolves to.
    """
    from fastapi.routing import Match

    def _first_match(path):
        scope = {"type": "http", "method": "GET", "path": path}
        for route in dash_app.server.router.routes:
            match, _ = route.matches(scope)
            if match == Match.FULL:
                return route
        return None

    panstarrs_route = _first_match("/panstarrs/csv/12345")
    assert panstarrs_route is not None
    assert panstarrs_route.endpoint.__name__ == "response_panstarrs_csv"

    gaia_route = _first_match("/gaia/csv/12345")
    assert gaia_route is not None
    assert gaia_route.endpoint.__name__ == "response_gaia_csv"


@pytest.mark.network
def test_csv_dr_oid(client):
    response = client.get(f"/{_DR}/csv/{_OID}")

    assert response.status_code == 200
    assert "text/csv" in _content_type(response)
    assert response.headers.get("Content-Disposition") == f"attachment; filename={_OID}.csv"

    header_line = _body(response).split(b"\n", 1)[0].decode()
    assert header_line == "oid,filter,mjd,mag,magerr,clrcoeff,ref,ref_err"


@pytest.mark.network
def test_csv_antares(client):
    """Exercises the shared `_lc_to_csv_response` helper also used by the Pan-STARRS and Gaia CSV
    routes (left out of this file -- see the module docstring).
    """
    response = client.get(f"/antares/csv/{_ANTARES_LOCUS_ID}")

    assert response.status_code == 200
    assert "text/csv" in _content_type(response)
    assert response.headers.get("Content-Disposition") == f"attachment; filename=antares_{_ANTARES_LOCUS_ID}.csv"

    header_line = _body(response).split(b"\n", 1)[0].decode()
    assert header_line == "oid,mjd,mag,magerr,filter"


# --------------------------------------------------------------------------------------------
# 5. Figure endpoints -- magic bytes, mimetype, non-trivial size. Never byte-compare PNG/PDF:
#    matplotlib/LaTeX output is not reproducible across versions.
# --------------------------------------------------------------------------------------------

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_PDF_MAGIC = b"%PDF-"
_MIN_FIGURE_BYTES = 10_000  # a blank/broken figure is nowhere near this size


@pytest.mark.network
def test_figure_png(client):
    response = client.get(f"/{_DR}/figure/{_OID}")

    assert response.status_code == 200
    assert _content_type(response) == "image/png"
    assert response.headers.get("Content-Disposition") == f"attachment; filename={_OID}.png"
    body = _body(response)
    assert body.startswith(_PNG_MAGIC)
    assert len(body) > _MIN_FIGURE_BYTES


@pytest.mark.network
def test_figure_pdf(client):
    texsystem = _pgf_texsystem()
    if shutil.which(texsystem) is None:
        pytest.skip(f"LaTeX ({texsystem}) is not available locally; PDF rendering shells out to it")

    response = client.get(f"/{_DR}/figure/{_OID}?format=pdf")

    assert response.status_code == 200
    assert _content_type(response) == "application/pdf"
    assert response.headers.get("Content-Disposition") == f"attachment; filename={_OID}.pdf"
    body = _body(response)
    assert body.startswith(_PDF_MAGIC)
    assert len(body) > _MIN_FIGURE_BYTES


@pytest.mark.network
def test_figure_folded(client):
    response = client.get(f"/{_DR}/figure/{_OID}/folded/1.5")

    assert response.status_code == 200
    assert _content_type(response) == "image/png"
    body = _body(response)
    assert body.startswith(_PNG_MAGIC)
    assert len(body) > _MIN_FIGURE_BYTES


def _pgf_texsystem():
    import matplotlib

    return matplotlib.rcParams.get("pgf.texsystem", "xelatex")

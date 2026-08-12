"""pytest plugin wiring the fixture layer into the suite.

Three modes:

``pytest``  (default)
    Sockets are blocked (``--disable-socket --allow-unix-socket`` from ``addopts``),
    tests marked ``live`` are deselected (``-m "not live"``), and every ``requests``
    call is served from ``tests/fixtures/http``.  A request with no recorded fixture
    raises :class:`~tests.httpfixtures.store.FixtureNotFound`.

``pytest -m live``
    Only the live tests run, with real sockets and no interception.  This is the
    upstream-drift detector.

``pytest -m live --record-http``
    Same, but every exchange is written to the fixture store.  This is how fixtures
    are (re-)recorded; see ``tests/httpfixtures/README.md``.

Interception happens in ``pytest_runtest_setup`` rather than in an autouse fixture, so
that HTTP performed by *module*- or *session*-scoped fixtures (e.g. the PanSTARRS
``stack_table``) is covered too — higher-scoped fixtures are set up before
function-scoped ones.
"""

from __future__ import annotations

from io import BytesIO
from urllib.error import HTTPError

import pytest
from requests.adapters import HTTPAdapter

from tests.httpfixtures.requests_adapter import RecordingAdapter, ReplayAdapter
from tests.httpfixtures.store import default_store

_ADAPTER_KEY = pytest.StashKey()
_PATCH_KEY = pytest.StashKey()
_astroquery_patch = pytest.MonkeyPatch()


def pytest_addoption(parser):
    parser.addoption(
        "--record-http",
        action="store_true",
        default=False,
        help="Perform real HTTP requests and (re-)record them into tests/fixtures/http. "
        "Use together with -m live. Implies real sockets.",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live: test talks to a real upstream service. Deselected by default; run with -m live.",
    )

    # astroquery keeps its own on-disk response cache in ~/.astropy/cache. It short-circuits
    # requests before they reach any adapter, which would make recordings incomplete and
    # replays pass for the wrong reason (and only on a machine with a warm cache).
    # Clearing the global flag is not enough: several services (astroquery.imcce, which
    # backs SkybotQuery) hardcode `cache=True` per call, so force every lookup to miss.
    from astroquery.query import AstroQuery, cache_conf

    _astroquery_patch.setattr(cache_conf, "cache_active", False)
    _astroquery_patch.setattr(AstroQuery, "from_cache", lambda self, *args, **kwargs: False)


def pytest_unconfigure(config):
    _astroquery_patch.undo()


def pytest_collection_modifyitems(config, items):
    """Adjust the socket blocker per item."""
    recording = config.getoption("--record-http")
    for item in items:
        if recording or item.get_closest_marker("live"):
            item.add_marker(pytest.mark.enable_socket)
        elif "redisdb" in getattr(item, "fixturenames", ()):
            # pytest-redis spawns a server and talks to it; keep the loopback open for
            # those tests only, so they stay honest about the outside world.
            item.add_marker(pytest.mark.allow_hosts(["127.0.0.1", "::1"]))


def _make_adapter(item):
    """The adapter for this item, or ``None`` when it should reach the real network."""
    if item.config.getoption("--record-http"):
        return RecordingAdapter(default_store)
    if item.get_closest_marker("live"):
        return None
    return ReplayAdapter(default_store)


def pytest_runtest_setup(item):
    adapter = _make_adapter(item)
    item.stash[_ADAPTER_KEY] = adapter
    if adapter is None:
        return

    monkeypatch = pytest.MonkeyPatch()
    item.stash[_PATCH_KEY] = monkeypatch

    # The app constructs its requests.Session objects itself, in module-level singletons
    # and inside third-party clients (antares_client, alerce, astroquery), so there is
    # nothing to mount an adapter on: patching HTTPAdapter.send is the only interception
    # point that covers all of them at once.
    def send(self, request, **kwargs):
        return adapter.send(request, **kwargs)

    monkeypatch.setattr(HTTPAdapter, "send", send)
    _patch_astropy_fits(monkeypatch)
    _patch_http_client(monkeypatch)


def pytest_runtest_teardown(item, nextitem):
    monkeypatch = item.stash.get(_PATCH_KEY, None)
    if monkeypatch is not None:
        monkeypatch.undo()
        del item.stash[_PATCH_KEY]


def _patch_astropy_fits(monkeypatch):
    """Route ``astropy.io.fits.open(<url>)`` through the same fixture store.

    ``ztf_viewer.catalogs.ztf_ref`` downloads its reference catalogue with
    ``fits.open(url)``, which goes through ``urllib``/``astropy.utils.data`` rather than
    ``requests`` and is therefore invisible to the adapter above.  Re-issuing it as a
    ``requests`` GET puts it back on the recorded path in both modes, and preserves
    ``ztf_ref``'s ``except HTTPError -> NotFound`` behaviour.
    """
    import requests
    from astropy.io import fits

    original_open = fits.open

    def open_(name, *args, **kwargs):
        if isinstance(name, str) and name.startswith(("http://", "https://")):
            response = requests.get(name, timeout=60)
            if response.status_code != 200:
                raise HTTPError(name, response.status_code, response.reason, {}, None)
            return original_open(BytesIO(response.content), *args, **kwargs)
        return original_open(name, *args, **kwargs)

    monkeypatch.setattr(fits, "open", open_)


def _patch_http_client(monkeypatch):
    """Make ``http.client`` connections fail like an unreachable network.

    ``astroquery``'s TAP layer (``astroquery.utils.tap.conn.TapConn``) speaks
    ``http.client`` directly, bypassing ``requests`` — and ``astroquery.gaia`` issues
    such a call *at import time* (``Gaia = GaiaClass()`` -> ``get_status_messages()``,
    which ``ztf_viewer.catalogs.conesearch`` pulls in), so it happens inside whichever
    test imports the catalogs first.

    pytest-socket would raise ``SocketBlockedError`` (a ``RuntimeError``) there, which
    astroquery's ``except OSError`` cannot catch, so the import explodes in a way it
    never would in production.  Raising ``OSError`` instead reproduces exactly what a
    sandboxed CI box looks like to the library: the network is simply down.
    """
    import http.client

    def blocked_connect(self):
        raise OSError(
            f"Blocked http.client connection to {self.host}:{self.port} — "
            "the offline test suite serves HTTP from tests/fixtures/http"
        )

    monkeypatch.setattr(http.client.HTTPConnection, "connect", blocked_connect)
    monkeypatch.setattr(http.client.HTTPSConnection, "connect", blocked_connect)


@pytest.fixture
def http_adapter(request):
    """The replay/recording adapter installed for the current test (``None`` if live)."""
    return request.node.stash.get(_ADAPTER_KEY, None)


@pytest.fixture
def fixture_store():
    """The shared :class:`FixtureStore` (handy for adapter-level tests)."""
    return default_store

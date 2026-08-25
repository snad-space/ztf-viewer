"""The WS callback transport is enabled with an explicit origin allowlist and a heartbeat pinned
under the deployed proxy's live 60s read-timeout default; HTTP-transport callbacks still work.
"""

from dash import Input, Output, html
from fastapi.testclient import TestClient

from tests.conftest import reset_shared_process_pool, reset_shared_thread_pool
from ztf_viewer import config
from ztf_viewer.app import app
from ztf_viewer.config import WEBSOCKET_ALLOWED_ORIGINS, WEBSOCKET_HEARTBEAT_INTERVAL_MS

# nginx's compiled default; the deployed proxy has no proxy_read_timeout override live anywhere,
# so this is the real ceiling a heartbeat must stay under.
LIVE_PROXY_READ_TIMEOUT_MS = 60_000


def test_websocket_transport_is_enabled_with_explicit_origins():
    """The handler rejects every cross-origin connection without an explicit allowlist."""
    assert app._websocket_allowed_origins == WEBSOCKET_ALLOWED_ORIGINS
    assert len(WEBSOCKET_ALLOWED_ORIGINS) > 0
    assert all(isinstance(origin, str) and origin for origin in WEBSOCKET_ALLOWED_ORIGINS)


def test_heartbeat_interval_is_bounded_below_the_live_proxy_ceiling():
    """This must keep failing if the heartbeat is ever raised past the live proxy ceiling --
    that failure mode is silent in production, not something CI would otherwise catch."""
    assert app._websocket_heartbeat_interval == WEBSOCKET_HEARTBEAT_INTERVAL_MS
    assert WEBSOCKET_HEARTBEAT_INTERVAL_MS < LIVE_PROXY_READ_TIMEOUT_MS
    # Real margin, not just "technically under": at least a 2x safety factor.
    assert WEBSOCKET_HEARTBEAT_INTERVAL_MS <= LIVE_PROXY_READ_TIMEOUT_MS / 2


def test_at_least_one_callback_opted_into_websocket_transport():
    """Proves the transport is actually reachable, not just configured and unused."""
    config.CACHE_TYPE = "memory"
    config.UNAVAILABLE_CATALOGS_CACHE_TYPE = "memory"

    # Must import after the config assignment above: unavailable_catalogs binds its backend from
    # CACHE_TYPE at import time, and this may be the first import of __main__ in the session.
    import ztf_viewer.__main__ as main_module

    opted_in = [callback_id for callback_id, entry in main_module.app.callback_map.items() if entry.get("websocket")]
    assert opted_in == ["skybot.children"]


def test_http_fallback_still_works_for_a_non_websocket_callback():
    """A callback without `websocket=True` still dispatches over the plain HTTP POST path."""

    def echo(value):
        return f"echoed: {value}"

    app.callback(Output("ws-fallback-target", "children"), [Input("ws-fallback-source", "value")])(echo)

    original = app._layout, app._layout_is_function
    app.layout = html.Div(
        [
            html.Div(id="ws-fallback-target"),
            html.Div(id="ws-fallback-source"),
        ]
    )
    reset_shared_thread_pool()
    reset_shared_process_pool()
    try:
        with TestClient(app.server) as client:
            response = client.post(
                "/_dash-update-component",
                json={
                    "output": "ws-fallback-target.children",
                    "outputs": {"id": "ws-fallback-target", "property": "children"},
                    "inputs": [{"id": "ws-fallback-source", "property": "value", "value": "hi"}],
                    "state": [],
                    "changedPropIds": ["ws-fallback-source.value"],
                },
            )
    finally:
        app._layout, app._layout_is_function = original

    assert response.status_code == 200
    assert response.json()["response"]["ws-fallback-target"]["children"] == "echoed: hi"

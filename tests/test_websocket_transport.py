"""The WS callback transport is enabled: same-origin connections work via dash's own same-Host
fallback, cross-origin ones are still rejected, and the heartbeat is pinned under the deployed
proxy's live 60s read-timeout default. No callback currently opts in, and HTTP-transport
callbacks still work.
"""

import pytest
from dash import Input, Output, html
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from tests.conftest import reset_shared_process_pool, reset_shared_thread_pool
from ztf_viewer import config
from ztf_viewer.app import app
from ztf_viewer.config import WEBSOCKET_HEARTBEAT_INTERVAL_MS

# nginx's compiled default; the deployed proxy has no proxy_read_timeout override live anywhere,
# so this is the real ceiling a heartbeat must stay under.
LIVE_PROXY_READ_TIMEOUT_MS = 60_000


def test_websocket_origin_check_allows_same_origin_and_rejects_cross_origin():
    """The security-relevant behavior: dash's same-Host fallback (not the allowlist, which
    defaults empty) is what accepts ordinary same-origin connections; a genuine cross-origin
    one must still be rejected at the handshake."""
    original_allowed_origins = app._websocket_allowed_origins
    original_layout = app._layout, app._layout_is_function
    app._websocket_allowed_origins = []
    app.layout = html.Div("x")
    reset_shared_thread_pool()
    reset_shared_process_pool()
    try:
        with TestClient(app.server) as client:
            with client.websocket_connect("/_dash-ws-callback", headers={"Origin": "http://testserver"}):
                pass  # same-origin: connects without being on the allowlist

            with (
                pytest.raises(WebSocketDisconnect),
                client.websocket_connect("/_dash-ws-callback", headers={"Origin": "https://evil.example.com"}),
            ):
                pass  # cross-origin, not on the allowlist: rejected
    finally:
        app._websocket_allowed_origins = original_allowed_origins
        app._layout, app._layout_is_function = original_layout


def test_heartbeat_interval_is_bounded_below_the_live_proxy_ceiling():
    """This must keep failing if the heartbeat is ever raised past the live proxy ceiling --
    that failure mode is silent in production, not something CI would otherwise catch."""
    assert app._websocket_heartbeat_interval == WEBSOCKET_HEARTBEAT_INTERVAL_MS
    assert WEBSOCKET_HEARTBEAT_INTERVAL_MS < LIVE_PROXY_READ_TIMEOUT_MS
    # Real margin, not just "technically under": at least a 2x safety factor.
    assert WEBSOCKET_HEARTBEAT_INTERVAL_MS <= LIVE_PROXY_READ_TIMEOUT_MS / 2


def test_only_get_summary_opts_into_websocket_transport():
    """A `websocket=True` opt-in must be justified by actually using streaming (set_props,
    progressive delivery); plain request/response callbacks gain nothing from it while losing
    the HTTP fallback. `get_summary` is the callback the plan sanctions -- it has no Output and
    streams progressively via `set_props` (see `tests/pages/test_viewer.py`). If this fails,
    either justify a new opt-in with real streaming and update this test, or drop
    `websocket=True` from whatever callback grew it."""
    config.CACHE_TYPE = "memory"
    config.UNAVAILABLE_CATALOGS_CACHE_TYPE = "memory"

    # Must import after the config assignment above: unavailable_catalogs binds its backend from
    # CACHE_TYPE at import time, and this may be the first import of __main__ in the session.
    import ztf_viewer.__main__ as main_module

    opted_in = [entry for entry in main_module.app.callback_map.values() if entry.get("websocket")]
    assert len(opted_in) == 1
    entry = opted_in[0]
    assert entry.get("no_output")
    assert [str(inp) for inp in entry["raw_inputs"]] == [
        "oid.children",
        "dr.children",
        "different_filter_neighbours.children",
        "different_field_neighbours.children",
        '{"index":["ALL"],"type":"search-radius"}.id',
        '{"index":["ALL"],"type":"search-radius"}.value',
    ]


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

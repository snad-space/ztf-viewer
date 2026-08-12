"""The point of this branch: one fixture store, two clients, identical results.

If these fail after the ``requests`` -> ``httpx`` swap, the swap changed behaviour.
"""

import httpx
import pytest
import requests

from tests.httpfixtures import (
    FixtureNotFound,
    ReplayAdapter,
    build_httpx_response,
    build_requests_response,
    default_store,
    replay_transport,
)
from tests.httpfixtures.store import normalize_url, request_key


def _recorded():
    responses = default_store.all_responses()
    if not responses:
        # Empty store: keep collection working so `-m live --record-http` can bootstrap it.
        return [pytest.param(None, marks=pytest.mark.skip(reason="no fixtures recorded yet"))]
    return responses


def _one_get():
    return next(r for r in default_store.all_responses() if r.method == "GET")


def test_request_key_identity():
    url = "https://example.org/a?b=1"
    # query order does not matter: requests may reorder params
    assert request_key("GET", "https://example.org/a?x=1&y=2") == request_key("GET", "https://example.org/a?y=2&x=1")
    # method and body do
    assert request_key("GET", url) != request_key("POST", url)
    assert request_key("POST", url) != request_key("POST", url, b"payload")


def test_normalize_url_drops_default_port_and_fragment():
    assert normalize_url("HTTPS://Example.ORG:443/p?b=2&a=1#frag") == "https://example.org/p?a=1&b=2"


@pytest.mark.parametrize("recorded", _recorded(), ids=lambda r: f"{r.method} {r.url}"[:80] if r else "empty")
def test_both_clients_replay_identical_bytes(recorded):
    """Every stored exchange must come back byte-identical through both clients."""
    via_requests = build_requests_response(recorded)
    via_httpx = build_httpx_response(recorded)

    assert via_requests.status_code == via_httpx.status_code == recorded.status_code
    assert via_requests.content == via_httpx.content == recorded.body
    assert via_requests.headers.get("content-type") == via_httpx.headers.get("content-type")


def test_requests_session_with_mounted_adapter():
    """The adapter also works the ordinary way: mounted on a single Session."""
    recorded = _one_get()
    session = requests.Session()
    session.mount("https://", ReplayAdapter())
    session.mount("http://", ReplayAdapter())
    response = session.get(recorded.url)
    assert response.status_code == recorded.status_code
    assert response.content == recorded.body


def test_httpx_client_with_mock_transport():
    recorded = _one_get()
    with httpx.Client(transport=replay_transport()) as client:
        response = client.get(recorded.url)
    assert response.status_code == recorded.status_code
    assert response.content == recorded.body


def test_async_httpx_client_with_mock_transport():
    """``MockTransport`` serves ``AsyncClient`` too — the aio-httpx stack's entry point."""
    import asyncio

    recorded = _one_get()

    async def go():
        async with httpx.AsyncClient(transport=replay_transport()) as client:
            return await client.get(recorded.url)

    response = asyncio.run(go())
    assert response.status_code == recorded.status_code
    assert response.content == recorded.body


def test_unrecorded_request_raises_with_a_useful_message():
    session = requests.Session()
    session.mount("https://", ReplayAdapter())
    with pytest.raises(FixtureNotFound, match="--record-http"):
        session.get("https://not.recorded.example/nope")


def test_replay_is_installed_by_default(http_adapter):
    assert isinstance(http_adapter, ReplayAdapter)

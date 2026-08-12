"""``httpx`` side of the fixture layer — the same fixtures, a different client.

Nothing here records: recording happens once, through ``requests`` (see
``requests_adapter.RecordingAdapter``).  That asymmetry is the point of the branch —
when the app moves from ``requests`` to ``httpx`` the fixtures do not move with it,
so before/after behaviour stays comparable.
"""

from __future__ import annotations

import httpx

from tests.httpfixtures.store import FixtureStore, RecordedResponse, default_store


def build_httpx_response(recorded: RecordedResponse, request: httpx.Request | None = None) -> httpx.Response:
    """Turn a stored exchange into a real :class:`httpx.Response`."""
    return httpx.Response(
        status_code=recorded.status_code,
        headers=recorded.replay_headers(),
        content=recorded.body,
        request=request or httpx.Request(recorded.method, recorded.url),
    )


def replay_handler(store: FixtureStore = default_store):
    """Return a ``MockTransport`` handler bound to ``store``."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content or None
        recorded = store.lookup(request.method, str(request.url), body)
        return build_httpx_response(recorded, request)

    return handler


def replay_transport(store: FixtureStore = default_store) -> httpx.MockTransport:
    """A sync+async transport that serves every request from ``store``.

    ``httpx.MockTransport`` implements both ``handle_request`` and
    ``handle_async_request``, so the very same object works for ``httpx.Client`` and
    ``httpx.AsyncClient``::

        client = httpx.AsyncClient(transport=replay_transport())
    """
    return httpx.MockTransport(replay_handler(store))

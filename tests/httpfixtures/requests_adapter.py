"""``requests`` side of the fixture layer: a replay adapter and a recording adapter.

Both are :class:`requests.adapters.HTTPAdapter` subclasses, so they can either be
mounted on a single ``Session`` or installed process-wide by patching
``HTTPAdapter.send`` (which is what the pytest plugin does — the app builds its
``requests.Session`` objects itself, deep inside module-level singletons and inside
third-party clients such as ``antares_client``/``alerce``/``astroquery``, so there is
no session to hand an adapter to).
"""

from __future__ import annotations

from io import BytesIO

import requests
from requests.adapters import HTTPAdapter
from urllib3 import HTTPResponse as Urllib3Response

from tests.httpfixtures.store import FixtureStore, RecordedResponse, default_store

#: Only used for its ``build_response``, which fills in encoding/cookies/url exactly
#: the way a real ``requests`` transfer would.
_response_builder = HTTPAdapter()

#: Transfer-encoding headers that describe the wire bytes we have already decoded.
_RAW_ONLY_HEADERS = frozenset({"content-encoding", "transfer-encoding", "content-length"})


def _request_body_bytes(request: requests.PreparedRequest) -> bytes | None:
    body = request.body
    if body is None:
        return None
    if isinstance(body, str):
        return body.encode()
    if isinstance(body, bytes):
        return body
    # Generators / file objects: not supported for matching, and never used by this app.
    raise TypeError(f"Cannot record/replay a streamed request body of type {type(body)!r}")


def build_requests_response(
    recorded: RecordedResponse,
    request: requests.PreparedRequest | None = None,
) -> requests.Response:
    """Turn a stored exchange into a real :class:`requests.Response`."""
    raw = Urllib3Response(
        body=BytesIO(recorded.body),
        headers=recorded.replay_headers(),
        status=recorded.status_code,
        reason=recorded.reason,
        preload_content=False,
        decode_content=False,
        original_response=None,
    )
    if request is None:
        request = requests.Request(method=recorded.method, url=recorded.url).prepare()
    return _response_builder.build_response(request, raw)


def _rewind(response: requests.Response, body: bytes) -> requests.Response:
    """Give ``response`` a fresh, re-readable ``raw`` after we consumed it.

    Recording has to read the whole body to store it, which exhausts ``response.raw``.
    Consumers that read the raw stream instead of ``.content`` — ``pyvo`` (via
    ``astroquery.simbad``) does exactly this — would otherwise see an empty document.
    """
    headers = {name: value for name, value in response.headers.items() if name.lower() not in _RAW_ONLY_HEADERS}
    headers["Content-Length"] = str(len(body))
    response.raw = Urllib3Response(
        body=BytesIO(body),
        headers=headers,
        status=response.status_code,
        reason=response.reason,
        preload_content=False,
        decode_content=False,
        original_response=None,
    )
    response._content = body
    response._content_consumed = True
    return response


class ReplayAdapter(HTTPAdapter):
    """Serves every request from the fixture store; raises ``FixtureNotFound`` on a miss."""

    def __init__(self, store: FixtureStore = default_store, **kwargs):
        self.store = store
        super().__init__(**kwargs)

    def send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
        recorded = self.store.lookup(request.method, request.url, _request_body_bytes(request))
        return build_requests_response(recorded, request)


class RecordingAdapter(HTTPAdapter):
    """Performs the real request and writes the exchange to the fixture store."""

    def __init__(self, store: FixtureStore = default_store, **kwargs):
        self.store = store
        self.recorded_paths: list = []
        # Captured up front: the plugin installs this adapter by patching
        # HTTPAdapter.send process-wide, so ``super().send`` would recurse.
        self._real_send = HTTPAdapter.send
        super().__init__(**kwargs)

    def send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
        response = self._real_send(
            self, request, stream=stream, timeout=timeout, verify=verify, cert=cert, proxies=proxies
        )
        body = response.content  # forces the full download, even for stream=True
        path = self.store.save(
            method=request.method,
            url=request.url,
            request_body=_request_body_bytes(request),
            status_code=response.status_code,
            reason=response.reason or "",
            headers=dict(response.headers),
            body=body,
        )
        self.recorded_paths.append(path)
        return _rewind(response, body)

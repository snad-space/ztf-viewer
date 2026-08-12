"""Client-agnostic HTTP fixtures: record once, replay through ``requests`` *and* ``httpx``.

See ``README.md`` in this directory for the recording workflow.
"""

from tests.httpfixtures.httpx_adapter import build_httpx_response, replay_handler, replay_transport
from tests.httpfixtures.requests_adapter import ReplayAdapter, RecordingAdapter, build_requests_response
from tests.httpfixtures.store import (
    FIXTURE_ROOT,
    FixtureNotFound,
    FixtureStore,
    RecordedResponse,
    default_store,
    request_key,
)

__all__ = [
    "FIXTURE_ROOT",
    "FixtureNotFound",
    "FixtureStore",
    "RecordedResponse",
    "RecordingAdapter",
    "ReplayAdapter",
    "build_httpx_response",
    "build_requests_response",
    "default_store",
    "replay_handler",
    "replay_transport",
    "request_key",
]

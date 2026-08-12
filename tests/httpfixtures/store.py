"""On-disk store of recorded HTTP exchanges.

The format is deliberately client-agnostic: a recorded exchange knows nothing about
``requests`` or ``httpx``, it is just *method + URL + request body hash* mapped to
*status + headers + body*.  Both replay adapters (``requests_adapter``,
``httpx_adapter``) read the very same files, which is what lets the async migration
compare before/after behaviour without re-recording anything.

Layout::

    tests/fixtures/http/<host>/<METHOD>-<path-slug>-<key>.json

One JSON document per exchange::

    {
      "key": "3f1c...",              # 16 hex chars, derived from the request (see request_key)
      "recorded_at": "2026-08-12T...",
      "request": {"method": "GET", "url": "https://...", "body_sha256": null},
      "response": {"status_code": 200, "reason": "OK", "headers": {...},
                   "body_text": "..."}    # or "body_base64" for non-UTF-8 payloads
    }

Bodies are stored verbatim (never re-serialized or pretty-printed) so byte-exact
golden tests downstream stay meaningful.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "fixtures" / "http"

#: Response headers that describe the wire encoding of the *recorded* transfer and
#: would be wrong (or actively harmful) on replay, plus cookies we do not want on disk.
_SKIP_RESPONSE_HEADERS = frozenset(
    {
        "content-encoding",
        "transfer-encoding",
        "content-length",
        "connection",
        "keep-alive",
        "set-cookie",
        "date",
    }
)

_DEFAULT_PORTS = {"http": 80, "https": 443}

_SLUG_RE = re.compile(r"[^A-Za-z0-9]+")

#: Bodies larger than this are stored as a raw ``.body`` sidecar next to the JSON.
MAX_INLINE_BODY = 512 * 1024


class FixtureNotFound(LookupError):
    """Raised on replay when no recorded exchange matches the outgoing request."""


def normalize_url(url: str) -> str:
    """Canonical URL used for fixture lookup.

    Lower-cases scheme/host, drops the default port and any fragment, and sorts query
    parameters, so that a request built by hand and the same request built by
    ``requests``' parameter encoding hit the same fixture.
    """
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    port = parts.port
    netloc = host if port is None or port == _DEFAULT_PORTS.get(scheme) else f"{host}:{port}"
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return urlunsplit((scheme, netloc, parts.path, query, ""))


def body_sha256(body: bytes | None) -> str | None:
    if not body:
        return None
    return hashlib.sha256(body).hexdigest()


def _canonicalize_unordered_tokens(body: bytes) -> bytes:
    """Order-insensitive digest of a form-encoded body.

    ``astroquery.simbad`` assembles both its select list *and* its ``JOIN`` clauses from
    *sets*, so the identical query is serialized in a different order in every process
    (``PYTHONHASHSEED`` is random).  Byte-exact matching therefore can never find a
    fixture recorded by an earlier run.  Sorting the body's words makes the lookup key
    invariant under any such permutation while still telling genuinely different
    queries apart.  Only the key is affected — the stored request/response
    bytes are untouched.

    Punctuation is dropped before sorting: reordering the clauses also moves the commas
    and parentheses between words, so only the bare word multiset is stable.
    """
    return b" ".join(sorted(re.findall(rb"[A-Za-z0-9_.]+", body)))


#: ``(url regex, canonicalizer)`` applied to the request body before hashing.  Add an
#: entry here when an upstream client emits a body that is not byte-stable across runs.
BODY_CANONICALIZERS: list[tuple[re.Pattern, "object"]] = [
    (re.compile(r"^https://simbad\.[^/]+/simbad/sim-tap/sync$"), _canonicalize_unordered_tokens),
]


def canonicalize_body(url: str, body: bytes | None) -> bytes | None:
    if not body:
        return body
    for pattern, canonicalize in BODY_CANONICALIZERS:
        if pattern.match(normalize_url(url)):
            return canonicalize(body)
    return body


def request_key(method: str, url: str, body: bytes | None = None) -> str:
    """Stable 16-hex-char identity of a request."""
    key_body = canonicalize_body(url, body)
    material = "\n".join([method.upper(), normalize_url(url), body_sha256(key_body) or ""])
    return hashlib.sha256(material.encode()).hexdigest()[:16]


def _slug(text: str, max_len: int = 48) -> str:
    slug = _SLUG_RE.sub("-", text).strip("-").lower()
    return slug[:max_len] or "root"


@dataclass(frozen=True)
class RecordedResponse:
    """A replayable response, independent of any HTTP client library."""

    status_code: int
    reason: str
    headers: dict[str, str]
    body: bytes
    url: str
    method: str

    @property
    def content_type(self) -> str:
        for name, value in self.headers.items():
            if name.lower() == "content-type":
                return value
        return ""

    def replay_headers(self) -> dict[str, str]:
        """Stored headers plus a ``Content-Length`` matching the stored body."""
        headers = dict(self.headers)
        headers["Content-Length"] = str(len(self.body))
        return headers


class FixtureStore:
    """Reads and writes :class:`RecordedResponse` objects under ``root``."""

    def __init__(self, root: Path = FIXTURE_ROOT):
        self.root = Path(root)
        self._by_key: dict[str, RecordedResponse] | None = None

    # -- reading ---------------------------------------------------------------

    def _index(self) -> dict[str, RecordedResponse]:
        if self._by_key is None:
            self._by_key = {}
            for path in sorted(self.root.rglob("*.json")):
                doc = json.loads(path.read_text())
                self._by_key[doc["key"]] = _response_from_doc(doc, path)
        return self._by_key

    def __len__(self) -> int:
        return len(self._index())

    def all_responses(self) -> list[RecordedResponse]:
        return list(self._index().values())

    def lookup(self, method: str, url: str, body: bytes | None = None) -> RecordedResponse:
        key = request_key(method, url, body)
        try:
            return self._index()[key]
        except KeyError:
            raise FixtureNotFound(
                f"No recorded HTTP fixture for {method.upper()} {url}"
                f" (key {key}, body sha256 {body_sha256(body)}).\n"
                f"Fixture root: {self.root}\n"
                "Record it by adding/keeping a test marked @pytest.mark.live that makes this "
                "request and running:  pytest -m live --record-http"
            ) from None

    # -- writing ---------------------------------------------------------------

    def path_for(self, method: str, url: str, body: bytes | None = None) -> Path:
        parts = urlsplit(normalize_url(url))
        key = request_key(method, url, body)
        name = f"{method.upper()}-{_slug(parts.path)}-{key}.json"
        return self.root / (parts.hostname or "unknown-host") / name

    def save(
        self,
        *,
        method: str,
        url: str,
        request_body: bytes | None,
        status_code: int,
        reason: str,
        headers: dict[str, str],
        body: bytes,
    ) -> Path:
        clean_headers = {name: value for name, value in headers.items() if name.lower() not in _SKIP_RESPONSE_HEADERS}
        doc: dict = {
            "key": request_key(method, url, request_body),
            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "request": {
                "method": method.upper(),
                "url": normalize_url(url),
                "body_sha256": body_sha256(request_body),
            },
            "response": {
                "status_code": status_code,
                "reason": reason,
                "headers": clean_headers,
            },
        }
        path = self.path_for(method, url, request_body)
        path.parent.mkdir(parents=True, exist_ok=True)
        if len(body) > MAX_INLINE_BODY:
            # Big payloads (the ZTF reference-catalogue FITS, ~2.8 MB) go next to the
            # JSON as raw bytes: base64 would inflate them by a third and make the
            # fixture unreadable.
            sidecar = path.with_suffix(".body")
            sidecar.write_bytes(body)
            doc["response"]["body_file"] = sidecar.name
        else:
            try:
                doc["response"]["body_text"] = body.decode()
            except UnicodeDecodeError:
                doc["response"]["body_base64"] = base64.b64encode(body).decode("ascii")
        path.write_text(json.dumps(doc, indent=1, ensure_ascii=False, sort_keys=False) + "\n")
        self._by_key = None  # invalidate
        return path


def _response_from_doc(doc: dict, path: Path) -> RecordedResponse:
    resp = doc["response"]
    if "body_file" in resp:
        body = (path.parent / resp["body_file"]).read_bytes()
    elif "body_base64" in resp:
        body = base64.b64decode(resp["body_base64"])
    else:
        body = resp.get("body_text", "").encode()
    return RecordedResponse(
        status_code=resp["status_code"],
        reason=resp.get("reason", ""),
        headers=dict(resp.get("headers", {})),
        body=body,
        url=doc["request"]["url"],
        method=doc["request"]["method"],
    )


#: Default store, used by both adapters and by the pytest plugin.
default_store = FixtureStore()

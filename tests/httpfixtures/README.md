# HTTP fixtures

Recorded upstream responses, replayed through **both** `requests` (today) and `httpx`
(the async stack).  The fixtures are ours, not a client-specific cassette format, so
the `requests` → `httpx` migration does not require re-recording — which is what makes
before/after comparison possible.

## Running the suite

| command | sockets | HTTP |
| --- | --- | --- |
| `pytest` | blocked | replayed from `tests/fixtures/http` |
| `pytest -m live` | open | real upstreams (drift detector) |
| `pytest -m live --record-http` | open | real upstreams, **written to the fixture store** |

A request with no matching fixture raises `FixtureNotFound`, naming the URL and the
command to record it.

## Recording a new fixture

1. Write (or find) a test that makes the request, and mark it `@pytest.mark.live`.
   Live tests double as our upstream-drift detectors, so give it real assertions.
2. `pytest -m live --record-http -k your_test`
3. Write the offline twin in `tests/test_replayed_catalogs.py`. It runs by default.
4. Commit both the test and the new files under `tests/fixtures/http/`.

Re-recording everything is `rm -rf tests/fixtures/http && pytest -m live --record-http`.

## Format

`tests/fixtures/http/<host>/<METHOD>-<path-slug>-<key>.json`, one file per exchange:

```json
{
 "key": "c4b8b578c5b6e851",
 "recorded_at": "2026-08-12T12:00:00+00:00",
 "request": {"method": "GET", "url": "https://db.ztf.snad.space/...", "body_sha256": null},
 "response": {"status_code": 200, "reason": "OK", "headers": {...}, "body_text": "..."}
}
```

* `key` = `sha256(METHOD \n normalized-URL \n sha256(request body))[:16]`.  The URL is
  normalized (lower-case scheme/host, no default port, sorted query) so a hand-built URL
  and one assembled by `requests`' `params=` match the same fixture.
* Bodies are stored verbatim — never reformatted — so byte-exact goldens downstream stay
  meaningful.  Non-UTF-8 payloads use `body_base64`; anything over 512 KiB goes into a
  sibling `.body` file referenced by `body_file`.
* Response headers are stored minus `Content-Encoding`/`Transfer-Encoding`/
  `Content-Length` (the body is already decoded; `Content-Length` is recomputed on
  replay), and minus `Set-Cookie`/`Date`.  Request headers are **not** stored, which
  incidentally keeps credentials off disk.

## Using the adapters directly

```python
from tests.httpfixtures import ReplayAdapter, replay_transport

session = requests.Session()
session.mount("https://", ReplayAdapter())

client = httpx.AsyncClient(transport=replay_transport())   # MockTransport, sync or async
```

The pytest plugin (`tests/httpfixtures/plugin.py`) installs the `requests` side globally
by patching `HTTPAdapter.send`, because the app builds its sessions itself inside
module-level singletons and third-party clients (`antares_client`, `alerce`,
`astroquery`), leaving nothing to mount an adapter on.

## Things that do not go through `requests`

Two upstream paths bypass `requests` entirely and are handled specially by the plugin:

* `astropy.io.fits.open(url)` (`ztf_viewer/catalogs/ztf_ref.py`) — re-issued as a
  `requests` GET so it lands in the same store, preserving the `HTTPError → NotFound`
  behaviour.
* `astroquery`'s TAP layer (`astroquery.utils.tap.conn`) speaks `http.client` directly.
  Nothing replays it; connections are refused with an `OSError`, which is what those
  libraries expect from an unreachable network.  This matters because
  `import astroquery.gaia` runs `Gaia = GaiaClass()` → `get_status_messages()` **at import
  time**, and `ztf_viewer.catalogs.conesearch` imports it.

`astroquery`'s own on-disk cache (`~/.astropy/cache`) is force-disabled for the whole
session: it short-circuits requests before any adapter sees them, which makes recordings
incomplete and lets replays pass only on a machine with a warm cache.

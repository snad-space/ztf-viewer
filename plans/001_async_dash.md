# 001 — Porting the ZTF Viewer to async (Dash 4 FastAPI backend)

Status: in progress · foundations landed except the two optional test items; prep landed in full;
the async shell has landed in full (`aio-shim`, `aio-loop-registry`; `aio-pilots` dropped); **the
flip has landed** (#658–#661, merged as one stack) — the three post-flip chains are now unblocked
Baseline: `master` after `994874e`
Now running: FastAPI backend under uvicorn, one worker, one loop; Python 3.14

Note on names: branches and PRs drop the `aio-` prefix the plan uses (`aio-py314` shipped as
`python-3.14`, `aio-cache-core` as `cache-core`, and so on). The plan keeps the prefixed names
as identifiers; the Progress list records the real branch where they differ.

---

## Progress

Mark `[x]` when merged. Prod stays on the current build until the whole plan lands; what must
keep working throughout is `master.ztf.snad.space`. Every PR also gets `pr<N>.ztf.snad.space` —
smoke-check there before merging.

**Every PR in this plan is opened as a draft.** Author it, get CI green, write the description —
then leave it in draft. Konstantin reviews and marks it ready when it is right. Nothing here is
merged by its author, and "ready for review" is a reviewer's signal, not the author's.

**Foundations** — land these first
- [x] `aio-py314` — bump to Python 3.14 (image, pyproject, ruff/black, lock) — #625 `python-3.14`
- [x] ~~`aio-fixtures`~~ — **dropped.** Recorded/replayed upstream responses (#631,
      branch `http-fixtures`, kept but closed): replaying canned upstream bytes mostly re-tests
      our own parsers against blobs, and the third-party sync clients are not being ported to
      async at all (F9), so their recordings would never take part in a before/after comparison.
      Replaced by #632 `robust-upstream-tests`, which keeps the tests live but turns
      transport-level failures on `upstream`-marked tests into skips, so CI stops going red
      because Simbad is down. See the revised foundations section.
- [x] `aio-golden-http` — **re-scoped:** goldens over *our* outputs only, no upstream replay;
      partial coverage is fine — #634 `golden-http`
- [ ] `aio-golden-callbacks` — **re-scoped** the same way; likely a thin subset
- [x] `aio-cache-spec` — cache contract tests (keys, TTL, pickle round-trip) — **found five defects in
      today's cache, see F12** — #627 `cache-contract-tests`
- [ ] `aio-bench` — fan-out latency harness, records a baseline
- [~] `aio-invariants` — **deliberately cut down, not landed as specified** (#626). Only the two
      cache-decorator guards landed (`tests/test_cache_decorator_guards.py`); the rest were
      **reassigned to the PRs that establish each rule**, where they are plain passing assertions
      rather than `xfail`. See the revised foundations section. The investigation behind it
      **corrected the callback count, see F1a′**.
      - no `import flask` outside `web.py` → `aio-deflask`
      - every `callback_map` entry is a coroutine → `aio-shim`
      - the async-decorator guards → **dropped**: `aio-cache-async` makes `cache()` dispatch instead, so
        the choice a guard would police no longer exists

**Prep** — backend-neutral, on Flask
- [x] `aio-deflask` — `ctx.cookies` instead of `flask.request`; routes go through `web.py` — #633 `deflask`
- [x] `aio-cache-core` — key derivation + value codec, no backend — #628 `cache-core`
- [x] `aio-cache-sync` — reimplement sync `cache()`, drop `redis_lru` — #629 `cache-sync`
- [x] `aio-pytest-asyncio` — async test support — **moved ahead of `aio-cache-async`** — #636 `pytest-asyncio`
- [x] `aio-cache-async` — make `cache()` dispatch on sync vs async, one shared store — #637 `cache-async`
- [x] `aio-cache-flight` — single-flight dedupe — #638 `cache-flight`
- [x] `aio-ttlset` — async `unavailable_catalogs` — #644 `ttl-set-async`. Came with #645
      `redis-min-version`, which raised the floor to Redis 6.2 and pinned the server image —
      not in the plan, but a real prerequisite the port surfaced. It also **retired the
      import-time `info()` probe** in `RedisTTLSet.__init__`, so one of the two blocking-I/O-at-import
      sites `aio-loop-registry` was told to deal with is already gone; the `astroquery.gaia` one
      remains.

**Async shell** — last stack on Flask
- [x] `aio-shim` — every callback becomes a coroutine (registration-layer wrap); adds the
      callbacks-are-coroutines guard as a plain passing test — #647 `callback-shim`.
      **Landed without the bounded thread pool the section below specifies**: the wrapper runs
      the callback inline, on the thread that awaits it, exactly as before the shim existed. A
      pool needs a size and a size needs one configured home, and neither exists until
      `aio-uvicorn` introduces them together — so the offload moves there. Consequence: the
      pessimization the section warns about is not incurred on Flask, and F1's requirement is
      still met, since it is about *registration* kind, not about where the body runs.
      Follow-up #648 fixed a client-side `State` error on `/tags` for logged-out users.
- [x] `aio-loop-registry` — per-loop clients/pools/semaphores — #651 `loop-registry`. One
      `LoopRegistry`, keyed on the loop object itself rather than `id(loop)` (ids are recycled, so
      a new loop could inherit a dead loop's resource), replacing the four ad-hoc
      `WeakKeyDictionary` + `threading.Lock` copies that had grown in the cache and TTL-set paths.
      **Reclamation is not automatic for every resource**, contrary to what the PR first claimed: a
      connected `redis.asyncio` client references its own loop, so it pins its own weak key and the
      table grows one entry per Flask request loop. Follow-up #654 sweeps closed loops out —
      **when a new loop asks for a resource, not on every lookup**, so the common path stays a
      plain dict hit.
- [x] ~~`aio-pilots`~~ — **dropped** (#652, closed). Converting a callback to `async def` before
      its body has anything to await opts it out of the offload `aio-uvicorn` installs in the
      shim's wrapper — see F15. The mechanics it would have proved are already covered by
      `tests/test_callbacks_shim.py`.

**The flip** — merged as one stack, as specified
- [x] `aio-fastapi-app` — deps, `backend=`, mount `/static` — #658 `fastapi-app`. **No
      `DASH_BACKEND` env var was built**: review dropped it because `aio-starlette-web` kills the
      Flask path in `web.py` one PR later, so the var's only real user was CI on #658 in
      isolation. The backend is hardcoded `"fastapi"`. Consequence: the rollback paragraph below
      and `aio-cleanup`'s "remove the escape hatch" item are void — there is nothing to remove.
      The `/static` mount is a `StaticFiles` subclass that adds `Cache-Control: no-cache`, so the
      header improvement the `/static` design note left open was taken here after all. `httpx`
      stayed a test-only dependency; it becomes a runtime one in `aio-httpx`, where it is first
      imported.
- [x] `aio-starlette-web` — `web.py` to Starlette *(broke Flask from here)* — #659
      `starlette-web`. Responses import from `fastapi.responses`, not `starlette.*`: `starlette`
      is transitive and undeclared, `fastapi` is what `pyproject.toml` names, and the classes are
      the same objects. `starlette.routing.Route` is the one import with no `fastapi` re-export.
- [x] `aio-routes` — port the six routes — #661 `starlette-routes`. Discharged F13: the ambient
      `request` re-export is gone and the four call sites take `request: Request`. `flask` left
      the direct dependency list and the import guard was widened to the whole package. Two
      things the plan did not anticipate, both now guarded by tests:
      **route registration order is load-bearing** — `/{dr}/csv/{oid}` takes an int `oid`, so it
      matches `/panstarrs/csv/12345` too, and Starlette stops at the first match where Flask
      picked the most specific rule; the three specific CSV routes must stay registered ahead of
      the generic one. And **`health_endpoint` must not carry a leading slash** — Dash
      concatenates it onto the route prefix, so `"/health"` registered as `"//health"` and fell
      through to the catch-all. The int/float folded-period pair did collapse to one `float`
      route, as the section allowed.
- [x] `aio-uvicorn` — entrypoint: Dockerfile **and `.ci/docker-compose.yml.tmpl`** (F11) — #660
      `uvicorn-entrypoint`. Both entrypoints now run the identical uvicorn command, so the
      dev/prod divergence F11 flagged is gone rather than patched. The shim's wrapper became a
      real thread offload here, as specified. **The two pools are sized independently at
      `THREAD_POOL_SIZE` each, not jointly**: anyio's limiter runs sync route handlers on its own
      worker threads, not on asyncio's default executor, so the default of 16 is up to 32
      blocking threads per process — the number `aio-offload-threads` has to size against.

**Async I/O** — the payoff
- [ ] `aio-httpx` — shared async client, `asyncio.timeout`
- [ ] `aio-snad-apis` — ztf_dr, features, model_fit, akb, ztf_ref
- [ ] `aio-conesearch` — cone-search base + per-catalog
- [ ] `aio-offload-threads` — astroquery / alerce / antares behind bounded semaphores
- [ ] `aio-gather` — concurrent fan-out; `aio-bench` becomes an assertion

**WebSocket**
- [ ] `aio-ws` — enable transport (verify deployed proxy config first)
- [ ] `aio-stream` — progressive rendering via `set_props`

**Process pool**
- [ ] `aio-procpool` — pool lifecycle, spawn-safe
- [ ] `aio-figures` — matplotlib rendering off-loop, PNG *and* PDF
- [ ] `aio-profile` — measure the rest; pool only what earns it

**Cleanup**
- [ ] `aio-cleanup` — drop `requests` and the sync `timeout()`; update docs

**Out-of-band** — deployment side, not PRs in this repo
- [ ] Verify which proxy config is live on the deployment host
- [ ] Per-vhost timeouts for the viewer
- [ ] Fix the no-op `client_max_body_size` patch

---

## Why

The viewer is I/O-bound almost end to end. A single object page fans out to ~20 external
cone-search catalogs, the ZTF DR light-curve API, the features API, the model-fit API, AKB,
Vizier, Simbad, Skybot, and the FITS reference proxy — all through blocking `requests` /
`astroquery` calls, executed **sequentially** inside Dash callbacks
(`ztf_viewer/pages/viewer.py:1379` `get_summary` loops over every catalog; each catalog also
gets its own `set_table` callback, `ztf_viewer/pages/viewer.py:2018`).

Today concurrency comes only from `gunicorn -w2 --threads=8` (`Dockerfile:73`) — 16 blocking
slots for the whole site. A handful of slow upstreams (Vizier and Simbad are regular
offenders) can starve the pool.

Dash 4.4 ships first-class ASGI backends (`dash/backends/_fastapi.py`), native `async def`
callbacks, and a WebSocket callback transport with `set_props` streaming. That unlocks:

- true concurrent fan-out (`asyncio.gather` over catalogs instead of a serial `for` loop),
- progressive rendering — each catalog table appears as it arrives instead of after the
  slowest one,
- far higher connection capacity per worker,
- a place to put genuinely CPU-heavy work (matplotlib + LaTeX PDF rendering) that doesn't
  fight with I/O for threads.

## Goals and non-goals

**Goals**

1. Run on the Dash FastAPI backend under uvicorn.
2. Move callback dispatch to the WebSocket transport where it buys us streaming UX.
3. Convert first-party HTTP calls to async (`httpx.AsyncClient`), with sequential fan-out
   replaced by `asyncio.gather`.
4. Offload CPU-heavy work (matplotlib/LaTeX figure rendering above all) to a process pool.
5. Keep the cache layer (Redis / in-memory) correct and non-blocking under async.

**Non-goals**

- No UI redesign, no new pages, no change to the public URL surface.
- Not rewriting third-party sync clients (`astroquery`, `alerce`, `antares-client`) — they keep
  their sync APIs. *How* each is offloaded differs by what it actually does; see F9 and
  `aio-offload-threads`.
- Not adopting Dash background callbacks / Celery. Our long tasks are I/O, not batch jobs.

## Findings that shape the plan

These were verified against the installed `dash==4.4.1` and drive the staging order.

**F1 — Under the FastAPI backend, a *synchronous* callback blocks the event loop.**
`FastAPIDashServer.serve_callback` (`dash/backends/_fastapi.py:549`) runs
`ctx.run(partial_func)` inline in an `async def` handler and only awaits if the result is a
coroutine. There is no threadpool hop for sync callbacks on the HTTP path. So flipping the
backend while any callback is still a plain `def` would serialize the *entire app* onto one
loop per worker — strictly worse than today. Every callback must be a coroutine function
*before* the flip.
(The WebSocket path is different: `dash/backends/_fastapi.py:710` does route sync callbacks
to a bounded shared `ThreadPoolExecutor`, `websocket_max_workers`, default 4.)

**F1a — but that does *not* force one big PR.** Dash only checks
`inspect.iscoroutinefunction(func)` at registration time (`dash/_callback.py:937`) to pick
the async dispatch wrapper. A registration-layer shim that wraps any sync callback into an `async def` satisfies F1 for every
callback in one ~30-line change, with no edits to a single callback body. *(As shipped the wrapper
awaits the callback inline rather than `asyncio.to_thread`-ing it; the offload waits for
`aio-uvicorn`, per the threading rule.)* Native async conversion then
proceeds one callback at a time, at leisure, with the shim as the safety net. This is what
makes the shell/flip stack a stack of small PRs rather than a monolith.

**F1a′ — the callback count: 39 is source sites, 57 is registrations.** *(measured in
`aio-invariants`; the plan originally said "39 callbacks" throughout, which undercounts.)*
- **39** is a source-site count: 33 `@app.callback` decorators + 6 bare `app.callback(...)` calls.
- **`app.callback_map` holds 59 entries — 57 server-side + 2 clientside.** The gap is
  `set_tables` (`ztf_viewer/pages/viewer.py:2048`), which registers one callback *per catalog*
  inside a loop — 19 of them.
- **23 registrations are `functools.partial`-based, not 4**: 19 `set_table`, 2
  `find_neighbours`, 2 `set_figure_link`. The original F1a named only the hand-written
  `app.callback(...)(partial(...))` sites and missed the loop, so `partial` handling in the shim
  is load-bearing for 23 registrations rather than an edge case.
- `inspect.iscoroutinefunction` **does** see through `functools.partial`, including nested —
  verified on Python 3.14 and now asserted by a test rather than assumed.
- Two consequences for anyone writing the invariant: `callback_map` entries hold Dash's own
  `add_context` / `async_add_context` wrapper, not our function (recover the original via
  `__wrapped__` / `partial.func` for error messages); and **clientside callbacks have no
  `"callback"` key at all**, so the invariant must exclude them explicitly or it `KeyError`s
  instead of failing cleanly.

**F1b — async callbacks already work on the *Flask* backend.**
`FlaskDashServer.serve_callback` has a second, async dispatch path (`_dispatch_async`,
`dash/backends/_flask.py:273`), selected by `use_async`, which auto-enables when `asgiref` is
importable (`dash/_validate.py:595` `check_async`) — i.e. as soon as `dash[async]` is
installed. Consequence: **the entire async conversion can land and deploy incrementally on
Flask**, and the backend flip shrinks to a handful of lines at the end of the stack. Without
`asgiref`, the sync path raises a loud, explicit error on encountering a coroutine
(`_flask.py:265-270`) — there is no silent-failure mode to fear.

**F1c — the two backends have different event-loop models, and it leaks.**
Flask runs `_dispatch_async` through asgiref's `async_to_sync`, i.e. a **fresh event loop per
request**, inside the same gunicorn worker thread. FastAPI has **one long-lived loop per
worker**. Anything loop-affine created at import time — `httpx.AsyncClient` connection pools,
`redis.asyncio` pools, `asyncio.Semaphore` / `Lock` — is bound to the loop that created it and
will misbehave on Flask. All such resources must be created lazily and keyed by
`asyncio.get_running_loop()`. This is a real cost of the flip-last ordering and is called out
as its own PR (`aio-loop-registry`); it is cheap to write and harmless to keep after the flip.

**F2 — `FastAPI()` is created bare; there is no `/static`.** See the `/static` design note for the options
discussion and the decision.
`FastAPIDashServer.create_app` (`dash/backends/_fastapi.py:276`) returns a plain `FastAPI()`.
The Flask backend instead gets `Flask(name)`, which silently provides `static_folder=<pkg>/static`
at `/static`. That implicit route is what serves, today:
`/static/img/logo.svg` (`ztf_viewer/__main__.py:45`), `/static/js/js9prefs.js` plus the four
JS9 files listed as `external_scripts`/`external_stylesheets` (`ztf_viewer/app.py:3-13`), and
the two deferred imports `/static/js/js9_helper.js` and `/static/js/aladin_helper.js`
(`ztf_viewer/pages/viewer.py:376,455`). `ztf_viewer/static/` is 16 KB in the repo but JS9 is
installed into `static/js9/` at image build time (`Dockerfile:14-22`), so the real payload is
several MB. Without an explicit mount, all of it 404s into the Dash index page via the
catch-all (`dash/backends/_fastapi.py:326`).
Note this is separate from `ztf_viewer/assets/` (464 KB), which Dash *does* mount on both
backends via `register_assets_blueprint` — on FastAPI as a `StaticFiles` mount
(`dash/backends/_fastapi.py:284`).

**F3 — The sync cache decorators cannot wrap coroutine functions.**
`ztf_viewer/cache.py` hands out either `redis_lru` or `cachetools.cached`. Applied to an
`async def`, both would cache the *coroutine object* — a correctness bug that returns an
already-awaited coroutine on the second hit. All 19 `@cache()` sites
(`grep -rn "@cache()" ztf_viewer`) need an async-aware decorator before the functions under
them become coroutines. `redis_lru` and `redis.StrictRedis` are sync-only; the async path
needs `redis.asyncio`.

**F4 — `flask.request` is used in exactly one place.**
`ztf_viewer/akb.py:37` `_token_from_cookies` (the `import flask` itself is at `akb.py:5`).
Dash exposes a backend-neutral
`dash.ctx.cookies` (`dash/_callback_context.py:274`) and `ctx.response.set_cookie` (already
used in `ztf_viewer/pages/login.py:35`). Trivial to make backend-agnostic ahead of time.
The full set of `flask` **import** sites `aio-deflask` must clear, measured during `aio-invariants`:
`akb.py:5`, `pages/favicon.py:1`, `pages/figure.py:7`, `pages/lc_csv.py:4`.

**F5 — Six Flask routes need porting**, all registered via `@app.server.route`:
`ztf_viewer/pages/figure.py:27,28,50`, `ztf_viewer/pages/lc_csv.py:45,93,103,113`,
`ztf_viewer/pages/favicon.py:6`. They use `flask.Response`, `flask.request.args`
(incl. `getlist`), `flask.send_file`, and `(body, status)` tuple returns — none of which
exist on Starlette. FastAPI *does* run plain `def` route handlers in a threadpool, so these
can stay synchronous initially without blocking the loop.

**F6 — `ztf_viewer/util.py:292` `timeout()` burns a thread per call.**
It spawns a `ThreadPoolExecutor(max_workers=1)` per invocation and is applied to every
cone-search query (`ztf_viewer/catalogs/conesearch/_base.py:108`). Under async this becomes
`asyncio.timeout` for free.

**F7 — The proxy situation already supports WebSockets.** Two points, both easy to get
backwards:
1. **`proxy/default.conf` in this repo is not in the app's request path.** `docker-compose.yml`
   defines only `redis` and `ztf-web-viewer-app`; there is no proxy service. The app joins the
   external `proxy` network and is picked up by the outer nginx-proxy through
   `VIRTUAL_HOST=ztf.snad.space`, which connects to the app container directly. The `proxy/`
   directory is a separately deployed cache in front of IRSA (`location /products`, matching
   `ZTF_FITS_PROXY_URL` and `proxy-cache-filler/`); its `location /` → `app_server` block is
   leftover from before the jwilder proxy. **No change needed there** — though the dead
   `location /` is worth deleting to avoid future confusion.
2. **The outer proxy already supports WebSockets out of the box.** It is
   `nginxproxy/nginx-proxy`, whose `nginx.tmpl` ships `proxy_http_version `aio-deflask``, the
   `map $http_upgrade $proxy_connection` block, and
   `proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection $proxy_connection;`
   on every location (verified against the upstream template).
What *does* need attention is timeouts and a config-management discrepancy — see
the proxy design note. That work is deployment-side and happens before/outside the PR stacks.

**F8 — Genuinely CPU-heavy work is narrow.** In order of cost:
PDF figure rendering via the matplotlib PGF backend, i.e. a LaTeX subprocess per request
(`ztf_viewer/pages/figure.py:294`, `Dockerfile:24-35`); PNG rendering; plotly figure
assembly and the per-observation Python loop in `ztf_viewer/lc_data/plot_data.py:18`; pandas
CSV assembly (`ztf_viewer/pages/lc_csv.py:13`).

**F9 — offload strategy differs by *why* a call is slow; there are two cases, not one.**
A single "offload to threads" rule flattens a real distinction. What matters is whether a
call is waiting on a socket or burning CPU.

1. **Network-bound sync clients → thread pool.** `astroquery` (Vizier, Simbad, MOCServer,
   Skybot), `alerce`, `antares-client`. These sit in `socket.recv` for most of their wall
   time, and CPython releases the GIL there, so threads give real concurrency — twenty
   catalogs genuinely overlap. A process pool would add pickling of astropy `Table`s and
   per-child interpreter memory to buy nothing. Their CPU component is real but small
   (VOTable/JSON → `Table`), tens of ms against seconds of network latency.
2. **CPU-bound work → process pool.** Only matplotlib rendering clears this bar (F8, `aio-figures`).

**F11 — the dev/PR deploy path overrides the entrypoint, and diverges from prod.**
`.github/workflows/deploy-dev.yml` renders `.ci/docker-compose.yml.tmpl`, which **hardcodes its
own entrypoint**, overriding the Dockerfile's:
`entrypoint: ["gunicorn", "-w2", "-t300", "--keep-alive=75", "-b0.0.0.0:80", "ztf_viewer.__main__:app"]`.
So `aio-uvicorn` must change **both** `Dockerfile:73` and that template — changing only the
Dockerfile leaves every dev and PR deployment launching gunicorn against an ASGI app, which
fails at startup. One further divergence from prod worth keeping in mind: dev runs `-w2 -t300`
with **no `--threads`**, i.e. 2 single-threaded workers, against prod's `-w2 --threads=8 -t70`.
Dev is therefore *more* sensitive to blocking calls than prod, which is useful: a regression in
concurrency shows up on the dev server first.

**F10 — dev and production run different Python minors.**
Development runs **Python 3.14**; the image is `python:3.12-bookworm` (`Dockerfile:1`),
`requires-python = ">=3.12"`, and black/ruff target `py312`. Tolerable for the largely
version-agnostic code we have today, but this plan adds a lot of asyncio, where the gap
between 3.12 and 3.14 is widest, and where a version difference is most likely to surface as
a subtle event-loop behaviour difference rather than an obvious failure. **Resolved by upgrading production to 3.14 in the foundations stack** (item `aio-py314`) rather than by
pinning development back. Also note `asgiref` is **not** currently installed, so `use_async` is
`False` today (`dash/_validate.py:595`) — consistent with `aio-shim` having to add the `dash[async]`
extra.

**F12 — today's cache is already broken in five ways, so the cache sub-stack is *not*
behaviour-preserving.** *(Found by `aio-cache-spec`, which characterized the current
`redis_lru`/`cachetools` behaviour against the argument and value types the app really uses.
Each defect below is an `xfail` in `tests/test_cache_contract.py`, non-strict so that a fix
surfaces as XPASS rather than forcing an edit to the spec.)*

This overturns the plan's original framing of `aio-cache-sync` as "behaviour-preserving by
construction". Five behaviours must **change**, deliberately:

1. **Memory backend: every `@cache()` site shares one keyspace.** `_crate_memory_cache` builds
   a single `TTLCache`, and `cachetools.cached`'s default `keys.hashkey` does not include the
   function. Two distinct cached functions called with identical args return **each other's
   values** — verified directly. Redis is unaffected (its key carries `module` + `qualname`).
   This is live in local dev *and in the test suite*, since `tests/conftest.py` forces
   `CACHE_TYPE=memory` — see the ordering note in `aio-golden-callbacks`.
2. **Redis backend: kwarg *names* are ignored.** `redis_lru._decorator_key` hashes only
   `kwargs.values()`, so `f(min_mjd=58000.0)` and `f(max_mjd=58000.0)` are the same entry.
   That is exactly the signature shape of `get_plot_data` and `model_fit.fit`; we are saved
   today only by callers passing both keywords in a fixed order.
3. **Redis backend: caching a picklable value can raise.** `RedisLRU.set` evaluates
   `value in self.exclude_values` for anything the `Hashable` ABC accepts, so returning e.g. a
   tuple of dicts raises `TypeError` out of the decorator instead of caching. Not obviously
   reachable from today's 19 sites, but "any picklable value round-trips" is a contract the
   rewrite should hold.
4. **The backends disagree on unhashable arguments.** Redis silently bypasses the cache
   (`ArgsUnhashable`); memory raises `TypeError` out of the wrapper. The rewrite should pick one
   and be explicit about it.
5. **All 16 method `@cache()` sites key on the identity of `self`** — memory puts the object in
   the key tuple, Redis uses `hash(self)`, which is `id()`-derived. **Consequence: the Redis
   cache is effectively per-process and per-boot** — cached catalog queries are not shared
   between the two gunicorn workers and are wholly lost on restart. The "persistent" cache is
   far less persistent than the architecture assumes. Note this does *not* undermine `aio-gather`'s
   "the second catalog loop is cheap" claim, which holds within a single request on one
   instance; it does mean the cross-request and cross-worker hit rate is much lower than
   assumed. **This is a decision for `aio-cache-core`, not a required fix** — keying on the class
   instead would fix it but is wrong for any instance carrying state. Tracked as open question 8.

Also worth carrying into `aio-cache-core`: the plan's list of awkward argument types omits
**`self`**, which is the *first* argument at 16 of the 19 sites and by far the most consequential
for keying, and **nested `immutabledict`** (the real `external_data` shape at `viewer.py:1658`).
Both are now covered by the spec. Separately, `immutabledefaultdict` caches its `__hash__` but
*mutates* on missing-key lookup, so after such a lookup it hashes equal to but compares unequal
to its original content — latent today because both backends behave identically and the app
rebuilds these mappings per callback, but a hazard if `aio-cache-core` starts keying on content
instead of `hash()`.

**F14 — the cache key cannot identify every callable, and failed unsafely in two ways.**
*(Found while reviewing `aio-cache-async`; both defects predate it, in `cache_core`'s
`function_id`.)* The key is `module.qualname` plus the encoded arguments, and `function_id` read
that as `getattr(func, "__qualname__", func.__name__)`. Python evaluates the default eagerly, so
`__name__` was required even when `__qualname__` was present — a callable carrying one but not
the other raised `AttributeError` from inside the wrapper, on the first *call*, which is exactly
what the decorator's `UncacheableArgument` bypass exists to prevent. Worse, a `functools.partial`
labelled with both attributes passed the check and then keyed on the wrapped function alone: its
bound arguments live in `partial.args`, which key derivation never sees, so two partials of one
function shared a single entry and returned each other's values. **Decision: refuse both at
decoration time** — partials by type (labelled or not), anything else by missing attribute — so a
bad `@cache()` site fails when its module is imported. Supporting partials by unwrapping them was
rejected: it fixes the name and leaves the wrong-value defect standing. No call site is affected
today; the risk grows as `aio-shim` introduces partial wrapping and the async-I/O stack converts
cached methods.

**F13 — `web.py` is backend-neutral except for one name: `request`.** *(Found reviewing what
`aio-deflask` actually landed, #633.)* The helpers came out as specified plus three more —
`request_body`, `error_response` and a `QueryArgs` view — and all of them take the request as an
argument, so they really do swap in one file. `ztf_viewer/web.py:15` also re-exports
`request = flask.request`, and `figure.py:34,56,58` and `lc_csv.py:47` use it **ambiently**, as a
module-level import. Starlette has no ambient request: the handler receives it. So the claim in
`aio-starlette-web` that `figure.py`/`lc_csv.py` need no edits holds for every helper *except*
this one. Those four call sites must take `request` as a parameter — cheap, but it must happen
in the same atomic sub-stack, and it is most naturally done in `aio-routes`, which is already
rewriting those handler signatures for path parameters.

**F15 — a callback converted to `async def` too early opts itself out of the offload.**
*(Found reviewing `aio-pilots`, #652, which was closed because of it.)* The shim returns the
function **unchanged** when it is already a coroutine — that is the whole point of
`_to_coroutine_function`. But `aio-uvicorn` installs the thread offload *inside that same
wrapper*, so the offload only ever covers callbacks the shim actually wrapped. A callback that is
`async def` while its body still makes blocking `requests`/`astroquery` calls therefore runs
inline on the one event loop after the flip, with nothing to catch it — which is precisely F1, the
failure the shim exists to prevent. The damage scales with the body: `get_summary`, the ~20-catalog
sequential fan-out, is the worst possible candidate.

**Rule: a callback becomes `async def` in the same change that gives it something to await** —
never earlier. This kills the "convert a few pilots first" idea outright, and it kills the larger
version too: converting all 39 sites ahead of the async-I/O work would opt the entire application
out of the offload and reinstate F1 wholesale. Mass conversion is the *last* step of the async-I/O
stack, not a step before it.

Two consequences to carry forward:
- `aio-uvicorn` must state which callbacks its offload actually covers. If any natively-async
  callback still has a blocking body when the flip lands, the offload must cover it too — or the
  flip is shipping a known loop-blocker.
- `aio-snad-apis`, `aio-conesearch` and `aio-gather` each convert bodies *and* signatures
  together. None of them may leave a callback `async def` with a blocking body behind.

---

## Shape of the work

Every PR is a branch named `aio-*`. Because of F1a/F1b, almost every one merges and deploys
safely **on its own, on Flask**; only the four flip branches are atomic with each other.

```
foundations   python 3.14, then tests            ──┐
prep          backend-neutral, ships on Flask    ──┤ ordered
shell + flip  async callbacks, then FastAPI      ──┤
                                                   │
async I/O     real awaits, concurrent fan-out  ─┐  │
WebSocket     transport + streaming UX         ─┤ parallel, after the flip
process pool  CPU-bound offload                ─┘
cleanup       remove the sync path
```

### Branch structure

Each branch is cut from its predecessor, so every PR's diff shows only its own change. The
chain is linear except where noted; branches marked ⇢ can instead be cut from `master`
directly, since they carry no dependency on the branch above them.

```
master
└─ aio-py314                  upgrade the interpreter first of all
   └─ robust-upstream-tests   transport failures on upstream tests → skip (replaced aio-fixtures)
      ├─ aio-golden-http    ⇢ route goldens (our outputs only)
      ├─ aio-golden-callbacks⇢ callback snapshots (pure/failure paths only)
      ├─ aio-cache-spec     ⇢ cache contract tests
      ├─ aio-bench          ⇢ fan-out benchmark harness
      ├─ aio-invariants     ⇢ migration guards
      └─ aio-deflask          drop direct flask coupling
         └─ aio-cache-core     keying + codec, no backend
            └─ aio-cache-sync    reimplement sync cache, drop redis_lru
               └─ aio-pytest-asyncio  async test support (moved up: the async cache needs it)
                  └─ aio-cache-async   cache() dispatches on sync vs async
                     └─ aio-cache-flight  single-flight
                        └─ aio-ttlset        async unavailable_catalogs
                           └─ aio-shim          all callbacks become coroutines
                              └─ aio-loop-registry  per-loop resources
                                 └─ aio-fastapi-app ── the flip, merged as one ──
                                    └─ aio-starlette-web
                                       └─ aio-routes
                                          └─ aio-uvicorn
                                             ├─ aio-httpx    ── async I/O chain ──
                                             │  └─ aio-snad-apis
                                             │     └─ aio-conesearch
                                             │        └─ aio-offload-threads
                                             │           └─ aio-gather
                                             ├─ aio-procpool ── process-pool chain ──
                                             │  └─ aio-figures
                                             │     └─ aio-profile
                                             └─ aio-ws       ── websocket chain ──
                                                └─ aio-stream
                                                   └─ aio-cleanup
```

The flip sits as early as its prerequisites allow: `aio-shim` satisfies F1 (every callback is a
coroutine) and `aio-loop-registry` satisfies F1c, and nothing else in the plan is a
prerequisite for it. Everything downstream is then written, reviewed and soaked on the runtime
we actually intend to ship. The async-I/O and process-pool chains do not depend on the backend
(F1b), so if the flip stalls in review they can be cut from `aio-loop-registry` instead and
rebased onto `aio-uvicorn` later.

**Threading rule for the whole plan: no thread pool exists before `aio-uvicorn`, and after it
there is exactly one place that sizes threads.** Decided deliberately, and it constrains every PR
in between.

Until the entrypoint flips, code that would otherwise offload to a thread runs inline instead —
that is why `aio-shim` shipped without the `ThreadPoolExecutor` its section originally specified.
The reason is control, not simplicity: a pool created before there is one configured home for its
size is a pool nobody owns. An unsized `ThreadPoolExecutor` silently becomes
`min(32, process_cpu_count() + 4)`, derived from the container's CPU allocation rather than from
anything we chose, and several such pools in several modules multiply without anyone being able to
read the total off the repo.

So: **no module builds its own `ThreadPoolExecutor`, and no code path falls through to a stdlib
default.** `aio-uvicorn` runs uvicorn with `--workers 1` — one process, one loop — and sizes both
thread pools (asyncio's default executor and anyio's limiter) from `config.py`. All concurrency
then lives *inside* the application, where it is counted, rather than being spread across worker
replication and implicit pools. Any PR that wants to offload work to a thread before that point is
in the wrong order: move the offload to `aio-uvicorn` or later, not the pool earlier.

One violation predates the rule and is inherited, not introduced: `util.py`'s `timeout()` spawns a
`ThreadPoolExecutor(max_workers=1)` **per call**, on every cone-search query (F6). It is the
clearest existing case of threads nobody counts, and `aio-conesearch` retires it by replacing it
with `asyncio.timeout`. Until then it stays as-is — the rule forbids adding pools, not tolerating
the one already there.

**Review-surface rule for the whole plan:** no PR should mix a mechanical rename/rewrap with
a semantic change. Where a change touches many files shallowly (`aio-shim`) it gets its own PR
whose diff is one-line-per-site and can be skimmed; where it touches one file deeply
(`aio-snad-apis`, `aio-gather`) it gets its own PR with tests.

### Deployment model and the working-code rule

**No production release until the whole plan lands.** Production stays on the current Flask
build for the duration. What must keep working continuously is the **dev server**,
`master.ztf.snad.space`, which `deploy-dev.yml` redeploys on every push to `master`.

That gives one hard rule and one very useful mechanism:

- **Rule: master must always be deployable and working on the dev server.** Every *stack* must
  leave master in that state; individual PRs need not be independently deployable.
- **Decided: the flip lands early**, immediately after `aio-shim` + `aio-loop-registry`, so the
  dev server runs FastAPI for the whole remaining migration and every later stack is written
  against the runtime it will ship on.
- **Mechanism: every PR already gets its own preview environment**, `pr<N>.ztf.snad.space`,
  built from the same template. So "does this break the dev server?" is answerable *before*
  merge, per PR, not discovered after. Each PR below should be smoke-checked on its own preview
  URL before merging — that is the enforcement of the rule, and it costs nothing extra because
  the pipeline already exists.

Because prod is frozen, "risky to ship" mostly stops being a consideration; the real currencies
are *review surface* and *keeping master green*. Two consequences worth naming:

- **Inert PRs** add code nothing calls yet (`aio-cache-core`, `aio-cache-async`,
  `aio-loop-registry`, `aio-procpool`). Merging them changes nothing at runtime, so they cannot
  break the dev server.
- **Live PRs** change behaviour on merge (`aio-cache-sync`, `aio-cache-flight`, `aio-shim`,
  `aio-gather`). These are the ones whose preview URL actually needs clicking through before
  merge.

The only genuinely non-deployable intermediate states are the flip branches, and they are
exactly the sub-stack already marked atomic: `aio-starlette-web` breaks Flask and only makes
sense once `aio-uvicorn` lands. Merged as one stack, master never sees the broken state.

The foundations stack precedes everything and is worth landing even if the rest of this plan is
deferred.

---

## Design note: serving `/static` after the flip

Four options were considered for replacing Flask's implicit static route (F2).

| Option | Cost | Verdict |
| --- | --- | --- |
| **A. `app.server.mount("/static", StaticFiles(...))`** | one line | **chosen** |
| B. Let nginx serve `/static` from a shared volume | app image must publish JS9 to a volume the shared proxy can read | rejected |
| C. Move the files into Dash's `assets/` | Dockerfile + index changes, needs `assets_ignore` | rejected |
| D. Mount a Flask sub-app for static only | keeps a WSGI stack alive forever | rejected |

**Why not B.** Superficially attractive — nginx serves several MB of JS9 better than Python
does. But the outer proxy is *shared infrastructure* (`nginxproxy/nginx-proxy` fronting every
service behind it, the proxy design note), not an app-local sidecar. Serving our static files from it means
exporting JS9 from the app image into a volume the proxy container mounts, and keeping those
two in sync across deploys. That couples our release process to shared infrastructure to save
a few MB of proxied traffic that is already cached by browsers. If static throughput ever
actually matters, the right move is a CDN or the app-local `proxy/` container, not the shared
vhost proxy.

**Why not C.** Dash auto-injects *every* `.js`/`.css` under `assets/` into the page, in
filename order — that is exactly why `assets/` currently holds `10-jquery-1.9.1.min.js` and
`20-aladin.min.js` with ordering prefixes. JS9 is deliberately *not* there: it is declared via
`external_scripts` (`ztf_viewer/app.py:8-13`) and two files are loaded lazily through
`dash_defer_js_import` (`viewer.py:376,455`). Moving it into `assets/` would auto-include
files we currently defer, and would need an `assets_ignore` regex to claw that back — plus a
Dockerfile change, since JS9's install path is fixed at build time
(`./configure --with-webdir=/app/ztf_viewer/static/js9`). More moving parts, no benefit.

**Decision: Option A**, with two details that belong in `aio-fastapi-app`:
- **Mount ordering.** Starlette matches routes in registration order and `mount()` appends to
  the same router table. The mount must happen at app construction — before Dash registers
  the index and the lazy `{path:path}` catch-all (`dash/backends/_fastapi.py:326`), which is
  set up on first request. Mounting in `ztf_viewer/app.py` right after `dash.Dash(...)`
  guarantees precedence.
- **Cache headers differ — but less than this note originally claimed.** *(Measured in
  `aio-golden-http` against the installed Flask 3.1.3.)* The note assumed Flask sends
  `Cache-Control: max-age=<SEND_FILE_MAX_AGE_DEFAULT>`; it actually sends
  **`Cache-Control: no-cache`** plus `ETag`/`Last-Modified` — Flask's default changed at some
  point. Starlette's `StaticFiles` sends `ETag`/`Last-Modified` and no `Cache-Control`. So
  **both** backends already do conditional revalidation on every JS9 asset today, and the flip
  is not the regression this note feared. That reframes the item: the cache headers are worth
  setting explicitly on the mount (or at the proxy) as an *improvement* we could make at any
  time, not as flip-blocking damage control.
- The header assertion for `/static/js9/js9.min.js` is landed (`aio-golden-http`), so whichever
  way those headers change, CI says so rather than a slow page.

---

## Design note: deployment proxy work (do first, outside the PR stacks)

The deployment fronts this app with an `nginxproxy/nginx-proxy` vhost proxy (selected by the
`VIRTUAL_HOST` variable in `docker-compose.yml`) plus an ACME companion, configured in a
separate private ops repository. WebSocket support itself needs no change there (F7). Three
things do want attention, none of them blocked by this plan — they can be done now,
independently, and they live outside this repository.

1. **Confirm which proxy config is actually live.** The vhost proxy's tuning snippets
   (`/etc/nginx/vhost.d/default`, `/etc/nginx/vhost.d/default_location`) can be baked into a
   derived image *or* persist on a named volume, and those two can silently disagree — a
   volume may still hold snippets written by an older image that is no longer built. **Verify
   on the deployment host rather than reading the compose file:**
   `docker exec <proxy-container> cat /etc/nginx/vhost.d/default_location`.
   Then make it deliberate: either build the derived image, or manage the `vhost.d` snippets
   as explicitly mounted files.
2. **Timeouts matter more after this migration.** nginx's default `proxy_read_timeout` is 60 s
   and the upstream nginx-proxy template sets none. Dash's WebSocket heartbeat defaults to
   30 s, so an idle connection survives on heartbeats alone — but only while heartbeats stay
   enabled and under the timeout. Long timeouts (the ops repo intends 1 h) are comfortable for
   both persistent WS connections and slow catalog fan-out; item 1 is about making sure they
   are actually applied. Prefer a **per-vhost** `vhost.d/<hostname>_location` file, so the
   viewer's timeouts don't ride on a global default shared with every other service behind the
   same proxy.
3. **Re-check the `client_max_body_size` patch.** The ops repo applies it through a helper
   container whose shell redirection targets a path that is not the mounted volume, so the
   setting has likely never taken effect. Unrelated to this migration, but adjacent enough to
   fix while in there.

Also worth a look while nearby: the ops compose file still declares the obsolete
`version: '2'` key, and the dead `location /` block in this repo's `proxy/default.conf` (F7)
should go.

---

## Stack: Foundations — Python 3.14 and tests, before anything moves

The single highest-leverage pre-work. Every stack below rewrites code whose only current
specification is its behaviour in production; without a "before" snapshot we cannot tell a
successful port from a subtly broken one. All of the foundations stack merges on today's Flask app and is
worth having even if the rest of this plan is shelved.

### Rule: no tests for functionality that does not exist yet

Established while reviewing `aio-invariants` (#626) and applying to every stack below. **A test
must describe what is supposed to work now.** A test written in advance of the feature it
describes cannot fail usefully; it encodes the plan in the test suite, and the `xfail` marker it
needs is a standing instruction to ignore it. When a PR establishes a new rule, the guard for
that rule is written **in that PR, as a plain passing assertion** — not earlier, and not as an
`xfail` waiting to be flipped.

The one legitimate use of `xfail` here is the opposite case: a test that characterizes **today's
behaviour including its defects**, which is a real specification of a real system. That is why
`aio-cache-spec`'s five markers stay (F12) — they describe what the current cache actually does —
and why `aio-invariants`' markers did not.

Order within the stack: **`aio-py314` first** (the interpreter upgrade, so the goldens are recorded
against the version we keep), then the rest in any order. The original ordering put a replay
layer second and made everything depend on it; that layer is gone (see below), so the remaining
items are independent and can be cut from `master` directly.

### `aio-py314` — Upgrade to Python 3.14 *(first within this stack)*
Resolves F10 by moving production up to the version development already runs, rather than
holding development back.
- `Dockerfile:1` → a `python:3.14` base; `pyproject.toml` `requires-python`;
  `[tool.black] target-version` and `[tool.ruff] target-version` → `py314`; regenerate
  `uv.lock`; make sure CI builds on the same base (`.github/workflows/test.yml` runs tests via
  Docker, so it follows the image).
- **The risk here is wheels, not our code.** The dependency set includes several packages that
  historically lag a new CPython by months and then build from source —
  `numpy`/`scipy`/`astropy`/`pandas`/`matplotlib`/`mocpy` all need checking. Do a
  `uv lock` dry run against 3.14 **before** committing to this ordering; if something has no
  3.14 wheel and won't build, that changes the answer to open question 7 and we stay on 3.12
  with 3.14 added to CI instead.
- **Why it belongs first, ahead of the fixtures and goldens.** Two reasons, one of them
  non-obvious:
  1. `aio-golden-http`'s CSV goldens are byte-exact, and they are produced by pandas/numpy through
     `DataFrame.to_csv`. Recording them on 3.12 and then changing the interpreter — and with it
     the resolved wheel versions — risks a wave of golden churn that is indistinguishable from
     a real regression. Record them once, on the version we intend to keep.
  2. 3.14 turns several asyncio foot-guns into hard errors rather than warnings — notably
     implicit event-loop creation via `asyncio.get_event_loop()`, which `aio-loop-registry`'s per-loop registry
     must avoid anyway (it uses `get_running_loop()`). We want that strictness in place
     *while* the async code is being written, not discovered afterwards.
- **Accept:** image builds on all three `[tool.uv] environments` targets (linux x86_64, linux
  aarch64, darwin arm64); existing suite green; a smoke run of the app in the container.

**The blocker, and how it was resolved.** The current suite hits the live network:
`tests/catalogs/conesearch/test_tns.py` really queries TNS; `tests/catalogs/test_ztf_ref.py`
really downloads a FITS file. The plan originally answered this with `aio-fixtures` — record
every upstream response and replay it, so the suite is hermetic and before/after comparisons
are exact.

**That was tried (#631, branch `http-fixtures`, kept but closed) and rejected as not worth its
cost.** Two reasons, both of which also re-scope the goldens below:

1. Those catalog tests exist to check **our parsing** against what upstreams actually return —
   column names, masked-vs-`"None"`, coordinate ranges. Replaying a recorded blob mostly
   re-tests the blob.
2. The third-party sync clients (`astroquery`, `alerce`, `antares-client`) are explicitly *not*
   being ported to async (F9), so their recordings could never take part in the before/after
   comparison the fixture layer was justified by.

It also turned out not to be the cheap layer it looked like: three upstream paths bypass
`requests` entirely (`astropy.io.fits.open` uses urllib; astroquery's TAP layer speaks
`http.client`), `import ztf_viewer.catalogs.conesearch` performs blocking network I/O at import
time, astroquery's on-disk cache made the suite non-hermetic underneath any adapter, and
`astroquery.simbad` serializes an identical query differently per process (set iteration order),
so byte-exact request matching needs a per-upstream canonicalizer. Those findings are worth
keeping even though the branch is not: **the import-time blocking I/O is on the startup path and
matters to `aio-loop-registry`**, and **Simbad's unstable column order lands on any snapshot test
that touches it.**

**What replaced it: #632 `robust-upstream-tests`, merged.** Tests stay live, but an
`upstream`-marked test that fails with a *transport-level* error becomes a skip-with-warning
rather than a failure, implemented in `pytest_runtest_makereport` so it covers fixtures as well
as test bodies. Assertion failures and `NotFound` still fail — those are answers, not outages.
That buys the actual thing we needed (CI stops going red because Simbad is down) without a
replay layer.

**Consequence for the goldens: they characterize *our* outputs, not upstream data.** Anything
whose value is really an upstream's payload is out of scope; anything we compute, format,
serialize or route is in scope. Perfect coverage is explicitly not the goal — a thin, honest
subset that pins the parts the flip is likely to break is worth more than a broad one that goes
red for reasons outside this repo.

### `aio-golden-http` — HTTP surface golden tests *(re-scoped)*
Characterize the routes whose behaviour is ours: index, `/login`, `/tags`, `/anomalies`,
`/health`, `/favicon.ico`, `/static/...`, and the shape (not the data) of
`/dr24/csv/<oid>`, `/dr24/figure/<oid>` (png + pdf), `/dr24/figure/<oid>/folded/<period>`.
- Assert status, `Content-Type`, `Content-Disposition`, and the response-construction details
  that `aio-starlette-web`/`aio-routes` will re-implement. **Byte-exact CSV goldens are dropped**
  along with the fixtures they depended on — without replay their bytes are an upstream's data,
  not ours. Pin the CSV *header row*, column set, dtype formatting and content-disposition
  instead, which is the part `lc_csv.py` actually authors.
- Assert `/static/js9/js9.min.js` returns 200 **and** record its cache headers — this is the
  test that catches both F2 and the Flask/Starlette cache-header difference (the `/static` design
  note). Highest-value item in this PR, and it needs no upstream at all.
- Figures: don't byte-compare PNG/PDF in CI (matplotlib/LaTeX output is not reproducible
  across versions). Assert magic bytes, non-trivial size, and mimetype; keep an opt-in visual
  comparison for local use.
- Routes needing a live upstream (`/dr24/view/<oid>`, `/dr24/search/...`, the per-catalog CSVs)
  get the `upstream` marker so #632's skip-on-transport-error applies, or are skipped entirely.
- **Accept:** green on Flask; must stay green through `aio-fastapi-app`–`aio-uvicorn` with no edits.

### `aio-golden-callbacks` — Callback characterization *(re-scoped, and much thinner)*
Dash callbacks are ordinary functions, so they can be called directly and their returned
component tree snapshotted with `plotly.utils.PlotlyJSONEncoder`. Without a replay layer this
can no longer be the full regression net the plan originally leaned on for the async-I/O stack,
so aim narrower: **snapshot callbacks whose output is a pure function of their inputs**, feeding
them hand-written or minimal stub data rather than recorded upstream payloads.
- Best candidates are the presentation-side callbacks — layout assembly, `set_figure_link`,
  `set_lc_table`, `set_features_list`, `get_metadata` — where the interesting logic is ours.
- Highest value is the **failure** paths, which need no upstream at all and are exactly where a
  rewrite silently drifts: catalog raises `NotFound`; catalog raises `CatalogUnavailable`;
  catalog present in `unavailable_catalogs`. `aio-gather`'s `gather(..., return_exceptions=True)`
  must reproduce the current per-catalog `except ...: continue` semantics exactly, and these
  snapshots — driven by stub catalogs that raise on cue — are how we know it does. Write these
  even if nothing else in this PR gets written.
- **Import-order hazard, found in `aio-golden-http`:** `ztf_viewer.catalogs.unavailable_catalogs`
  connects to Redis **eagerly at import** (`RedisTTLStringSet.__init__` calls `client.info()`), so
  `CACHE_TYPE` / `UNAVAILABLE_CATALOGS_CACHE_TYPE` must be forced to `memory` *before*
  `ztf_viewer.__main__` is first imported — not merely before the test runs. `tests/conftest.py`'s
  `pytest_runtest_setup` hook does it per-test, which is a hook/fixture-ordering race the moment
  another test module imports first. Set `ztf_viewer.config` directly in the fixture before
  importing, as `tests/test_golden_http.py` does. This is also import-time blocking I/O on the
  startup path, so it belongs on `aio-loop-registry`'s list alongside the `astroquery.gaia` one.
- `get_summary` and `set_table` over a real catalog are the ones that most wanted replay; either
  stub the catalog objects or leave them out. **Anything Simbad-derived has unstable column
  order** (set iteration, per-process) and must be normalized or skipped.
- **Ordering hazard — record snapshots with the cache disabled, not merely empty (F12.1).**
  `tests/conftest.py` forces `CACHE_TYPE=memory`, and on that backend *every* `@cache()` site
  shares one keyspace, so two distinct cached functions called with identical arguments return
  each other's values. A snapshot recorded under that condition can bake in a wrong value that
  then looks like the specification. Either disable caching outright for snapshot recording, or
  land `aio-cache-sync` (which fixes F12.1) before recording. Do not simply clear the cache
  between tests — that reduces the odds without removing the failure mode.
- **Accept:** snapshots committed; a deliberate one-line change to a callback makes the
  matching snapshot fail.

### `aio-cache-spec` — Cache contract tests (the spec for the cache sub-stack)
*(Landed — branch `aio-cache-spec`, `tests/test_cache_contract.py`: 88 tests, each parametrized
over `CACHE_TYPE` in `{memory, redis}`. It found five defects in today's implementation; see F12.)*

Written *against today's* `redis_lru`/`cachetools` behaviour, as a **black box**: hits and misses
are counted through the wrapped function body, no key strings are asserted, and no
`redis_lru`/`cachetools` name appears in any assertion — because the rewrite is explicitly
allowed to change the key scheme.
- key identity for the awkward argument types we actually pass — `immutabledict`, **nested
  `immutabledict`**, `immutabledefaultdict` (both `lambda: np.inf` and `float` factories),
  `frozenset` (`lc_data/plot_data.py:82`), `tuple[int]` (`model_fit.py:89`), and **`self`**;
- distinct functions with identical args do not collide — including distinct methods of one
  class, and same-named methods on different classes;
- pickle round-trip fidelity for the values we cache: `astropy.table.Table` (with units,
  descriptions, `meta` and masked columns), a `Table` `Row` (what `vizier.py:15` caches),
  `SkyCoord`, plain and nested dicts, list-of-dicts, numpy arrays;
- TTL expiry — before, after, and per-entry — for both `CACHE_TYPE=memory` and `redis`.
- **Accept:** green on the current implementation, with the five known defects recorded as
  **non-strict** `xfail`. Non-strict is deliberate: the plan's original "the cache sub-stack
  changes no test in this file" would otherwise force an edit the moment the rewrite fixes a
  bug, whereas non-strict lets a fix surface as XPASS. See the revised `aio-cache-sync` criterion.

### `aio-bench` — Concurrency benchmark harness
- A **harness** — not a test — that drives `get_summary` against **stub catalogs** with an
  injected per-upstream delay and reports total wall-clock. Unaffected by dropping the replay
  layer: what this measures is the fan-out *shape*, so a `sleep`-and-return stub is not merely
  sufficient, it is better than a recording, because the delay is the point and should be
  explicit.
- **Ship it as a runnable benchmark, not as a collected test that asserts nothing.** A
  no-assertion test is the same anti-pattern as an `xfail` placeholder — it occupies a slot in
  the suite while being unable to fail. The real assertion (with N catalogs each delayed `d`,
  elapsed must be `~d`, not `~N·d`) is written **in `aio-gather`**, the PR that makes it true,
  where it converts "the payoff" from a claim into a CI-enforced property.
- Consequently this item is optional and can be folded into `aio-gather` outright; it is listed
  separately only because having the harness early makes the baseline easy to quote.
- **Accept:** baseline number recorded in the PR description.

### ~~`aio-invariants`~~ — the guards, distributed to the PRs that establish them
*(Partly landed as #626, `tests/test_cache_decorator_guards.py` — deliberately much smaller than
this section originally specified. Branch `migration-invariants`; the earlier #622 was closed only
because GitHub auto-closes on a head-branch rename.)*

The original idea was one file of guards, several of them `xfail` with the future PR named in
the marker, flipped to hard assertions as each landed. **That framing was rejected during
review, and the reasoning generalizes:** a test describing a state that does not exist yet
cannot fail usefully — it encodes the plan in the test suite rather than saying what is supposed
to work now. Note this is the *opposite* call from `aio-cache-spec`'s non-strict `xfail`s, and
for a coherent reason: those describe **today's** behaviour including its defects, which is a
real specification; these described tomorrow's.

**What landed** (the subset that already holds today, so it is an ordinary passing test):
- `@cache()` is never applied to a coroutine function — an `ast` scan over the package (F3);
- the sync `cache()` decorator itself should *refuse* a coroutine function. This one **failed**
  on merge — today's `redis_lru`/`cachetools` accepts it silently — and was fixed by
  `aio-cache-sync`.

Both were **deleted again by `aio-cache-async`**, which makes `cache()` dispatch on the kind of
function it wraps: there is no longer a choice for a guard to police.

**What was reassigned**, each to be written as a plain passing assertion in the PR that makes it
true:
- **no `import flask` outside `ztf_viewer/web.py` → `aio-deflask`.** An `ast` walk, not a regex,
  so string literals and comments cannot produce false hits.
- **every server-side entry in `app.callback_map` is a coroutine function → `aio-shim`.** Must
  exclude clientside callbacks explicitly, which have no `"callback"` key at all and would
  otherwise `KeyError` instead of failing cleanly (F1a′). Reading `callback_map` requires
  importing `ztf_viewer.__main__`; a static source scan cannot work, because after `aio-shim` the
  source still says `def` and the wrapping happens at registration time. The import is
  session-scoped, does no network or Redis I/O, and costs ~0 s marginally inside the full suite.
- **The async-decorator guards → dropped.** `aio-cache-async` makes the single `cache()` dispatch on
  `inspect.iscoroutinefunction`, so there is no longer a wrong decorator to pick and nothing for
  a guard to police.

Two guards from the original list are worth keeping wherever they land, because they are
permanent facts rather than migration states: that `inspect.iscoroutinefunction` really does see
through `functools.partial`, including nested (F1a′ depends on it, verified on 3.14), and an
anti-vacuity check that `callback_map` is populated at all — both belong with the `aio-shim`
guard.

**What the net actually is, now that replay is gone.** The original claim was that fixtures plus
callback snapshots would turn the risky stacks — `aio-snad-apis`, `aio-conesearch`, `aio-gather` —
into "snapshot unchanged?" reviews. Without replay that is only partly true, and it is worth
being honest about which guarantees remain:

- **Kept:** the failure-path snapshots (`NotFound` / `CatalogUnavailable` / unavailable-catalogs),
  which need no upstream and cover exactly the semantics `aio-gather`'s
  `return_exceptions=True` must reproduce; the cache contract tests; the migration invariants;
  the `aio-bench` fan-out assertion.
- **Lost:** byte-exact before/after comparison of upstream-derived output. Those stacks are
  reviewed as diffs, backed by live `upstream`-marked tests that skip rather than fail when a
  service is down.
- **Mitigation:** `aio-snad-apis` touches *first-party* APIs (ztf_dr, features, model_fit, akb,
  ztf_ref), which are ours and stable; if any one stack later proves to need real replay, the
  `http-fixtures` branch is still there to revive for that narrow case rather than for the
  whole suite.

---

## Stack: Prep — backend-neutral, still on Flask

Everything here is behaviour-preserving and independently valuable. Ship it first so
the shell/flip stack stays small enough to review.

### `aio-deflask` — Remove direct Flask coupling from app code
*(Landed — #633, branch `deflask`. `web.py` also grew `request_body`, `error_response` and a
`QueryArgs` view; the one thing that did not come out backend-neutral is the ambient `request`
re-export, see F13.)*
- `ztf_viewer/akb.py:37`: `flask.request.cookies` → `dash.ctx.cookies` (F4); drop the
  `flask` import.
- Introduce `ztf_viewer/web.py` with backend-neutral helpers used by the routes:
  `file_response(...)`, `csv_response(...)`, `binary_response(...)`, `query_args(request)`.
  Implement against Flask for now, single-file swap in `aio-starlette-web`.
- Rewrite `ztf_viewer/pages/{figure,lc_csv,favicon}.py` to call those helpers and to return
  explicit responses instead of `(body, status)` tuples.
- **Accept:** existing behaviour identical; `grep -rn "^import flask\|from flask" ztf_viewer`
  matches only `ztf_viewer/web.py`. Add the **no-`import`-flask-outside-`web.py` guard here**, as
  a plain passing test — an `ast` walk, not a regex, so string literals and comments cannot
  produce false hits. This is the PR that makes the rule true, so it is the PR that owns the
  guard (see the no-tests-in-advance rule).

### `aio-pytest-asyncio` — Async test support *(moved up: it is a prerequisite, not a follow-up)*
Originally listed last in this stack. That was an ordering mistake: `aio-cache-async` is the
first PR in the plan that adds a coroutine, so it is also the first that cannot be tested
without async test support. Nothing here depends on the cache work, so moving it to the front
of the remaining prep chain costs nothing and stops `aio-cache-async` from having to carry
test-infrastructure changes alongside a cache rewrite.
Route coverage lives in `aio-golden-http`; this PR only adds what async tests need.
- Add `pytest-asyncio` to the `tests` dependency group; `asyncio_mode = "auto"`.
- The `httpx.MockTransport` adapter this PR originally carried is dropped with the replay layer.
  What replaces it is smaller: make sure #632's skip-on-transport-error path also fires for
  async `upstream`-marked tests (the `pytest_runtest_makereport` hook is transport-agnostic, but
  `httpx` raises a different exception hierarchy than `requests`, so the classifier needs the
  `httpx` exceptions added — do it here, before any async upstream test exists). `httpx` is not
  a dependency until `aio-fastapi-app`, which is fine: `tests/conftest.py` already imports
  third-party transport exceptions lazily and skips the ones that are not installed.
- **Accept:** an async test and a sync test asserting identical results against the same
  upstream; an injected `httpx` transport error on an `upstream`-marked async test skips rather
  than fails.

### the cache sub-stack — Async-capable cache layer *(its own stack of four PRs)*
The cache sits under all 19 `@cache()` sites and under every catalog query; it is the one
piece of shared infrastructure the whole migration rests on, so it gets its own reviewable
stack rather than one big rewrite. Spec is `aio-cache-spec`, written first and unchanged throughout.

- **`aio-cache-core` — Extract the keying/serialization core.** A `cache_key(func, args, kwargs)` function
  (`module.qualname` + stable encoding of args) and a pickle value codec, as pure functions
  with no backend and no decorator. Nothing calls them yet except tests. Reviewable in
  isolation, and this is where the awkward `immutabledict`/`frozenset`/`tuple[int]` argument
  handling actually lives — **plus `self` and nested `immutabledict`**, which the original
  list omitted (F12).
  - The key must include the function (`module.qualname`) **for both backends**, fixing F12.1,
    and must incorporate kwarg *names*, fixing F12.2.
  - Decide `self`-keying deliberately here (F12.5 / open question 8) and write the decision
    into the PR description either way.
- **`aio-cache-sync` — Reimplement the *sync* `cache()` on that core, dropping `redis_lru`.**
  Backends: `StrictRedis` (as today) and `cachetools.TTLCache`.
  **Not behaviour-preserving — and that is the point.** The original plan claimed it was; F12
  showed today's behaviour contains five defects, so this PR is where four of them get fixed
  (F12.1–F12.4) and the fifth is a recorded decision. The proof obligation is therefore *not*
  "the spec passes unchanged" but the sharper:
  - every non-`xfail` test in `tests/test_cache_contract.py` still passes, **and**
  - the tests currently `xfail` for F12.1–F12.4 turn XPASS.
  The spec file still changes by zero lines in this PR; dropping the now-stale `xfail` markers
  is a deliberate follow-up commit, which is exactly why they were written non-strict.
  Lands well before any async exists, which is the point: the riskiest part of the cache
  rewrite is reviewed and soaked on the dev server on its own, decoupled from everything else.
  - Rationale for dropping `redis_lru`: it is a thin LRU-over-Redis wrapper with no async
    path, it is the direct cause of F12.2 and F12.3, and we need deterministic keys of our own
    anyway.
- **`aio-cache-async` — Make `cache()` dispatch.** One public decorator: `cache()` inspects the
  function it wraps (`inspect.iscoroutinefunction`, which sees through `functools.partial`, F1a')
  and routes to an internal sync factory or an async one on `redis.asyncio` + an
  `asyncio.Lock`-guarded `TTLCache`. Both share `aio-cache-core`'s core so entries are
  *key-compatible* regardless of which path wrote them (a value cached via a sync call is a hit
  for an async one — this matters during the async-I/O stack, when some callers are converted and
  others are not). No call site ever chooses a decorator, so the F3 mistake is unreachable rather
  than merely guarded against. Resources come from `aio-loop-registry`'s per-loop registry (F1c).
- **`aio-cache-flight` — Single-flight.** Coalesce concurrent identical misses behind one shared future, on
  both decorators. Separate PR because it is the only part with genuinely subtle concurrency
  semantics (exception propagation to all waiters, cancellation of the leader, no cross-loop
  future sharing). It also becomes load-bearing rather than a nicety the moment `aio-gather` lands: N
  users on a popular object currently serialize into N identical upstream queries.
- **Accept (whole stack):** no non-`xfail` test in `aio-cache-spec` regresses at any step, and the
  F12.1–F12.4 `xfail`s turn XPASS by the end of `aio-cache-sync`; new tests for cross-decorator
  key compatibility (`aio-cache-async`) and dedupe under concurrent misses (`aio-cache-flight`); `pytest-redis` fixtures
  as in `tests/test_ttl_set_redis_ttl_set.py`.
  - Local note: `pytest-redis` fails on macOS with `UnixSocketTooLong` because of the long
    default `TMPDIR`; run `pytest --basetemp=/tmp/pytest`. This already breaks the existing
    `test_ttl_set_redis_*` tests locally and is not caused by anything in this plan. CI runs in
    Docker and is unaffected.

Two of these four PRs are inert (`aio-cache-core`, `aio-cache-async`: nothing calls them yet)
and two are live (`aio-cache-sync`, `aio-cache-flight`). The key scheme changes at
`aio-cache-sync`, so existing Redis entries become unreachable on deploy — an accepted cold
start, not something to design around. Per F12.5 that cold start is also smaller than it
sounds: method-site entries are already per-process and per-boot today.

### `aio-ttlset` — Async-capable `unavailable_catalogs`
- `ztf_viewer/ttl_set.py` `RedisTTLStringSet` → add an async variant on `redis.asyncio`
  (`AsyncRedisTTLStringSet`), keep `LocalTTLSet` usable from async (it's pure in-memory).
- `ztf_viewer/catalogs/unavailable_catalogs.py` gains an async accessor.
- **Accept:** mirrored versions of the three existing `test_ttl_set_*` suites.

---

## Stack: Async shell, then the flip

Six PRs. **`aio-shim` and `aio-loop-registry` each merge and deploy on their own, on Flask** (F1b): they are the async
conversion, and they are safe without the backend change. Only **`aio-fastapi-app`–`aio-uvicorn` are atomic** — the
Starlette response swap breaks Flask, so that sub-stack must land as one merge.

```
`aio-shim` dash[async] + callback shim      ← merges solo, still Flask
`aio-loop-registry` loop-affine resource discipline  ← merges solo, still Flask
────────────────────────────────────  the flip: merge as one stack ↓
`aio-fastapi-app` static mount + app construction
`aio-starlette-web` web.py → Starlette
`aio-routes` route ports
`aio-uvicorn` uvicorn entrypoint + Dockerfile + backend default
```

### `aio-shim` — `dash[async]` and the callback shim *(small, high leverage)*
This is the PR that dissolves the F1 constraint.
- Add the `dash[async]` extra (pulls `asgiref`) so `use_async` auto-enables on Flask
  (`dash/_validate.py:595`). Nothing else changes about how the app runs today.
- Add `ztf_viewer/callbacks.py` exposing our own `callback(...)` wrapper: if the decorated
  function is already a coroutine function, register it as-is; otherwise wrap it as
  an `async def` (preserving `functools.wraps`) and register that. ~30 lines. **The wrapper awaits
  the callback inline; it does not `asyncio.to_thread` it** — that offload arrives with the pool in
  `aio-uvicorn`, per the threading rule.
- Mechanically repoint all **39 source sites** from `app.callback` to this wrapper — a
  one-line-per-site diff, no bodies touched, trivially skimmable in review. Note those 39 sites
  produce **57 server-side registrations** (F1a′), because `set_tables`
  (`ztf_viewer/pages/viewer.py:2048`) registers one callback per catalog inside a loop. The diff
  is per-site; the invariant is per-registration.
- **23 registrations are `functools.partial`-based** — 19 `set_table`, 2 `find_neighbours`,
  2 `set_figure_link` — not the four the original F1a named (F1a′). The shim
  must unwrap/handle `functools.partial`; `inspect.iscoroutinefunction` does see through a
  partial of an `async def` (verified on 3.14; assert it here, alongside the guard), but our own
  "is this sync?" check must too. The loop registration is the easiest one to miss in review.
- The 2 **clientside** callbacks have no `"callback"` key in `callback_map` and are not ours to
  wrap — exclude them explicitly in the invariant.
- Contextvars: **moot while the wrapper is inline** — `dash.ctx` is read on the same thread that
  set it. It becomes live again in `aio-uvicorn`, where the wrapper starts offloading:
  `asyncio.to_thread` propagates the current context, so `dash.ctx` still works, but the test
  asserting `ctx.cookies` is readable from inside the offloaded thread belongs *there*, with the
  offload it protects. The AKB/login path depends on it.
- ~~Bound the offload pool explicitly instead of relying on the default `min(32, cpu_count+4)`:
  install a sized `ThreadPoolExecutor` as the loop default executor, matched to today's
  `--threads=8`.~~ **Moved to `aio-uvicorn`**, which is where thread-pool sizes get their single
  configured home. As landed, the wrapper awaits the callback inline rather than offloading it,
  so there is no pool here to bound.
- **Accept:** every **server-side** entry in `app.callback_map` is a coroutine function — write
  this guard **here**, as a plain passing test, since this is the PR that makes it true (it is
  the invariant F1 needs; see the no-tests-in-advance rule). Bring the two permanent facts with
  it: that `inspect.iscoroutinefunction` sees through nested `functools.partial`, and an
  anti-vacuity check that `callback_map` is populated at all. Exclude clientside callbacks
  explicitly or the guard `KeyError`s instead of failing cleanly. Also: no `RuntimeWarning` from `dash/_callback.py:944`;
  `aio-golden-http` green; site behaves identically on Flask.
- ~~**Note:** on Flask this is a small *pessimization* (a per-request event loop plus a thread
  hop, versus just a thread).~~ **Did not materialize**, because the thread hop was dropped
  along with the pool: on Flask the cost is the per-request event loop alone.

### `aio-loop-registry` — Loop-affine resource discipline
Per F1c, prerequisite for anything in the async-I/O stack to work on both backends.
- Any `httpx.AsyncClient`, `redis.asyncio` pool, `asyncio.Semaphore` or `Lock` is created
  lazily through a small registry keyed by the running loop, never at import time. **Not by
  `id(loop)`** — ids are recycled, so a new loop can inherit a dead loop's resource.
- **"Cleanup on loop close" is not achievable as written.** `aclose()` needs a live loop;
  `transport.close()` raises `RuntimeError: Event loop is closed`; and `weakref.finalize` on the
  loop cannot help, because holding the resource in order to close it later is exactly what keeps
  the loop alive, so the finalizer runs at interpreter exit instead. Weak keys alone do not even
  reclaim the *entry*: a `WeakKeyDictionary` holds values strongly and a connected
  `redis.asyncio` client references its loop via `transport._loop`, so it pins its own key —
  measured at one leaked entry per loop. What works is sweeping entries whose loop `is_closed()`,
  which bounds the table by the number of live loops. Graceful close belongs to a shutdown hook on
  a live loop, i.e. after the flip.
- Retrofit the cache sub-stack's async path and `aio-ttlset`'s async TTL set onto that registry.
- **Accept:** a test that acquires each resource under two successive
  `asyncio.run(...)` calls (simulating Flask's per-request loop) without error, and a test
  that a single long-lived loop reuses one instance (simulating FastAPI).
- *(Landed as #651 `loop-registry` + #654. The registry keys on the loop **object**, not
  `id(loop)`, and the four existing ad-hoc per-loop caches were retrofitted onto it. One thing the
  design did not survive contact with: weak keys alone do not reclaim a `redis.asyncio` client,
  which holds its own loop through its transport, so #654 added the closed-loop sweep. No
  `httpx.AsyncClient` or `asyncio.Semaphore` exists yet — those arrive with the async-I/O stack and
  are expected to use the registry from the start.)*

### ~~`aio-pilots`~~ — Native async pilots *(dropped; #652 closed)*
The idea was to convert two or three callbacks to genuinely `async def` before the flip — one
reading `ctx.cookies`, one `partial`-registered, one fan-out — to validate the conversion pattern
while rollback was still a one-line revert.

**It validates nothing and costs something.** Per F15, a callback that is `async def` with a
blocking body bypasses the offload `aio-uvicorn` puts in the shim's wrapper, so the pilots would
have quietly excluded themselves — `get_summary` above all — from the protection the flip depends
on. And the mechanics they were meant to prove are already proved: `tests/test_callbacks_shim.py`
covers `iscoroutinefunction` through nested partials, the shim passing a coroutine through
unwrapped, and `dash.ctx.cookies` resolving through the shim path.

The conversion recipe this PR was to produce belongs with the first PR that actually converts a
body, in the async-I/O stack.

---

*Everything below merges as one stack.*

### `aio-fastapi-app` — Dependencies, app construction, static mount
- `pyproject.toml`: add `fastapi`, `uvicorn[standard]`, `httpx`. `flask` leaves our direct
  dependency list (stays transitive via dash).
- `ztf_viewer/app.py`: backend selected by env var — `dash.Dash(..., backend=DASH_BACKEND)`,
  defaulting to `flask` in this PR and flipped to `fastapi` in `aio-uvicorn`. Keep
  `health_endpoint="/health"`.
- Mount static explicitly (F2) when the backend is FastAPI, after app construction and before
  any route registration or first request:
  `app.server.mount("/static", StaticFiles(directory=<pkg>/static), name="static")`.
- **Accept:** with `DASH_BACKEND=fastapi`, the index renders and JS9 + `logo.svg` load
  (guards F2); with the default, nothing changes.

### `aio-starlette-web` — `web.py` → Starlette
- Swap `ztf_viewer/web.py` internals (built in `aio-deflask`) to Starlette `Response` / `FileResponse` /
  `PlainTextResponse`. Every helper takes its request as an argument, so `figure.py` /
  `lc_csv.py` / `favicon.py` need no edits here — **except for the ambient `request` re-export
  (F13)**, which has no Starlette equivalent and is dealt with in `aio-routes`.
- **Accept:** unit tests on the helpers; this is the PR that makes the stack atomic — Flask
  is broken from here until `aio-uvicorn`.

### `aio-routes` — Port the six routes
- Registration moves to `app.server.add_api_route(...)`. Flask converters become FastAPI path
  params: `"/<dr>/figure/<int:oid>/folded/<float:period>"` →
  `"/{dr}/figure/{oid}/folded/{period}"` with typed signature params. The existing int/float
  route pair (`ztf_viewer/pages/figure.py:27-28`) collapses to a single `float` route — keep
  an int-first route only if a client depends on the distinction.
- `request.args.getlist("other_oid")` → `request.query_params.getlist(...)` (or
  `list[str] = Query(...)`), inside `web.py`'s `QueryArgs`.
- **Take `request` as a handler parameter** at `figure.py:34,56,58` and `lc_csv.py:47`, dropping
  the ambient `from ztf_viewer.web import request` (F13). Four call sites.
- Keep these handlers **sync** `def` — FastAPI threadpools them (F5). Making them async is
  the process-pool stack's job, after the CPU work moves off-loop.
- **Accept:** `aio-golden-http` passes unchanged — that is its stated acceptance criterion, so a
  route port that changes a status, content type or disposition fails CI; figure PNG/PDF and all four CSV endpoints
  byte-compare against the Flask build for a fixed OID.

### `aio-uvicorn` — Entrypoint, deployment, and the default flip
- `ztf_viewer/__main__.py`: dev path becomes `uvicorn.run("ztf_viewer.__main__:app.server", ...)`.
  Do **not** use Dash's `app.run(debug=True)` under FastAPI — it re-execs uvicorn as a
  subprocess by inspecting the caller frame (`dash/backends/_fastapi.py:384-470`), which is
  fragile for a `python -m` entry point.
- `Dockerfile:73`: `gunicorn -w2 --threads=8 ...` →
  `uvicorn ztf_viewer.__main__:app.server --host 0.0.0.0 --port 80 --workers 1`. Prefer plain
  uvicorn over `gunicorn -k uvicorn.workers.UvicornWorker` — one fewer moving part.
- **This is where the threading rule is discharged** (see "Shape of the work"): thread-pool sizes
  are decided in exactly one place — `config.py`, from an environment variable set next to the
  entrypoint — and nowhere else. There are **two** pools to set, not one, and missing either
  leaves a stdlib default in play:
  1. asyncio's default executor, which every `asyncio.to_thread` call reaches —
     `loop.set_default_executor(...)` once in a startup hook (safe here, unlike under Flask,
     because the loop is long-lived and never torn down per request);
  2. anyio's limiter, which Starlette uses to run the sync `def` route handlers — default 40
     tokens, set via `anyio.to_thread.current_default_thread_limiter().total_tokens`.
- **Turn the shim's wrapper into an offload here** (`ztf_viewer/callbacks.py`), in the same PR
  that creates the pool. Until this point the wrapper runs callbacks inline, which is correct on
  Flask and catastrophic on FastAPI: flipping the backend while it is still inline serializes
  every callback onto the loop. Add a test asserting the wrapper offloads when the FastAPI
  backend is selected, so the two cannot drift apart.
  **State what the offload covers** (F15): it reaches only callbacks the shim wrapped, so any
  callback that is natively `async def` bypasses it. That is correct exactly when such a callback
  genuinely awaits its I/O. Before flipping, check that every natively-async callback does — a
  blocking body behind an `async def` is a loop-blocker the offload will not catch.
- **`--workers 1`, decided.** One loop, one process: concurrency now comes from the loop rather
  than from replication, and it makes the in-process caches and `unavailable_catalogs` whole
  again: with two workers they are per-process and half the hits are missed (F12.5). Revisit
  only against a load test that shows one loop saturating a core, which is what settles open
  question 1.
- **`.ci/docker-compose.yml.tmpl` must change too** (F11): it hardcodes its own gunicorn
  `entrypoint:`, which overrides the Dockerfile for every dev and PR deployment. Miss this and
  the flip passes CI, then fails to start on `master.ztf.snad.space`.
- Timeouts: `-t70 --keep-alive=75` today. Uvicorn has no per-request worker timeout; long
  upstream calls are bounded by our own `asyncio.timeout` (F6) instead. Set
  `--timeout-keep-alive` to match nginx.
- Flip the `DASH_BACKEND` default to `fastapi`. `HEALTHCHECK` unchanged.
- **Accept:** `docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build`
  serves the site; healthcheck green; **and the PR preview at `pr<N>.ztf.snad.space` comes up
  and serves an object page** — this is the check that would catch the F11 template trap.
  Per-worker RSS compared against the Flask build.

**Rollback.** One level, not two. This section originally offered `DASH_BACKEND=flask` as a cheap
first resort; that env var was dropped during review of `aio-fastapi-app` precisely because
`aio-starlette-web`/`aio-routes` keep no Flask-compatible path for it to select. Rollback for
`aio-fastapi-app`–`aio-uvicorn` is a revert of the merged stack, which is exactly why they merge as
one unit. `aio-shim` and `aio-loop-registry` stay in place either way; they are pure async conversion and backend-neutral.

---

## Stack: Async I/O

The `asyncio.to_thread` shims get replaced with genuine `await`s, bottom-up. Each PR is
independently shippable and revertable.

**Runs after the flip, on FastAPI.** Nothing here depends on the backend (F1b), so this stack
*could* run on Flask — that is the escape hatch if the flip stalls in review. But it is written
and measured on FastAPI by choice: with prod frozen there is no value in banking the win early,
and timing `asyncio.gather` on asgiref's per-request loop would measure a configuration we
never intend to run.

### `aio-httpx` — Shared async HTTP client
- `ztf_viewer/http.py`: an `httpx.AsyncClient` with connection limits, a default timeout, and
  retry policy, obtained through `aio-loop-registry`'s per-loop registry (not a module-level singleton — F1c);
  closed on loop teardown / app shutdown.
- Replace `ztf_viewer/util.py:292` `timeout()` with `asyncio.timeout` at the call sites
  (F6) — keep the sync `timeout()` around only while sync paths remain.
- **Accept:** unit test that a slow endpoint raises `CatalogUnavailable` with the right
  `catalog=` kwarg, matching today's `_base.py:108` behaviour.

### `aio-snad-apis` — First-party services (highest value, lowest risk — all plain JSON over HTTP)
Convert to `async def` — the `@cache()` line stays as it is:
- `ztf_viewer/catalogs/ztf_dr.py` — `FindZTFOID.find` (`:42`), `FindZTFCircle.find` (`:100`),
  and the `get_lc` / `get_meta` / `get_coord*` accessors that call them. This one is on the
  critical path of nearly every callback.
- `ztf_viewer/lc_features.py` (`:18`, `:29`)
- `ztf_viewer/model_fit.py` (`:12`, `:27`, `:86`) — also replaces the bare
  `requests.post`/`requests.get` and their `print()` error reporting with `logging`.
- `ztf_viewer/akb.py` — all of it; note `whoami` uses `cachetools.cached` directly
  (`:111`, `:129`), which becomes `@cache()`.
- `ztf_viewer/catalogs/ztf_ref.py` (`:41`) — fetch bytes with httpx, then parse the FITS from
  an in-memory buffer instead of letting `astropy.io.fits.open` do its own blocking URL
  fetch; parsing itself moves to a thread (or the process-pool stack's pool).
- `ztf_viewer/date_with_frac.py:55` — scrapes an HTML index, trivial conversion.
- **Accept:** existing catalog tests plus new ones per module; viewer page renders identically.

### `aio-conesearch` — Cone-search catalogs
- `_BaseCatalogApiQuery._api_query_region` (`ztf_viewer/catalogs/conesearch/_base.py:295`) and
  `find` (`:145`) become async; `_BaseNameResolverQuery.resolve_name` (`:275`) likewise.
  That covers every catalog that talks plain JSON to a SNAD-hosted API.
- Per-catalog follow-ups where the query is bespoke: `panstarrs.py:118`, `ogle.py:63`,
  `sdss.py:41`, `fink.py`, `colibri.py`, `otter.py`, `tns.py`, `gaia_dr3.py`.
- **Accept:** the `tests/catalogs/conesearch/` suite, extended to cover every converted
  catalog, and a manual check that the "catalog temporarily unavailable" path still trips
  (`unavailable_catalogs`, now via `aio-ttlset`'s async set).

### `aio-offload-threads` — Sync-only third parties stay sync, offloaded according to F9
Do **not** try to port these to async. **Network-bound → `asyncio.to_thread`, with a
per-upstream bounded semaphore** so one slow service cannot eat the shared thread pool:
- `astroquery`: `Vizier` (`catalogs/vizier.py`, `conesearch/_base.py:328`), `Simbad`,
  `MOCServerClass` (`vizier.py:17`), `Skybot` (`catalogs/skybot.py`)
- `alerce.core.Alerce` (`conesearch/alerce.py:35`)
- `antares_client.search` (`conesearch/antares.py:29`)
- **Size the pool against fan-out width, not core count.** `aio-uvicorn` set the number in
  `config.py` (`THREAD_POOL_SIZE`, default 16); this is the PR that knows what it should be. Note
  it sizes **two** independent pools to that same value — asyncio's default executor and anyio's
  sync-route limiter — so the process ceiling is twice the number, and only the first of the two
  is what `asyncio.to_thread` reaches. One object page fans out to ~19
  catalogs, so a pool sized like `cpu_count + 4` serializes a *single user's* page — the very
  thing `aio-gather` exists to fix. The shape is fan-out width × expected concurrent pages, with
  the per-upstream semaphores providing fairness so one slow service cannot take the pool.
- **Accept:** semaphore limits configurable **from the same single place as the pool size**; a
  test that a stalled upstream does not block unrelated catalogs.

### `aio-gather` — Concurrent fan-out (the payoff)
- `get_summary` (`ztf_viewer/pages/viewer.py:1379`): replace the serial
  `for catalog, query in catalog_query_objects()` loop with `asyncio.gather(...,
  return_exceptions=True)`, preserving the current per-catalog
  `except (NotFound, CatalogUnavailable, KeyError): continue` semantics. Note it currently
  loops over every catalog **twice** (again at `:1451` for ML classifications) — with the
  cache that's cheap, but the gather should compute once and reuse.
- `find_neighbours`, `get_metadata`, `set_figure`'s external light curves
  (`ztf_viewer/lc_data/plot_data.py:110-160`, currently a serial dict comprehension over
  antares/gaia/panstarrs): gather.
- `ztf_viewer/pages/lc_csv.py:13` `get_csv`: gather the per-OID `get_lc`/`ztf_ref.get`.
- **Accept:** measured wall-clock for a cold `get_summary` on a known-busy field, before vs
  after, recorded in the PR description. This is the number that justifies the whole project.

---

## Stack: WebSocket — transport and streaming UX

Depends on the flip — the Flask backend has no WebSocket transport, so this is the one stack
that could never have run early in any ordering. Independent of the async-I/O stack, but the UX win only really
shows once `aio-gather` lands.

### `aio-ws` — Transport enablement
- Proxy prerequisites are already handled: upgrades work natively and the timeout/config
  cleanup is the proxy design note, done ahead of the stacks. Confirm the proxy design note item 1 was actually verified on the
  box before enabling this.
- `dash.Dash(..., websocket_callbacks=True, websocket_allowed_origins=[...],
  websocket_max_workers=..., websocket_inactivity_timeout=..., websocket_heartbeat_interval=...)`.
  Origins must be set explicitly — the handler rejects on Origin mismatch
  (`dash/backends/_fastapi.py:710`).
- Consider enabling per-callback (`websocket=True`) first rather than globally, so the HTTP
  path stays as a fallback while we gain confidence.
- **Accept:** callbacks dispatch over `ws://` in devtools; reconnect after a proxy restart
  works; HTTP fallback still functions with `websocket_callbacks=False`.

### `aio-stream` — Progressive rendering
Now the actual UX change. Convert the slow, fan-out callbacks to no-output `set_props`
streaming so results paint as they arrive instead of in one blocking batch:
- the per-catalog tables (`set_tables`, `ztf_viewer/pages/viewer.py:2046`) — today ~20
  independent callbacks each waiting on one upstream; with `set_props` they can be one
  streaming callback that pushes each table as its `gather` task completes;
- `get_summary` — push rows incrementally, so the page is useful before Vizier answers;
- the light-curve figure — paint ZTF DR photometry immediately, then push external
  (antares/gaia/panstarrs) traces as they land.
- Per `dash/backends/ws.py:44`, any persistent/streaming callback **must** be `async def` and
  **must** check `ctx.websocket.is_shutdown` in its loop, or it leaks work after disconnect.
- **Accept:** with an artificially delayed catalog, the rest of the page renders without
  waiting; closing the tab mid-load stops server-side work (assert via logs).

---

## Stack: Process pool — CPU-bound offload

Runs after the flip. Nothing here depends on the backend — the routes can `run_in_executor`
either way — so it can be pulled earlier if convenient. Do it **after** measuring — the point of F8 is that this list is short, and a process pool costs pickling and
memory.

### `aio-procpool` — Pool infrastructure
- A `ProcessPoolExecutor`, one per worker process, sized ~`cpu_count // workers`, created and
  torn down through `aio-loop-registry`'s registry so it works under both loop models.
- macOS/spawn safety: worker functions must be importable module-level functions with no
  captured state, and every entry point stays behind `if __name__ == "__main__":`
  (repo convention). Verify locally under spawn *and* in the Linux container under fork.
- **Accept:** pool survives worker reload; no zombie processes; a crash in a child surfaces
  as a 500 rather than a hang.

### `aio-figures` — Figure rendering — **both PDF and PNG**
- `ztf_viewer/pages/figure.py` `plot_data` / `plot_folded_data` / `save_fig` move into the
  pool for *every* format, not just PDF.
- The two paths differ in cost but not in kind. PDF is worse — `usetex=True`
  (`figure.py:102,192`) plus `FigureCanvasPgf.print_pdf` (`:294`) shells out to a LaTeX
  process per request, which is why the image carries `texlive-latex-extra`, `texlive-xetex`
  and a 50 MB `main_memory` bump (`Dockerfile:24-35`). But PNG is not cheap either: it is
  still a full matplotlib figure — `errorbar` + `scatter` per light curve, over every epoch of
  every neighbour OID, at `dpi=300` — executed synchronously in the request. Under Flask that
  occupies a gunicorn thread; under FastAPI, an un-offloaded sync route handler is threadpooled
  by FastAPI (F5) but still burns a worker for the duration. PNG is also the *common* case:
  it is the default format (`figure.py:68`), so it is what most users actually hit.
- Treating them the same also keeps one code path: `save_fig` dispatches on `fmt` internally,
  so splitting PNG and PDF across pool/no-pool would mean fragmenting it for no benefit.
- **Correction to "differ in cost but not in kind": under threads they differ in kind, and the
  cheaper format is the more hostile one.** *(Measured while reviewing `aio-snad-apis`, which put
  both renderers on `asyncio.to_thread`; numbers in the `aio-profile` table.)* PDF's cost is
  dominated by **waiting on the LaTeX child process**, which releases the GIL — four concurrent PDF
  renders on four threads come out at **3.33x**, i.e. they already overlap. PNG is in-process Agg
  rendering and manages **1.25x**, barely above the GIL-bound control. So the process pool is
  needed for PNG — the *default* format (`figure.py:68`), and therefore the common one — while PDF,
  the expensive one, is the case a thread already handles. This inverts F8's cost ordering as a
  guide to what needs pooling, and it means the "pool both formats" decision rests on the
  one-code-path argument alone, not on PDF being worse.
- The routes become `async def` and `await loop.run_in_executor(pool, ...)`; inputs are
  already plain dicts/lists (`get_plot_data` output), so pickling is cheap.
- **Accept:** `aio-golden-http`'s figure assertions unchanged for both formats; measure both — a concurrent
  PNG flood and a concurrent PDF flood must each stop degrading unrelated page loads.

### `aio-profile` — Candidates to evaluate, not to assume
Measure before moving; each may be cheaper to leave on a thread:
- `ztf_viewer/lc_data/plot_data.py:18` `plot_data` per-observation loop (pure Python over
  every epoch; likely worth vectorizing with numpy *instead of* pooling),
- `ztf_viewer/pages/lc_csv.py` pandas assembly,
- `ztf_viewer/catalogs/ztf_ref.py:41` FITS parse (after `aio-snad-apis` makes the fetch async),
- plotly figure construction in `set_figure` (`ztf_viewer/pages/viewer.py:1606`).

**The question here is promotion, not introduction.** `aio-snad-apis` had to put the FITS parse,
the pandas CSV assembly and both matplotlib renderers behind `asyncio.to_thread` the moment their
callers became coroutines — a thread was the only offload available, since no process pool exists
until `aio-procpool`. So this section inherits work that is already *off the loop* and asks a
narrower question: does moving it further, to a process, earn the pickling and the child-process
memory? Answer it per site, with a measurement.

**Measured, not assumed: a thread buys these workloads almost nothing.** It is tempting to argue
that numpy/pandas/astropy spend their time in C that releases the GIL, so threads are enough. That
argument was made during review and is **wrong**. `plans/misc/gil_bench.py` runs each workload as 4
tasks on 4 threads against the same 4 run serially, on the interpreter we ship (CPython 3.14, GIL
enabled), with two controls to bracket the range:

| workload | serial | threaded | speedup |
| --- | --- | --- | --- |
| `time.sleep` — control, pure wait | 0.612 s | 0.154 s | **3.98x** |
| Python arithmetic — control, GIL-bound | 0.390 s | 0.399 s | **0.98x** |
| astropy FITS parse, 2M rows (`ztf_ref`) | 0.058 s | 0.035 s | **1.65x** |
| pandas concat + sort + `to_csv` (`lc_csv`) | 2.826 s | 2.594 s | **1.09x** |
| matplotlib Agg PNG (`figure`) | 1.146 s | 0.916 s | **1.25x** |
| matplotlib PGF → LaTeX PDF (`figure`) | 5.111 s | 1.533 s | **3.33x** |
| per-observation loop (`plot_data`) | 0.209 s | 0.220 s | **0.95x** |

pandas and Agg sit at the GIL-bound control, not near the parallel one. The per-observation loop is
*slower* on threads than serially — thread overhead on top of no parallelism at all. The FITS parse
does release partially, but 57 ms for 2M rows is negligible against a real reference catalog.

**So the destination for this work is a process, and the `to_thread` calls `aio-snad-apis` had to
introduce are keeping the loop responsive, nothing more.** The one real exception is the LaTeX/PDF
path, which parallelizes because it waits on a child process — see the correction under
`aio-figures`. `lc_data/plot_data.py:18` still heads the list, and vectorizing it with numpy may
still beat pooling it, but that is now a claim about *that* loop rather than about C extensions in
general.

**Rule that came out of reviewing `aio-snad-apis`: none of this reasoning belongs in a code
comment.** A comment that labels work "CPU-bound" next to an `asyncio.to_thread` call states a
classification and pairs it with the mechanism that does not follow from it, and a comment that
says a call is "out of scope here" is describing a PR boundary that is stale as soon as the next
PR lands. Both facts live in this plan, which is versioned, and in the PR description, which is
dated. `await asyncio.to_thread(x)` needs no gloss.

---

## Stack: Cleanup

### `aio-cleanup` — Remove the sync path
- Drop the `requests` direct dependency once the async-I/O stack is complete (it stays transitive via
  astroquery/alerce/antares).
- Remove the sync `timeout()` helper (`ztf_viewer/util.py:292`) and the sync `cache()`
  variant once nothing uses them.
- Remove any remaining `flask[async]` extra. *(The `DASH_BACKEND` escape hatch this item also
  named was never built — see the flip's Progress entry.)*
- **Retire `ztf_viewer/callbacks.py`.** The shim is transitional, not permanent. By this point the
  I/O-bound callbacks are natively `async def` (the shim passes those through untouched) and the
  sync-only third parties are offloaded explicitly with their own semaphores (`aio-offload-threads`),
  so what the shim still wraps is mostly trivial presentation callbacks — for which a thread hop
  and a context copy cost more than running inline on the loop. Unwrap those, keep native `async
  def` for the rest, and either drop the callbacks-are-coroutines guard or replace it with the
  narrower rule that actually matters: no callback performs blocking I/O.
- Update `README.md`, `AGENTS.md` (run command, dev stack), `CHANGELOG.md`.
- Add a small load-test script (`plans/misc/`) so the concurrency claims stay verifiable.

---

## Cross-cutting risks

| Risk | Mitigation |
| --- | --- |
| Sync callback silently blocks the loop after the flip (F1) | `aio-shim`'s shim makes every callback a coroutine; a test asserts the invariant over `app.callback_map`, so a newly added sync callback fails CI rather than production |
| A callback added between `aio-shim` and `aio-uvicorn` bypasses the shim | The invariant test above catches it; also make `ztf_viewer/callbacks.py` the only sanctioned import and lint for direct `app.callback` use |
| Cache decorator applied to a coroutine (F3) | No longer reachable: `cache()` dispatches on `inspect.iscoroutinefunction` instead of requiring the caller to pick a decorator. Covered by tests |
| Golden snapshots recorded through a colliding memory cache, baking a wrong value in as the spec (F12.1) | Record `aio-golden-callbacks` snapshots with caching disabled, or after `aio-cache-sync` fixes the shared keyspace — not merely with the cache cleared between tests |
| The cache rewrite silently preserves one of today's defects (F12) | The five defects are recorded as named `xfail`s in `aio-cache-spec`; `aio-cache-sync`'s accept criterion is that F12.1–F12.4 turn XPASS, so preserving a bug fails the criterion rather than passing quietly |
| `aio-shim` misses the 19 loop-registered `set_table` callbacks (F1a′) | The invariant asserts over all 57 registrations, not the 39 source sites, so a missed loop fails CI |
| Static assets 404 after the flip (F2) | `aio-golden-http` asserts `/static/js9/js9.min.js` and `/static/img/logo.svg` return 200 — landed, #634 |
| Concurrent fan-out hammers upstreams that previously saw serialized traffic | Per-upstream `asyncio.Semaphore` (`aio-offload-threads`) plus the existing `unavailable_catalogs` circuit breaker; keep an eye on Vizier/Simbad rate limits |
| Cache stampede amplified by concurrency | Single-flight in the cache sub-stack — this becomes load-bearing, not a nicety |
| WebSocket dropped by a proxy (F7) | nginx-proxy handles upgrades natively; residual risk is timeouts and the the proxy design note config discrepancy — verify the deployed proxy config first, then roll out per-callback (`aio-ws`) with HTTP retained as fallback |
| Static assets served with weaker caching after the flip (the `/static` design note) | `aio-golden-http` records today's cache headers for `/static/js9/js9.min.js`; set them explicitly on the mount |
| Process pool memory blowup | `aio-procpool` sizing; compare container RSS before/after |
| Redis client split-brain (sync `StrictRedis` in `ttl_set.py`, async elsewhere) | `aio-ttlset` lands the async set before anything async touches it; one connection pool per worker |
| Loop-affine client reused across Flask's per-request loops (F1c) | `aio-loop-registry`'s per-loop registry, with a test that runs two successive `asyncio.run` calls |
| `aio-starlette-web` is assumed to be a one-file swap, but the ambient `request` re-export has no Starlette equivalent (F13) | The four call sites are named in `aio-routes`, inside the same atomic sub-stack; `aio-golden-http` fails if any of those routes changes shape |
| Flip passes CI but breaks `master.ztf.snad.space` via the hardcoded entrypoint (F11) | `aio-uvicorn` changes `.ci/docker-compose.yml.tmpl` alongside the Dockerfile; verified on the PR preview before merge |
| Async code developed on a different Python than it ships on (F10) | `aio-py314` upgrades production to 3.14 first, before any goldens are recorded or async is written |
| A dependency has no Python 3.14 wheel and won't build | `aio-py314` opens with a `uv lock` dry run; if it fails, fall back to staying on 3.12 and adding 3.14 to CI — decided before, not during |
| The `aio-fastapi-app`–`aio-uvicorn` stack sits open too long and drifts | It is four small PRs with no external dependencies; if review stalls, land the async-I/O stack first (it ships on Flask) rather than holding the stack open |

## Open questions

Tick these off as they are answered.

1. ~~**Worker count under uvicorn.**~~ **Answered: `--workers 1`** (see `aio-uvicorn`). Still
   worth a load test to confirm one loop does not saturate a core under real fan-out; the
   cleanup stack's script is where that lives.
2. **How much of the process-pool stack is real?** `aio-figures` is clearly justified; `aio-profile` is speculative until profiled.
   Do not build the pool for `aio-profile`'s sake alone.
3. **Do we keep an HTTP fallback permanently** (`aio-ws` per-callback) or commit fully to WebSocket
   transport? Depends on what the deployment proxies tolerate.
4. **Is the `dr7` / legacy-URL behaviour** in `app_select_by_url` (`ztf_viewer/__main__.py:328`)
   worth preserving verbatim through the route port, or can it be dropped now?
5. **`websocket_max_workers` sizing** matters only if any sync callback survives; if `aio-shim`'s
   invariant holds it should be irrelevant — worth asserting.
6. ~~**Does the foundations stack block the start, or run alongside?**~~ **Answered: it runs
   alongside.** The replay layer that was the long pole is gone, so nothing in foundations blocks
   anything else. `aio-golden-http` landed alongside the prep stack (#634); `aio-golden-callbacks`
   and `aio-bench` are independent and can still land at any point.
7. ~~**Python 3.14 upgrade — does the dependency set cooperate?**~~ **Answered: yes** — #625
   merged, production is on 3.14.
8. ~~**Should the cache key on `self`?**~~ **Answered in `aio-cache-core` (#628): key on the
   class**, resolved at call time, with a `__cache_key__()` opt-out. The audit found the 15 true
   method sites all live on module-level singletons whose per-instance state is transport
   (`requests.Session`, client objects, the timeout decorator), never anything that changes a
   result for equal arguments. `_BaseCatalogQuery` — whose `find` is shared by 20 subclasses and
   which carries a per-catalog `query_name` — defines `__cache_key__` returning
   `normalized_query_name`, so it is keyed exactly rather than relying on the accident that each
   class has exactly one instance. **Consequence: Redis method entries are now shared between
   workers and survive restarts**, which they never did. Two corrections to F12.5 fell out: the
   count is 15 methods + 1 `@staticmethod` (not 16 methods), and the staticmethod is why
   `self`-detection must be descriptor-based rather than `__qualname__`-based. F12.4 was also
   decided here: unhashable arguments are keyed **on content**; only a genuinely un-encodable
   argument raises, and the decorator turns that into an uncached call rather than an error.

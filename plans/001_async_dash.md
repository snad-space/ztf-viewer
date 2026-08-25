# 001 — Porting the ZTF Viewer to async (Dash 4 FastAPI backend)

Status: in progress · foundations landed in full; prep landed in full;
the async shell has landed in full (`aio-shim`, `aio-loop-registry`; `aio-pilots` dropped); **the
flip has landed** (#658–#661, merged as one stack); **the async-I/O stack is complete**
(`aio-httpx`, `aio-snad-apis`, `aio-conesearch`, `aio-gather` — #664, #665, #668, #681;
`aio-offload-threads` dropped). **The process-pool stack is complete**
(`aio-procpool`, `aio-figures`, `aio-profile` — #685, #686, #689/#690). **Transport enablement has
landed** (`aio-ws` — #693), and browsers really do use it — verified live in Firefox and Safari
(see the Progress list). **`aio-stream`'s first slice was tried and rejected** (per-catalog tables,
#696, closed without merging — it collapsed independent failure domains into one); only the
`get_summary` slice is still planned. What remains is that `get_summary` slice and `aio-cleanup`.
The out-of-band proxy-config verification the WebSocket stack depends on has now been partly
answered by reading the ops repo directly, plus a live protocol-level test against the dev/preview
host (see the Progress list and the design note below) — it is the frontier now.
Baseline: `master` after `994874e`
Now running: FastAPI backend under uvicorn, one worker, one loop; Python 3.14
First-party HTTP and every JSON cone-search catalog now go through one shared async `httpx`
client, fanned out concurrently via `asyncio.gather` rather than queried one at a time; the sync
third parties (astroquery, alerce, antares) reach a **bare, unbounded** `asyncio.to_thread`, and
now permanently — see the dropped entry below.

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
- [x] `aio-golden-callbacks` — **re-scoped** the same way, and then **the snapshot mechanism the
      section below specifies was tried and reversed** — #679 `golden-callbacks`.
      Serialized component trees were written first, as specified; review rejected them as
      unmaintainable and the evidence was decisive: the four failure-path snapshots came out
      **byte-identical to each other** (same md5), i.e. 432 lines of JSON encoding the single fact
      that a failing catalog contributes nothing, while pinning `style` dicts and URL-encoded
      broker `href`s no test cared about. An `UPDATE_CALLBACK_GOLDEN=1` re-record flag made
      re-recording the path of least resistance, which is how a characterization test stops being
      one. **Nothing is committed to disk now.** Failure paths are asserted *relationally* — call
      `get_summary` twice, once with the catalog failing and once with it absent, and assert the
      two are identical, so a failing catalog must be indistinguishable from one never queried and
      later cosmetic changes move both sides equally. Everything else asserts a *projection* of the
      tree (visible text plus `href`s, cosmetic props dropped) against an inline literal, so the
      expectation is readable in the diff.
      **What it found, and `aio-gather` depends on it: the two-loop structure masks a blanket
      `except`.** Widening *only* the first per-catalog loop's clause to `except Exception:` passed
      every test, because the second loop (`ml_classifications`) still had the narrow clause and
      re-raised. Only widening both — which is exactly what a consolidated `gather` rewrite
      produces — failed. The relational tests therefore do **not** police over-broad swallowing;
      `test_get_summary_propagates_exception_not_in_the_swallow_list` does, and it is the
      load-bearing test for `aio-gather`'s `return_exceptions=True`.
      Two smaller corrections: the section's worry that `get_summary` needed a replay layer was
      overstated — catalog stubs plus five small upstream stubs covered the whole failure matrix —
      and the projection **drops component type**, so a `Div`→`Span` swap with identical text and
      `href` now passes where a snapshot would have caught it. Deliberate trade. `set_table` over a
      real catalog is still not covered.
- [x] `aio-cache-spec` — cache contract tests (keys, TTL, pickle round-trip) — **found five defects in
      today's cache, see F12** — #627 `cache-contract-tests`
- [x] `aio-bench` — fan-out latency harness, records a baseline — #674 `fanout-bench`.
      Shipped as `plans/misc/fanout_bench.py`, next to #667's `gil_bench.py`. It drives the
      **loop shape** over sleep-stubs, not the real `get_summary`, which also pulls in dust maps,
      light-curve fetches and broker links — none of it the fan-out being measured. It therefore
      imports nothing from `ztf_viewer` and can only regress against itself. It also models only
      the **first** of `get_summary`'s two catalog loops, on the argument that the second hits
      `find()`'s `@cache()`, so 9.5s is a floor on today's cost rather than a fair figure for it.
      Baseline: 19 stubs × 0.5s ⇒ **9.522s** serial, against an illustrative `gather` run at
      0.504s. Consequence: this number does **not** discharge `aio-gather`'s acceptance, which
      asks for a cold `get_summary` against real upstreams.
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
- [x] `aio-cache-async` — make `cache()` dispatch on sync vs async, one shared store —
      #637 `cache-async`.
      Follow-up #673 fixed a defect only the async stack could reach: both async client factories
      (here and in `aio-ttlset`'s `unavailable_catalogs`) passed `host` **positionally**, but
      `redis.asyncio.Redis.__init__` takes it keyword-only, unlike the sync `StrictRedis`. Every
      async cache lookup against the redis backend raised `TypeError`, so the viewer page rendered
      empty with all its callbacks 500ing. Latent on master and invisible in production, and the
      existing tests all built their own clients with keywords — which is why none caught it.
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
      blocking threads per process. `aio-offload-threads` was meant to own that number and was
      dropped, so **nothing sizes it**: it stays at its default of 16 until `aio-gather` makes
      fan-out real, which is where the decision now falls — and #681 left it at 16 too; see that
      Progress entry.

**Async I/O** — the payoff
- [x] `aio-httpx` — shared async client, `asyncio.timeout` — #664 `httpx-client`. Landed
      **inert**: nothing called `get_client()` or `async_timeout()` until #665. The single
      `HTTP_TIMEOUT_SECONDS` this section implies was rejected in review — upstreams disagree by
      two orders of magnitude, so `config.py` grew **nine named per-API `httpx.Timeout`
      constants** instead, with `HTTP_DEFAULT_TIMEOUT` left only as a backstop for a call site
      that forgets one. Pan-STARRS is the proof no single default works: connect 10s, read 600s.
      **Five sites that had no timeout at all** are now bounded — a real behaviour change on
      `lc_features`, `model_fit`, `akb` and the FITS proxy, and the values there are judgement
      calls, not measurements. One shared client, not one per API: `httpx.Limits` is per-client,
      so N clients would leave nobody holding a total connection cap for the ~19-way fan-out.
      Also retired the sync `timeout()`'s only caller later, in #668.
- [x] `aio-snad-apis` — ztf_dr, features, model_fit, akb, ztf_ref — #665 `snad-apis-async`. The
      ripple was much wider than the module list here: awaiting `find_ztf_oid` reaches nearly
      every callback in `pages/viewer.py`, plus `search`/`login`/`tags`/`akb_table` and
      `lc_data/plot_data.py`. Three things the plan did not anticipate:
      **`pages/figure.py`'s two routes had to go `async def` too**, not just `lc_csv.py`'s as F5
      assumed, because they await `get_plot_data`. **`get_layout` lost its `@lru_cache`** —
      `lru_cache` on a coroutine function caches the coroutine object, which can only be awaited
      once, so every hit past the first would raise; the inner network calls are still `@cache()`d,
      but Python-side layout assembly is no longer memoized, and no wall-clock number is attached
      to what that costs. And `asyncio.run()`'s teardown shuts down the *object* set as a loop's
      default executor, so the process-wide `_thread_pool` died for every later loop once several
      `TestClient`s shared a pytest run — **test-only**, fixed in `tests/conftest.py`, cannot fire
      on one worker with one loop.
- [x] `aio-conesearch` — cone-search base + per-catalog — #668 `conesearch-async`. Added
      `_ensure_coroutine` in `_base.py`: `find()` is shared between the JSON-API catalogs and the
      astroquery ones that F9 says never convert, so it wraps a sync `_query_region` and passes a
      coroutine one through. Two surprises: **`httpx.Response` has no `.ok`** (`otter.py` used it;
      now `is_success`), and **converting Pan-STARRS reaches past the cone search** — its
      `light_curve()` shares `_panstarrs_request`, so `closest_light_curve` and the
      `/panstarrs/csv/{obj_id}` route went async too. This also retired the per-call
      `ThreadPoolExecutor(max_workers=1)` inside `util.timeout()` — spawned on *every* cone-search
      query, and the one pre-existing violation of the threading rule.
- [x] ~~`aio-offload-threads`~~ — **dropped** (#676, kept for the defect it found). The section
      below is superseded; what it specifies is not going to be built.
      **No bound survives both requirements review set: provably deadlock-free, and free of
      custom concurrency code a reviewer cannot verify.** `asyncio.Semaphore` is correct only by
      convention — `release()` never checks its loop and `acquire()` only checks once it has to
      wait, so it miscounts *silently* rather than raising, and staying correct depends on nobody
      awaiting in the wrong place later. A subclass adding that check is exactly the custom code
      that was declined. `anyio.CapacityLimiter` breaks its own bound across loops (measured: peak
      3 against a limit of 1) and allows only one token per task, so a nested same-upstream
      offload raises in production. `threading.Semaphore` is genuinely thread-safe but blocks a
      pool thread while waiting — the starvation this item existed to prevent. Async limiters are
      loop-scoped by design, so this is not a gap in the ecosystem to wait out.
      **Consequence:** astroquery (`Vizier`, `MOCServerClass`, `Skybot`), alerce, antares and the
      `csfd`/`bayestar` lookups stay on a bare `asyncio.to_thread` sharing one pool, with no
      fairness between them. `aio-gather` sharpens that and now inherits it — if one slow upstream
      starving the pool shows up in practice, the lever is `THREAD_POOL_SIZE`, or per-upstream
      *rate* limiting at a layer that is not an async primitive, not this item.
      **What it did find:** `AlerceQuery.add_prob_class_columns` queries Alerce once per row and
      ran inline on the event loop, outside the `_query_region` path that already had an offload.
      That fix is what #676 became.
- [x] `aio-gather` — concurrent fan-out for `get_summary` and related I/O — #681 `gather`.
      `get_summary`'s two per-catalog loops became one `asyncio.gather(...,
      return_exceptions=True)`, computed once and reused for both passes, as specified;
      `get_metadata`, `find_neighbours`, `get_plot_data`'s neighbour/external light curves, and
      `lc_csv.get_csv`'s per-OID fetches got the same treatment.
      **The cold-`get_summary`-on-real-upstreams number #674 left owed is now measured**: 18.27s
      median (serial, 3 runs) vs 11.71s median (gather, 3 runs), **~1.56x**, OID
      `633207400004730`/`dr24`, all ~19 catalogs, via new `plans/misc/get_summary_bench.py`.
      Caveated hard in the PR: this sandbox cannot reach CDS at all — a plain, non-concurrent
      `requests.get()` to Vizier fails at the socket level, so 7 of 19 catalogs fail fast via
      `CatalogUnavailable` in both arms, and SIMBAD's ~10s timeout dominates most runs, paid
      **once** (absorbed into the concurrent max) after, **serially** (stacked on everything else)
      before — exactly the effect the PR exists to produce. The *shape* of the win is the
      transferable result; the absolute numbers are almost certainly better on a host with full
      CDS reachability.
      **Deviation: `aio-bench` was *not* turned into an assertion**, despite this section's own
      "`aio-bench` becomes an assertion." Decided against: `aio-bench` drives `asyncio.sleep()`
      stubs and imports nothing from `ztf_viewer` (per its own Progress entry), so asserting it
      would only prove `gather` beats a serial loop over sleeps — a language fact needing no test.
      The tests that matter instead pin the real code: `test_get_summary_catalog_fanout_is_concurrent`
      (wall-clock overlap), `test_get_summary_queries_each_catalog_once` (the consolidated gather
      isn't re-run for the ML-classification pass), plus new `tests/pages/test_lc_csv.py` and
      `tests/lc_data/test_plot_data.py`.
      **Found and fixed mid-review: moving the radius lookup broke every page load.** `radii` is
      keyed by the search-radius inputs the layout renders, which don't cover every registered
      catalog; that `KeyError` used to be caught by the per-catalog `try` inside the loop. Pulling
      `radii[catalog]` out into the `gather()` argument list — the natural way to write the
      fan-out — evaluates it *before* the task's own exception handling runs, so the `KeyError`
      escaped the swallow list and raised on every load instead. Fixed by moving the lookup back
      inside the gathered coroutine, guarded by `test_get_summary_skips_catalog_with_no_radius_input`.
      **Both questions `aio-offload-threads` handed down are answered, not resolved.**
      `THREAD_POOL_SIZE` stays at its default of 16 — the PR found no load-bearing reason to change
      it (the bottleneck observed is upstream latency/reachability, not pool contention) but did
      not build the concurrent-multi-page-load test that would actually stress pool *width*, so
      this is a reviewer call recorded here, not a measurement that closes the question. The
      **upstream-hammering risk stays unmitigated**, exactly as the risk table already said: no
      per-upstream bound was built — the plan already rejected the three candidates when dropping
      `aio-offload-threads` — and the PR's own argument is that no in-process bound could have
      covered it anyway, since master plus every `pr<N>` preview share one host IP, so the number
      that matters is per-IP, not per-process. The exposure's *nature* is unchanged; only its
      *timing* moved, from serial to concurrent hits per page load.

**WebSocket**
- [x] `aio-ws` — enable transport (verify deployed proxy config first) — #693 `websocket-transport`.
      **The design section named five `dash.Dash(...)` constructor arguments; four turned out to
      be no-ops.** `websocket_max_workers` was dropped as unreachable: Dash's WS handler
      (`dash/backends/base_server.py`'s `get_callback_executor`) routes only *sync* callbacks to
      that pool, and this app has none — `ztf_viewer/callbacks.py` wraps every registration into a
      coroutine, an invariant `tests/test_callbacks_shim.py` pins, and a grep confirmed nothing
      bypasses it by calling `app.callback` directly. `websocket_allowed_origins` and
      `websocket_inactivity_timeout` were dropped because their computed values were identical to
      Dash's own defaults (`None or []`, and `300000`, respectively) — passing them changed
      nothing. `websocket_callbacks` was deliberately left at its default `False`, so opt-in stays
      per-callback rather than global. **Exactly one value is configured:
      `websocket_heartbeat_interval`.**
      **The heartbeat is the one real decision: 20000ms against Dash's default of 30000ms.**
      Reason is the live 60s proxy read-timeout ceiling this plan diagnosed (see the out-of-band
      entry below): at a 30s heartbeat a single dropped or delayed beat can already exceed the
      window and drop an idle connection, while 20s leaves room to lose one and still land inside
      it. `tests/test_websocket_transport.py::test_heartbeat_interval_is_bounded_below_the_live_proxy_ceiling`
      fails if the interval is ever raised past half the live ceiling — the failure mode it guards
      is silent in production.
      **The design section's origin prose was wrong, not just incomplete, and is corrected below.**
      It said "origins must be set explicitly — the handler rejects on Origin mismatch." Dash's
      `validate_origin` actually accepts a connection if the Origin is on the allowlist **or** if
      the Origin's netloc equals the request's `Host` header. Same-origin connections — production,
      the master build, per-PR preview hosts, and local dev alike — are therefore already allowed
      with an empty allowlist, which is why none is configured. Per-PR preview hosts could not have
      been enumerated in an allowlist anyway, since matching is exact string equality with no
      wildcard support. The property is pinned end-to-end by
      `test_websocket_origin_check_allows_same_origin_and_rejects_cross_origin`, which drives a
      real handshake with the allowlist forced empty and asserts same-origin connects while
      cross-origin is rejected.
      **One callback opted in**: `update_skybot_for_graph_clicked`
      (`ztf_viewer/pages/viewer.py`), chosen for having no cookies and no chained outputs. Every
      other callback still dispatches over HTTP, covered by a fallback test.
      **One of the design section's three accept criteria was not met, and stays outstanding.**
      "Callbacks dispatch over `ws://` in devtools" and "HTTP fallback still functions" were both
      verified live against a locally running app: a callback round-tripped over `ws://`, and a
      disallowed Origin was rejected at handshake with a 403. **"Reconnect after a proxy restart
      works" was never verified** — it requires the live deployment, which this task did not touch.
      The item was merged with that criterion still open; see `## Open questions`.
      **Whether browsers actually use the WS transport at all is now answered: yes.** Earlier
      instrumentation (Resource Timing) suggested browsers silently used HTTP instead — that was a
      **misattribution**, not a real finding: the `_dash-update-component` fetch observed on a
      graph click belonged to `fits-to-show.children`, a sibling callback sharing the same
      `graph.clickData` `Input`, not to skybot; Resource Timing cannot see SharedWorker-initiated
      traffic, so the instrumentation was blind to the actual WS dispatch. Patching
      `MessagePort.prototype.postMessage` (prototype lookup happens at call time, so it intercepts
      the renderer's already-open port) shows one click producing exactly two dispatches:
      `skybot.children` as a `callback_request` through the SharedWorker port, and
      `fits-to-show.children` as an HTTP fetch — zero HTTP requests for skybot. Verified in Firefox
      153. This also corrects an earlier concern: **Safari supports `SharedWorker`**
      (`typeof SharedWorker === "function"`, and one constructs with a working port) — verified in
      Safari 27, alongside Firefox 153. Any note suggesting Safari would silently fall back is wrong.
      **There is no HTTP fallback if a WebSocket connection fails at runtime, but there is a
      capability fallback that keeps the exposure narrow — both confirmed by reading the installed
      `dash-renderer` bundle and `dash-ws-worker.js` directly.** Dispatch computes `useWebSocket =
      !background && (isWebSocketEnabled(config) || cb.callback.websocket &&
      isWebSocketAvailable(config))`, and `isWebSocketAvailable` requires `typeof SharedWorker !==
      'undefined'` — a browser without `SharedWorker` takes the HTTP path cleanly at dispatch time,
      no failed connection, no delay. But a browser that *has* `SharedWorker` and commits to WS
      gets no second chance if the connection then can't be established (a network blocking the
      Upgrade, a proxy dropping it): the worker queues the request and retries the *connection*
      only — `maxRetries: 10`, 1s initial backoff, 30s cap, with jitter — then emits an `ERROR` to
      the renderer; it never re-dispatches the queued request over HTTP. It also runs its own
      heartbeat (~10s ack timeout), closing with code 4000 and reconnecting on anything but a clean
      close (1000) or an inactivity close (4001). **Consequence: an opted-in callback does not
      degrade to HTTP when its WebSocket connection fails at runtime — it hangs, retries for a
      couple of minutes, then errors. The exposed population is modern (`SharedWorker`-capable)
      browsers on networks that specifically block WebSocket upgrades — real, but narrow, not a
      general breakage risk.** This is why a WebSocket opt-in should be justified by actually using
      streaming, not adopted by default — but it is not an argument against opting in where
      streaming buys something real; the planned `get_summary` slice is exactly that trade.
      **Current state:** work in progress (not yet its own PR) removes `websocket=True` from
      `update_skybot_for_graph_clicked`, leaving the transport enabled but with no opted-in
      callback until genuine streaming lands.
      **This partially informs, but does not close, the outstanding "reconnect after a proxy
      restart" criterion**: the worker's reconnect logic demonstrably exists (see above), but it
      has still not been exercised against a live proxy restart. That criterion stays open.
- [x] Thread-pool sizing bumped ahead of `aio-stream` — `THREAD_POOL_SIZE` default raised 16 → 64
      (#697 `raise-pool-sizes`), pinned by a test that both pools actually track the config value
      (#695 `pool-width-bench`). Because `_size_thread_pools` sizes **both** asyncio's default
      executor and anyio's sync-route limiter from that one value, this is up to 128 blocking
      threads per process, not 64 — and roughly four times the simultaneous upstream requests a
      single IP could produce before. `PROCESS_POOL_SIZE` was deliberately left at 2.
      **Decided by the project owner, not measured**: #697 records no production measurement, only
      a consequence check of what the number actually allows — record it as a judgement call.
      Watch for upstream rate-limiting presenting as catalogs looking flaky, not as anything
      obviously pool-related — CDS services are the most exposure-prone (cross-cutting risks
      table).
      **#695 originally also carried a queueing benchmark, written and then dropped before
      review**: its blocking work was `time.sleep`, so its numbers were derivable from its own
      parameters and identical on any machine — measuring nothing about the deployment, the same
      objection the plan already raises against `fanout_bench.py`. Recorded here so nobody rebuilds
      it. **Open question 11 (pool width) is therefore still open** — the only honest route to
      answering it is instrumenting the running deployment, not a synthetic benchmark.
- [ ] `aio-stream` — progressive rendering via `set_props`. **First slice tried and rejected:**
      #696 `stream-catalog-tables` ("Stream per-catalog tables over the WS transport") was opened,
      deployed to a preview, found broken there, and **closed without merging.** It converted the
      ~20 per-catalog `set_table` callbacks so initial fan-out went through one no-`Output`
      `set_props` streaming callback, adding `prevent_initial_call=True` to the per-catalog
      callbacks. **On the live preview only 3 of 19 tables rendered.** Root cause: the fan-out
      iterates 19 catalogs (`catalog_query_objects()`), but only 17 have a table div in the layout
      — `antares` and `gaia-dr2-distances` have none — and a failure in the shared loop hit the
      `finally` block, which cancelled every still-pending task, killing the rest.
      `prevent_initial_call=True` had removed the fallback that would otherwise have made this a
      slow page rather than a blank one. **This is the same defect class already recorded under
      `aio-gather`** above, where a per-catalog `radii` lookup hoisted out of per-task exception
      handling turned a contained `KeyError` into a page-wide failure — the plan predicted this
      shape of bug once already.
      **The rule that came out of it, and governs the remaining slices: stream where it does not
      consolidate independent failure domains; do not where it does.** Per-catalog tables collapse
      ~20 independent callbacks into 1 — a bad trade, and the weakest case for streaming anyway,
      since each table already paints independently as its own callback returns. `get_summary` and
      the light-curve figure are each already a single callback with a single output, so streaming
      them changes nothing about the failure domain. **Only the `get_summary` slice is now planned
      to proceed.**
      **The existing tests passed while 16 of 19 tables were blank in production.** The automated
      suite asserted things like "a fast catalog paints before a slow one finishes" and "a failing
      catalog contributes nothing," but nothing asserted that *all* expected tables populate — a
      partial-render check cannot distinguish "streaming in progress" from "streaming died." What
      was needed, and is still needed for the `get_summary` slice, is a completeness assertion.
      **Salvaged from #696:** the `WebSocketDisconnect` import fix (`starlette` → `fastapi`) landed
      separately as #698.

**Process pool**
- [x] `aio-procpool` — pool lifecycle, spawn-safe — #685 `procpool`. Landed **inert**, like
      `aio-httpx`: nothing calls `run_in_process` until `aio-figures`.
      **Not built through `aio-loop-registry`, contrary to this section — and the plan is wrong
      on that point.** A `ProcessPoolExecutor` isn't loop-affine: it touches nothing on
      `asyncio.get_running_loop()` until a future gets wrapped, so nothing needs the registry's
      protection, and keying it by loop would be actively wrong — a fresh registry entry means a
      fresh set of OS child processes on every new loop, the opposite of what a worker pool is
      for (the same reason `ztf_viewer/__main__.py`'s `_thread_pool` is already one per process,
      not one per loop). `procpool.py` is a plain process-wide singleton behind a
      `threading.Lock` instead. The section's "works under both loop models" framing is also
      moot: Flask was already gone by the time this landed. **Sizing shipped as a flat default
      of 2, not `~cpu_count // workers`** — changed on review, not measured against the plan's
      formula; still env-overridable via `PROCESS_POOL_SIZE`.
      **Built lazily, not at import** — found in review, not anticipated by this section: an
      import-time executor re-runs inside the pool's own children, because spawn re-imports the
      module holding the submitted function. Measured, not assumed: a worker whose module
      imports `procpool` reports `_pool._executor` as `True` under eager construction, `False`
      under lazy. Not a fork bomb (building a `ProcessPoolExecutor` doesn't spawn workers) but
      every child carried a dead executor for nothing, and one `run_in_process` call from such a
      module would have spawned a second generation; `tests/test_procpool.py` pins it against
      regressing.
      **Fork-mode (the Linux container) was not independently verified**, only spawn (macOS) —
      short of the section's "verify locally under spawn and in the Linux container under fork."
      The rest of the accept criteria hold: a killed child raises `BrokenProcessPool` to its own
      awaiter (not a hang) and poisons the executor; `_discard` replaces it — shutdown of the
      broken one now happens outside the lock, so callers asking for the replacement don't queue
      behind it — and the next call gets a working pool, verified with a real `os._exit(1)` child.
- [x] `aio-figures` — matplotlib rendering off-loop, PNG *and* PDF — #686 `figures-procpool`.
      Landed as specified: both formats move into the pool behind one `save_fig` dispatch, and
      the routes reach it via `run_in_process` — `pool.submit()` + `asyncio.wrap_future`, not
      literally `loop.run_in_executor(pool, ...)` as this section wrote, because
      `run_in_executor` doesn't take kwargs and the real call site does; decided in `aio-procpool`.
      **One structural piece this section didn't anticipate**: `plot_data`, `plot_folded_data`
      and `save_fig` moved out of `pages/figure.py` into a new `ztf_viewer/figure_render.py`.
      Reason: under spawn, a worker re-imports the *module* holding the function it was handed,
      and `pages/figure.py` imports `ztf_viewer.app`, which builds the whole Dash app as an
      import side effect — re-running that in every spawned worker was not something to rely on
      being safe. Verified by inspecting `sys.modules` inside a real spawned child: only
      `ztf_viewer`, `figure_render` and `util` load, never `app` or `dash`.
      **The accept criterion's flood measurement is in**, via new `plans/misc/figure_pool_bench.py`
      (4 concurrent renders against a heartbeat coroutine standing in for another page load on the
      same loop): PNG's worst stall drops 38.9ms → 9.6ms (~4x), PDF's drops 30.3ms → 0.6ms
      (~50x), flood wall time roughly unchanged either way — the pool doesn't speed up rendering,
      it moves the GIL contention off the loop. This confirms the section's own mid-review
      correction above: PNG is the format that actually needed the pool, and it shows the larger
      relative win despite being the cheaper render. Pickling was measured too, not just asserted
      cheap: a real 832-observation light curve is 183KB, 1.6ms to dump, 0.7ms to load. No pool
      `initializer=` for pre-warming — cold start is ~525ms once per worker process, judged not
      worth it against "several seconds," which is what would have justified one.
- [x] `aio-profile` — measure the rest; pool only what earns it — #689 `profile-candidates`
      (measurement harness and numbers, no behaviour change), #690
      `vectorize-plot-data-pool-csv` (the two changes the numbers earned).
      **Correction to the design section's framing, found while measuring:** the section's "each
      may be cheaper to leave on a thread" presupposes all four candidates already run on a
      thread. `grep -rn to_thread ztf_viewer/` shows that's true for sites 2 and 3 but **not** for
      sites 1 and 4 — `plot_data`'s loop and `set_figure`'s plotly construction ran fully inline,
      with no offload at all. For those two the question was never thread-vs-process, it was
      "should this be offloaded at all."
      **Per site — only one of four actually moved to the pool.**
      **1. `plot_data`'s per-observation loop — vectorized, not pooled.** `cProfile` found ~50% of
      its time went to building one `astropy.time.Time` per observation just for `.strftime`; one
      batched call replaces all of them, ~10.4–10.7x faster inline (50.9ms→4.8ms at 1,500 obs,
      674.5ms→64.8ms at 20,000 obs), byte-identical output, pinned by
      `tests/lc_data/test_plot_data_vectorized.py` (six deliberate mutations, each caught by the
      test that names that behaviour — an earlier revision's duplicate-implementation oracle was
      dropped in review as no evidence). Pooling the *original*, unvectorized loop did help under a
      6-way 20k-obs concurrent flood (2530ms/67ms gap vs 4157ms/359ms unpooled), but that pooled
      number is still ~40x worse than vectorizing inline — pooling would have solved a problem
      vectorizing removed outright.
      **2. `lc_csv`'s pandas assembly — promoted to `run_in_process`.** Single-call cost is a wash,
      but under concurrent load the pool cuts wall time ~45% and the worst-case event-loop stall
      **~90–200x**, matching `gil_bench.py`'s standing finding that pandas concat/sort holds the
      GIL for real stretches. The pure function moved to a new module, `ztf_viewer/csv_render.py`,
      for the same reason `figure_render.py` exists (`aio-figures`): a spawned worker re-imports
      whatever module holds the submitted function, and `lc_csv.py` itself pulls in the
      astroquery-backed catalog clients. A CI-only timing flake this exposed (a cold pool spawn
      landing inside an unrelated fan-out test's 0.5s budget) was fixed by stubbing that one test's
      pool hop, not by loosening the budget — `3f984ac`.
      **3. `ztf_ref`'s FITS parse — left on a thread; F8 confirmed, sharpened not reversed.**
      Measured against a real proxy payload (38,261 rows / 2.2MB, downloaded during development,
      not `gil_bench.py`'s synthetic 2M-row control) it parses in under 2ms; pickling 2.2MB into a
      child costs more than the parse saves. `gil_bench.py`'s "57ms, negligible" reading of this
      site was ~50x larger than a real reference catalog and so **understated** how cheap the real
      parse is — the conclusion doesn't change, the margin is wider than the table implied.
      **4. `set_figure`'s plotly construction — left inline; blocked outright, not just costed.**
      Its actual return type, `go.FigureWidget`, **cannot be pickled at all** — verified directly,
      plotly's dynamically-built subclass fails pickle's own identity check even within one
      process — so `run_in_process` on it would not perform badly, it would crash. Even the
      picklable proxy (`go.Figure`, not what the function returns) loses 1.6–2.3x on a single call,
      with an inconsistent concurrency benefit.
      **Two costs the steady-state numbers understate, found while landing #690, not #689:** a
      `ProcessPoolExecutor` cold start is **~560ms once per worker** (in the same ballpark as
      `aio-figures`'s own measured ~525ms), amortized and not worth an `initializer=` pre-warm,
      same reasoning as `aio-figures`. More consequentially, `PROCESS_POOL_SIZE`'s flat default of
      2 (`aio-procpool`) is now shared between CSV assembly and figure rendering — measured
      directly, a CSV render queued behind two concurrent PDF renders took 974ms wall time against
      14ms of its own CPU work. This is a genuine queueing risk for the CSV requester, not a
      regression in what promoting site 2 fixed (the event loop still stays free for *other*
      requests); left open rather than resized without production traffic data to justify a
      number — carried into `## Open questions`.

**Cleanup**
- [ ] `aio-cleanup` — drop `requests` and the sync `timeout()`; update docs

**Out-of-band** — deployment side, not PRs in this repo
- [~] Verify which proxy config is live on the deployment host — **diagnosed in full, not yet
      fixed.** The running proxy uses the stock `nginxproxy/nginx-proxy` image; the derived image
      in the ops repo, the only place that would have written the intended timeout snippet, is
      not built or used. The `vhost.d` directory on the deployed proxy is confirmed completely
      empty — no timeout snippet, no per-host file. The effective running configuration contains
      no `proxy_read_timeout`, `proxy_send_timeout`, or `proxy_connect_timeout` directive
      anywhere, so nginx's compiled defaults are live: 60s each. One thing this narrows: the ACME
      `.well-known/acme-challenge` block is already emitted by the stock template into every
      vhost on its own, so the derived image's `default` snippet was redundant — only the
      *timeout* snippet is actually missing. A separate trap worth carrying into the fix: the
      upstream template only emits the `include` line for a vhost's snippet file when that file
      exists at config-generation time, so dropping the snippet in later also requires a config
      regeneration/reload before it takes effect. Fixing this is still the ops-repo work this item
      asks for; it has been diagnosed, not fixed.
      **Live-tested against the dev/preview deployment (`master.ztf.snad.space`), not production —
      a distinction worth keeping precise, since that host resolves to a different machine than
      production and this does NOT clear the production proxy diagnosed above.** A raw HTTP/1.1
      upgrade request to `/_dash-ws-callback` returned `101 Switching Protocols`; a cross-origin
      handshake was rejected with 403; a real callback round-tripped over a WS frame; and an idle
      connection survived past 70 seconds before closing with code 1012 (service restart), **not**
      a timeout. So the 60s `proxy_read_timeout` concern this item raises is not borne out by this
      one observation on this one host — but the ops-side fix has still not been made anywhere, and
      this item stays `[~]`, not checked off.
- [ ] Per-vhost timeouts for the viewer
- [~] Fix the no-op `client_max_body_size` patch — **confirmed as a no-op at the strongest level,
      not yet fixed.** The effective running configuration contains no `client_max_body_size`
      directive anywhere, and `conf.d` holds only the generated `default.conf` — the file the
      patch was supposed to create does not exist on the box at all, matching the ops repo's
      broken shell redirect (`conf:` is docker-compose volume syntax, meaningless inside a shell
      redirect). The setting has never taken effect. Fixing it is still the ops-repo work this
      item asks for.

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
  their sync APIs. *How* each is offloaded differs by what it actually does; see F9. (Bounding
  those offloads per upstream was `aio-offload-threads`, now dropped — they share one pool.)
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
      ├─ aio-golden-callbacks⇢ callback characterization (pure/failure paths only)
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
                                             │        └─ aio-gather   (aio-offload-threads dropped)
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

1. **Confirm which proxy config is actually live. Diagnosed in full, not yet fixed — see the
   Progress list, `[~]`.** The running proxy uses the stock `nginxproxy/nginx-proxy` image; the
   derived `nginx-proxy/Dockerfile` in the ops repo, the only place that would have written
   `/etc/nginx/vhost.d/default_location` and `/etc/nginx/vhost.d/default`, is not built or used.
   The `vhost.d` directory on the deployed proxy is confirmed completely empty. The effective
   running configuration contains no `proxy_read_timeout`, `proxy_send_timeout`, or
   `proxy_connect_timeout` directive anywhere, so nginx's compiled 60s defaults are what's live,
   not the ops repo's intended 1h. This item's original stale-volume-from-an-older-image
   hypothesis was wrong in a more basic way: the derived image was never wired into compose at
   all. One thing this narrows: the ACME `.well-known/acme-challenge` block is already emitted by
   the stock template into every vhost on its own, so the derived image's `default` snippet was
   redundant — only the *timeout* snippet is actually missing. A trap worth carrying into the
   fix: the upstream template only emits the `include` line for a vhost's snippet file when that
   file exists at config-generation time, so dropping the snippet in later also requires a config
   regeneration/reload before it takes effect. The fix itself — build the derived image, or
   manage the `vhost.d` snippets as explicitly mounted files — is still outstanding.
2. **Timeouts matter more after this migration.** nginx's default `proxy_read_timeout` is 60 s
   and the upstream nginx-proxy template sets none. Dash's WebSocket heartbeat defaults to
   30 s, so an idle connection survives on heartbeats alone — but only while heartbeats stay
   enabled and under the timeout. Long timeouts (the ops repo intends 1 h) are comfortable for
   both persistent WS connections and slow catalog fan-out; item 1 is about making sure they
   are actually applied. Prefer a **per-vhost** `vhost.d/<hostname>_location` file, so the
   viewer's timeouts don't ride on a global default shared with every other service behind the
   same proxy.
   **Item 1's finding sharpens this: the 60s default is what's actually live, not the intended
   1h, and that changes `aio-ws`'s prerequisites — see that section.** WebSocket UPGRADE itself
   is unaffected: nginx-proxy's built-in template emits the `$http_upgrade`/`$proxy_connection`
   map and the `Upgrade`/`Connection` headers unconditionally, on the stock image, no derived
   build required. F7 still holds. But the live 60s ceiling is the real constraint in two ways:
   Dash's 30s WS heartbeat default survives it with only a 2x margin, not the comfortable margin
   a 1h timeout would give — `aio-ws` must pin the heartbeat conservatively against the *live*
   config, and setting `websocket_heartbeat_interval` above 60s would silently break idle
   connections. And the same 60s ceiling caps slow HTTP-fallback callbacks: post-`aio-gather`
   cold `get_summary` measured ~11.7s median (`get_summary_bench.py`), but SIMBAD alone is ~10s
   of that and a `usetex` PDF render stacks on top for callbacks that render one — today's margin
   is real but not comfortable.
3. **Re-check the `client_max_body_size` patch. Confirmed as a no-op at the strongest level, not
   yet fixed — see the Progress list, `[~]`.** The effective running configuration contains no
   `client_max_body_size` directive anywhere, and `conf.d` holds only the generated
   `default.conf` — the file the ops repo's `patch-config` service was supposed to create does
   not exist on the box at all. Matches the ops repo's broken shell redirect (`conf:` is
   docker-compose volume syntax, meaningless inside a shell redirect). Unrelated to this
   migration, but adjacent enough to fix while in there; not yet fixed.

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
*(Landed — #679, `tests/pages/test_viewer.py`. **Read the Progress entry before this section:**
the snapshot-and-commit mechanism described below was built, rejected in review as
unmaintainable, and replaced by relational assertions plus an inline projection, with no files
committed to disk. The choice of *what* to characterize — failure paths first, presentation-side
callbacks after, no upstream replay — survived intact and is what the rest of this section is
still good for.)*
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
*(Landed — #674, `plans/misc/fanout_bench.py`. **The assertion this section promises never got
written.** `aio-gather` (#681) explicitly decided against converting this harness into a pytest
assertion — see that Progress entry for why. The harness remains exactly what it always was: a
standalone script that regresses only against itself.)*
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
  future sharing). It also became load-bearing rather than a nicety the moment `aio-gather`
  landed (#681): N users on a popular object still serialize into N identical upstream queries
  without it.
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

### ~~`aio-offload-threads`~~ — Sync-only third parties stay sync, offloaded according to F9

**Dropped — see the Progress entry. Kept below as the record of what was specified; the
per-upstream semaphores and the pool resizing were not built.**
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
*(Landed — #681, branch `gather`. **Read the Progress entry before this section:** the fan-out
itself landed as specified, but the accept criterion below did not — no assertion against
`aio-bench` was written, and that was a deliberate call, not an oversight. The wall-clock number
this section asks for was measured against real upstreams, with caveats about this build's own
network reachability recorded alongside it.)*
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
shows now that `aio-gather` has landed (#681).

### `aio-ws` — Transport enablement
*(Landed — #693, branch `websocket-transport`. Read the Progress entry before this section: four
of the five constructor arguments below turned out to be no-ops and were dropped, only
`websocket_heartbeat_interval` is configured, and the origin claim two bullets down was wrong —
corrected in place below. "Reconnect after a proxy restart works" in the accept criteria was not
verified and is still open. Also read the Progress entry for the later finding that browsers really
do use the WS transport — an earlier Resource Timing-based concern that they silently fell back to
HTTP was a misattribution — and for the corrected fallback story: no HTTP fallback if a WS
connection fails at *runtime*, but a capability check keeps that narrow to browsers that have
`SharedWorker` and are on a network that specifically blocks WebSocket upgrades. Safari supports
`SharedWorker` (verified Safari 27); any note below suggesting otherwise is wrong.)*
- Proxy prerequisites: upgrade support is confirmed, not just handled — nginx-proxy's built-in
  template emits the `$http_upgrade`/`$proxy_connection` map and the `Upgrade`/`Connection`
  headers unconditionally, on the stock image, verified directly against the deployed proxy
  (design note item 1). F7 holds. **What is confirmed and changes what "done" means here:** the
  deployed proxy runs the stock image, not the derived one, and its `vhost.d` directory is
  confirmed empty — the intended 1h timeouts do not exist on the box, and the live
  `proxy_read_timeout` is nginx's compiled 60s default. Dash's 30s WS heartbeat survives that
  with only a 2x margin — pin `websocket_heartbeat_interval` conservatively under the *live* 60s
  ceiling, not the design note's originally-intended 1h. The ops-side fix (design note item 1)
  is diagnosed but not yet applied; re-confirm the timeout is actually fixed on the box before
  relying on a longer one.
- `dash.Dash(..., websocket_callbacks=True, websocket_allowed_origins=[...],
  websocket_max_workers=..., websocket_inactivity_timeout=..., websocket_heartbeat_interval=...)`.
  **Corrected — this section's origin claim was wrong, not merely incomplete:** it is not true
  that "origins must be set explicitly — the handler rejects on Origin mismatch." Dash's
  `validate_origin` accepts a connection if the Origin is on the allowlist **or** if the Origin's
  netloc equals the request's `Host` header, so ordinary same-origin connections — production, the
  master build, per-PR preview hosts, local dev — are already allowed with an empty allowlist.
  #693 configures no allowlist at all and only `websocket_heartbeat_interval`; the other three
  arguments here (`websocket_max_workers`, `websocket_inactivity_timeout`,
  `websocket_allowed_origins`) turned out to be no-ops — see the Progress entry for why each one
  specifically doesn't move anything.
- Consider enabling per-callback (`websocket=True`) first rather than globally, so the HTTP
  path stays as a fallback while we gain confidence. **Landed this way**: only
  `update_skybot_for_graph_clicked` opts in; `websocket_callbacks` stays at its default `False`.
- **Accept:** callbacks dispatch over `ws://` in devtools **(met, verified live outside devtools
  via a raw WS client)**; reconnect after a proxy restart works **(not verified — requires the
  live deployment; outstanding, see `## Open questions`)**; HTTP fallback still functions with
  `websocket_callbacks=False` **(met)**.

### `aio-stream` — Progressive rendering
*(First slice tried and rejected — #696 `stream-catalog-tables`, closed without merging. Read the
Progress entry before this section for the full story: converting the per-catalog tables collapsed
~20 independent failure domains into one, and a shared-loop failure that hit the `finally` block
took down every not-yet-completed table with it — only 3 of 19 rendered on the live preview. **The
rule that came out of it and now governs this section: stream where it does not consolidate
independent failure domains; do not where it does.** That rules the per-catalog tables item below
out entirely — it is superseded, kept here only as a record of what was tried — and leaves
`get_summary` and the light-curve figure as the two candidates worth pursuing, since each is
already a single callback with a single output and streaming changes nothing about its failure
domain.)*

Depends on `aio-ws` (landed, #693) for the transport; the opted-in callback there
(`update_skybot_for_graph_clicked`) is single-shot, so nothing here could be checked against a real
streaming callback until #696 — which is where `dash/backends/ws.py:44`'s `is_shutdown`
requirement below got its first real exercise, and where a completeness assertion (not just a
partial-render check) turned out to be the test that actually matters: #696's own tests passed
while 16 of 19 tables were blank on the live preview.

Now the actual UX change. Convert the slow, fan-out callbacks to no-output `set_props`
streaming so results paint as they arrive instead of in one blocking batch:
- ~~the per-catalog tables (`set_tables`, `ztf_viewer/pages/viewer.py:2046`) — today ~20
  independent callbacks each waiting on one upstream; with `set_props` they can be one
  streaming callback that pushes each table as its `gather` task completes~~ — **superseded: tried
  as #696 and rejected.** Collapsing ~20 independent per-catalog callbacks into one streaming
  callback is the weakest case for streaming anyway (each table already paints independently as
  its own callback returns) and the worst case for the failure-domain rule above. Not proceeding.
- `get_summary` — push rows incrementally, so the page is useful before Vizier answers. **The only
  slice now planned to proceed.**
- the light-curve figure — paint ZTF DR photometry immediately, then push external
  (antares/gaia/panstarrs) traces as they land.
- Per `dash/backends/ws.py:44`, any persistent/streaming callback **must** be `async def` and
  **must** check `ctx.websocket.is_shutdown` in its loop, or it leaks work after disconnect. #696
  built exactly this (`_find_table_for_stream` catching per-catalog exceptions, a `finally` that
  cancels in-flight tasks) — the design held up; it was the *scope* (per-catalog tables) that was
  wrong, not the streaming mechanics.
- **Accept:** with an artificially delayed catalog, the rest of the page renders without
  waiting; closing the tab mid-load stops server-side work (assert via logs); **and, learned from
  #696: a completeness assertion that every expected element actually populates** — a
  partial-render check alone cannot distinguish "streaming in progress" from "streaming died."

---

## Stack: Process pool — CPU-bound offload

Runs after the flip. Nothing here depends on the backend — the routes can `run_in_executor`
either way — so it can be pulled earlier if convenient. Do it **after** measuring — the point of F8 is that this list is short, and a process pool costs pickling and
memory.

### `aio-procpool` — Pool infrastructure
*(Landed — #685, branch `procpool`. **Read the Progress entry before this section:** the bullet
below routing pool lifecycle through `aio-loop-registry` was rejected in review as the wrong call
— a `ProcessPoolExecutor` isn't loop-affine, so keying it by loop would spawn a fresh set of child
processes per loop rather than reuse one process-wide pool — and sizing shipped as a flat default
of 2, not `cpu_count // workers`.)*
- A `ProcessPoolExecutor`, one per worker process, sized ~`cpu_count // workers`, created and
  torn down through `aio-loop-registry`'s registry so it works under both loop models.
- macOS/spawn safety: worker functions must be importable module-level functions with no
  captured state, and every entry point stays behind `if __name__ == "__main__":`
  (repo convention). Verify locally under spawn *and* in the Linux container under fork.
- **Accept:** pool survives worker reload; no zombie processes; a crash in a child surfaces
  as a 500 rather than a hang.

### `aio-figures` — Figure rendering — **both PDF and PNG**
*(Landed — #686, branch `figures-procpool`. Built as specified, including the flood measurements
the accept criterion below asks for; see the Progress entry for the one thing this section didn't
anticipate — the renderers moving into a new `ztf_viewer/figure_render.py` so a spawned worker
doesn't re-import `ztf_viewer.app` and build the whole Dash app.)*
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
*(Landed — #689 `profile-candidates` measured, #690 `vectorize-plot-data-pool-csv` applied the
two changes the numbers earned. See the Progress entry for the per-site verdicts and numbers.
**"Each may be cheaper to leave on a thread" below presupposes all four are already on a thread —
wrong for two of them:** `plot_data`'s loop and `set_figure`'s plotly construction ran fully
inline, no offload at all, until #689 found that by grepping for `to_thread`. For those two the
real question was whether to offload at all, not thread-vs-process.)*
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
**Superseded by #689: the 2M-row control overstates this site's real cost, in the cheap direction.**
A real reference-catalog payload downloaded during development is 38,261 rows / 2.2MB — ~50x
smaller than this table's control — and parses in under 2ms, not 57ms scaled down. The verdict
(leave on thread) doesn't change; the margin for it is wider than this table implies.

**Superseded by #689/#690's per-site measurements — only one of four actually moved to a
process.** This paragraph's "the destination for this work is a process" reads, in hindsight, as
an overclaim from the gil_bench table alone, without having measured the pool round trip
(pickling, child-process cost) against each site. Once that round trip was measured: `lc_csv`'s
pandas assembly (site 2) promoted to `run_in_process` as this paragraph predicted. The other
three did not — `plot_data`'s loop (site 1) was vectorized instead of pooled (~10x faster inline,
and pooling the *original* loop was still ~40x worse than the vectorized inline version); the
FITS parse (site 3) stayed on a thread, sharpened above; and `set_figure`'s plotly construction
(site 4) stayed inline because its `go.FigureWidget` return type cannot be pickled at all, a hard
block the gil_bench table had no way to surface — it only measures CPU time, not picklability.
The one real exception this paragraph named, the LaTeX/PDF path, still holds — see the correction
under `aio-figures`. See the Progress entry for the full numbers and reasoning per site.

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
  sync-only third parties are offloaded explicitly with a bare `asyncio.to_thread` (the bounded
  version was dropped), so what the shim still wraps is mostly trivial presentation callbacks — for which a thread hop
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
| Golden snapshots recorded through a colliding memory cache, baking a wrong value in as the spec (F12.1) | **Moot — #679 records no snapshots at all.** Nothing is committed to disk, so there is no recording step for a colliding keyspace to poison; the stubbed calls it asserts over are not `@cache()`-decorated either. The hazard would return the moment anyone reintroduces a recorded fixture |
| The cache rewrite silently preserves one of today's defects (F12) | The five defects are recorded as named `xfail`s in `aio-cache-spec`; `aio-cache-sync`'s accept criterion is that F12.1–F12.4 turn XPASS, so preserving a bug fails the criterion rather than passing quietly |
| `aio-shim` misses the 19 loop-registered `set_table` callbacks (F1a′) | The invariant asserts over all 57 registrations, not the 39 source sites, so a missed loop fails CI |
| Static assets 404 after the flip (F2) | `aio-golden-http` asserts `/static/js9/js9.min.js` and `/static/img/logo.svg` return 200 — landed, #634 |
| Concurrent fan-out hammers upstreams that previously saw serialized traffic | **Live and unmitigated as of `aio-gather` (#681)**, and the exposure grew with #697 — `aio-offload-threads`, whose job this was, was dropped first. What is left is the `unavailable_catalogs` circuit breaker (which trips *after* an upstream is already unhappy) and `THREAD_POOL_SIZE` as a blunt global ceiling, raised from 16 to 64 by #697 (a judgement call, not a measurement) — up to 128 blocking threads per process once anyio's separate limiter is counted, roughly 4x the simultaneous upstream requests one IP could produce before. The concrete exposure is CDS: SIMBAD bans an IP for a minute above 10 queries/s and for an hour above 400 in 10s, and VizieR, MOCServer and Sesame share that origin. Note we are one IP for every user, and master plus each `pr<N>` preview are separate containers on one host, so the figure that matters is per-IP, not per-process — no in-process bound could have covered it anyway, the same argument #681 made when leaving it unmitigated. Not yet exercised under real production traffic — prod stays on the Flask build until the whole plan lands. If this bites, rate limiting belongs outside the async layer; watch for it presenting as catalogs looking flaky rather than as anything obviously pool-related |
| Cache stampede amplified by concurrency | Single-flight in the cache sub-stack — this becomes load-bearing, not a nicety |
| WebSocket dropped by a proxy (F7) | nginx-proxy handles upgrades natively; residual risk is timeouts and the the proxy design note config discrepancy — `aio-ws` (#693) pins the heartbeat under the live 60s ceiling and rolled out per-callback with HTTP retained as fallback. **Reconnect-after-proxy-restart, the design section's own accept criterion for this risk, was never verified against the live deployment** — see `## Open questions`. Live-tested against the dev/preview host only (a different machine than production): a raw upgrade returned 101, an idle connection survived past 70s before closing 1012 (service restart, not a timeout) — encouraging, but not a substitute for testing the production proxy |
| An opted-in WebSocket callback has no HTTP fallback if its connection fails at *runtime* | A capability check (`isWebSocketAvailable`, requires `typeof SharedWorker !== 'undefined'`) keeps this narrow: browsers without `SharedWorker` never attempt WS and dispatch over HTTP cleanly. But a `SharedWorker`-capable browser that commits to WS and then can't establish the connection (a network blocking the Upgrade) retries the connection for ~2 minutes (`maxRetries: 10`, 1s–30s backoff) and then errors — it never falls back to HTTP. Mitigation is scope, not code: only opt a callback in when streaming buys something real (`get_summary`), not by default |
| Static assets served with weaker caching after the flip (the `/static` design note) | `aio-golden-http` records today's cache headers for `/static/js9/js9.min.js`; set them explicitly on the mount |
| Process pool memory blowup | `aio-procpool` sizing; compare container RSS before/after |
| CSV assembly (`aio-profile`/#690) queues behind figure renders on the shared 2-worker pool | Not yet mitigated — measured directly, a CSV render can sit ~1s behind two concurrent PDF renders; `PROCESS_POOL_SIZE` left at its default of 2 for lack of production traffic data to size it against, see `## Open questions` |
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
2. ~~**How much of the process-pool stack is real?**~~ **Answered by `aio-profile` (#689/#690):
   less than assumed.** `aio-figures` was justified as expected. Of the other four candidates,
   only one — `lc_csv`'s pandas assembly — earned promotion to the pool; the FITS parse stays on
   a thread, `set_figure`'s plotly construction stays inline (blocked outright, its return type
   isn't picklable), and `plot_data`'s loop was vectorized rather than pooled. The pool was not
   built for `aio-profile`'s sake alone, as this question originally cautioned against.
3. **Do we keep an HTTP fallback permanently** (`aio-ws` per-callback) or commit fully to WebSocket
   transport? Depends on what the deployment proxies tolerate. **Still open after `aio-ws`
   (#693):** the PR opted in exactly one callback and left HTTP as the working path for
   everything else, deliberately, so this question carries forward unchanged into `aio-stream`.
   **Sharper now, both ways.** A capability check (`isWebSocketAvailable`) means a browser without
   `SharedWorker` always dispatches over HTTP regardless of this decision — that population never
   sees WS either way. But a `SharedWorker`-capable browser that opts into WS and then can't
   establish the connection gets no HTTP fallback at runtime, only a multi-minute retry-then-error
   (see the WebSocket Progress entry and the cross-cutting risks table). So "keep the HTTP fallback
   permanently" cannot mean "as a runtime safety net for a failed WS connection" — that safety net
   does not exist and cannot be added without upstream Dash changes. The question that remains is
   narrower: which callbacks are worth the narrow no-runtime-fallback exposure in exchange for
   streaming, which is exactly the test #696's failure applied — and failed — to the per-catalog
   tables, and which `get_summary` is expected to pass.
4. **Is the `dr7` / legacy-URL behaviour** in `app_select_by_url` worth preserving verbatim
   through the route port, or can it be dropped now? **Half answered:** the port kept it verbatim
   (`ztf_viewer/__main__.py:358`), so nothing was lost while this went undecided. Whether to drop
   it is still open, and is a product call rather than a porting one.
5. ~~**`websocket_max_workers` sizing** matters only if any sync callback survives; if `aio-shim`'s
   invariant holds it should be irrelevant — worth asserting.~~ **Answered by `aio-ws` (#693):
   irrelevant, as this question predicted.** The invariant holds — a grep confirmed nothing
   bypasses the shim — so the argument was dropped from the constructor call entirely rather than
   passed and left unreachable.
6. ~~**Does the foundations stack block the start, or run alongside?**~~ **Answered: it runs
   alongside.** The replay layer that was the long pole is gone, so nothing in foundations blocks
   anything else. `aio-golden-http` landed alongside the prep stack (#634), and `aio-golden-callbacks`
   (#679) and `aio-bench` (#674) landed independently much later, as predicted — foundations is
   now complete.
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
9. **Is `PROCESS_POOL_SIZE`'s flat default of 2 (`aio-procpool`) still right now that two
   workloads share it?** Open, not answered. `aio-figures` routed PNG/PDF rendering through it;
   `aio-profile` (#690) added CSV assembly. Measured directly: a CSV render can queue ~1s behind
   two concurrent PDF renders on the default 2-worker pool, against ~14ms of its own CPU work.
   The PR that found this made a case that 2 is too small but left it unchanged for lack of
   production traffic data (request-rate ratio of CSV downloads to figure renders, real
   concurrent-user counts) to pick a number with. Bumping it isn't free — more child-process
   memory per worker.
10. **Reconnect after a proxy restart** (`aio-ws`'s own accept criterion) — **not answered.**
    #693 verified two of its three accept criteria live (dispatch over `ws://`, HTTP fallback);
    this one requires the actual deployment and was out of scope for the sandbox it was built in.
    Carries forward as an outstanding check, not a completed item — see the Progress entry and the
    cross-cutting risks table. **Partially informed but still not closed**: the worker's reconnect
    logic demonstrably exists (exponential backoff, `maxRetries: 10`, jitter, verified by reading
    `dash-ws-worker.js` directly) and a dev/preview-host connection has been observed surviving 70+
    idle seconds before a *service restart* closed it with code 1012 — but that is not the same
    event as a *proxy* restart, and the test was against the dev/preview host, not production.
    Still requires a live proxy-restart test against the production deployment.
11. **`THREAD_POOL_SIZE`'s default** (raised 16 → 64 by #697 as a judgement call, pinned by #695 —
    not a measurement, see the Progress entry) **gets sharper now that `aio-stream` is next.**
    `aio-ws` (#693) opted in exactly one callback, and it is single-shot — no new load landed on
    the default executor by that PR. `aio-stream`'s first slice (#696) would have been the first
    thing to actually stress pool width, but it was rejected on a correctness defect (the
    per-catalog collapse) before pool width came into play at all — so this question is still
    exactly as open as before, just against a default of 64 instead of 16. **#695's own attempt to
    measure it (a `time.sleep`-driven queueing benchmark) was written and dropped before review**:
    its numbers were derivable from its own parameters and identical on any machine, measuring
    nothing about the deployment. The only route to a real answer is instrumenting the running
    deployment; the `get_summary` slice of `aio-stream` is where that pressure will actually show
    up, and it should answer this with a number, not inherit it unmeasured a third time.

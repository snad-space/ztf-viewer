"""Drives a *running* instance of the app over HTTP and reports latency percentiles.

Every other script in `plans/misc/` measures a loop shape or a function in-process, over stub
objects or synthetic payloads -- useful for isolating one mechanism, but none of them go through
uvicorn, the ASGI app, or the process/thread pools as a real client would. This script is the one
that does: it points `httpx` at `--base-url` and drives real concurrent HTTP traffic, so the
plan's concurrency claims (one uvicorn worker under real fan-out, the figure/CSV process pool
sharing, an unrelated request not degrading under a flood) stay checked against the deployed
shape of the app rather than a model of it. It is not a test: it prints numbers and makes no
assertion, same posture as the rest of `plans/misc/`.

Scenarios:

  - `summary`   -- the viewer page's per-catalog fan-out. `get_summary`
                   (`ztf_viewer/pages/viewer.py`) is a `websocket=True` Dash callback with no
                   Output; a plain HTTP client (this script included) gets Dash's batched HTTP
                   fallback -- one `_dash-update-component` response with the final summary,
                   not the progressive `set_props` pushes a browser's WS transport would see.
                   The callback's own id and input shape are read from `/_dash-dependencies`
                   rather than hardcoded, so a change to the callback's signature shows up as a
                   clear lookup failure here instead of a silently wrong request. The ~19 catalog
                   names it fans out over (`ztf_viewer/catalogs/conesearch/__init__.py`) are not
                   discoverable over HTTP, so they are listed below and kept in sync by hand --
                   same tradeoff `fanout_bench.py` documents for its own catalog count.
  - `figure-png`/`figure-pdf` -- `GET /{dr}/figure/{oid}[?format=pdf]`, matplotlib Agg / PGF+LaTeX.
  - `csv`       -- `GET /{dr}/csv/{oid}`, the pandas assembly path.
  - `flood`     -- the highest-value scenario: floods the figure/CSV process pool (default size
                   2, shared by both) with concurrent PDF renders while separately sampling an
                   unrelated cheap endpoint (`/health`) on a fixed cadence, then reports that
                   endpoint's latency during the flood against a quiet baseline. This is the
                   plan's own repeated claim -- a CSV render measured queueing ~1s behind two
                   concurrent PDF renders on the default pool -- checked live rather than modeled.

What this does not model: browser-side WS transport for `summary` (see above); realistic upstream
response-time variance (every request goes to whatever `--base-url` actually has behind it, cold
or warm); and it is not a stress test -- default concurrency is small enough to run against a
laptop-sized preview deployment without becoming the thing that trips CDS's own rate limit (see
the plan's cross-cutting risks table).

Point this at a local run or a `pr<N>` preview -- never at production.

Run: python plans/misc/load_test.py --base-url http://localhost:8050 --scenario flood
Run: python plans/misc/load_test.py --scenario summary --concurrency 8 --requests 24
Run: python plans/misc/load_test.py --scenario all --concurrency 4 --requests 12
"""

import argparse
import asyncio
import statistics
import time

import httpx

DEFAULT_BASE_URL = "http://localhost:8050"
# The app's own placeholder example (ztf_viewer/__main__.py), also used by
# tests/test_golden_http.py, tests/catalogs/test_ztf_ref.py and plans/misc/get_summary_bench.py.
DEFAULT_OID = "633207400004730"
DEFAULT_DR = "dr24"
DEFAULT_RADIUS_ARCSEC = 10.0

# query_name strings registered in ztf_viewer/catalogs/conesearch/__init__.py, normalized the
# same way _BaseCatalogQuery.__new__ does (name.replace(" ", "-").lower()). Not discoverable over
# HTTP -- the summary callback's inputs only ever carry whatever radii the caller supplies, and a
# radius omitted for a catalog name makes get_summary skip that catalog outright (a KeyError while
# building its find() call, caught as "not found") -- so an incomplete list here quietly narrows
# the fan-out instead of erroring loudly. Keep in sync with that module by hand.
_CATALOG_QUERY_NAMES = [
    "Alerce",
    "ATLAS",
    "Antares",
    "Astrocats",
    "Otter",
    "Astro-COLIBRI",
    "Fink",
    "Gaia DR2 Distances",
    "Gaia DR3",
    "Gaia EDR3 Distances",
    "GCVS",
    "OGLE",
    "Pan-STARRS DR2 Stacked",
    "SDSS DR16 Quasars",
    "Simbad",
    "SPICY",
    "Transient Name Server",
    "VSX",
    "ZTF Periodic",
]


def _normalize_catalog_name(name):
    return name.replace(" ", "-").lower()


def _percentiles(samples):
    if not samples:
        return {}
    ordered = sorted(samples)
    quantiles = statistics.quantiles(ordered, n=100, method="inclusive") if len(ordered) > 1 else ordered * 100
    return {
        "min": ordered[0],
        "p50": quantiles[49] if len(ordered) > 1 else ordered[0],
        "p90": quantiles[89] if len(ordered) > 1 else ordered[0],
        "p99": quantiles[98] if len(ordered) > 1 else ordered[0],
        "max": ordered[-1],
    }


def _print_stats(label, samples, errors):
    stats = _percentiles(samples)
    if not stats:
        print(f"{label}: no successful samples ({errors} errors)")
        return
    print(
        f"{label}: n={len(samples)} errors={errors}  "
        f"min={stats['min'] * 1000:7.1f}ms  p50={stats['p50'] * 1000:7.1f}ms  "
        f"p90={stats['p90'] * 1000:7.1f}ms  p99={stats['p99'] * 1000:7.1f}ms  max={stats['max'] * 1000:7.1f}ms"
    )


async def _timed_request(client, method, url, **kwargs):
    start = time.perf_counter()
    try:
        response = await client.request(method, url, **kwargs)
        response.raise_for_status()
    except httpx.HTTPError:
        return None
    return time.perf_counter() - start


async def _run_many(client, method, url, concurrency, n_requests, **kwargs):
    samples = []
    errors = 0
    semaphore = asyncio.Semaphore(concurrency)

    async def one():
        nonlocal errors
        async with semaphore:
            elapsed = await _timed_request(client, method, url, **kwargs)
        if elapsed is None:
            errors += 1
        else:
            samples.append(elapsed)

    await asyncio.gather(*(one() for _ in range(n_requests)))
    return samples, errors


async def _fetch_summary_callback_spec(client):
    """Look up get_summary's callback id and input shape from the live app's own dependency list,
    rather than hardcoding a callback id that changes with the Input/Output signature."""
    response = await client.get("/_dash-dependencies")
    response.raise_for_status()
    for entry in response.json():
        if entry.get("websocket") and entry.get("no_output"):
            return entry
    raise RuntimeError("no websocket, no-Output callback found in /_dash-dependencies -- is this get_summary?")


def _summary_request_body(spec, oid, dr, radius_arcsec):
    radius_ids = [{"index": _normalize_catalog_name(name), "type": "search-radius"} for name in _CATALOG_QUERY_NAMES]
    radius_values = [radius_arcsec] * len(radius_ids)
    # dep["id"] is always a string (Dash's `stringify_id`) -- a plain component id like "oid", or
    # the wildcard's own JSON-ish rendering for a pattern-matching Input. Values for the wildcard
    # inputs are the concrete radius_ids/radius_values built above; scalar inputs are looked up by
    # component id.
    scalar_values = {
        "oid": oid,
        "dr": dr,
        "different_filter_neighbours": None,
        "different_field_neighbours": None,
    }
    inputs = []
    for dep in spec["inputs"]:
        if "search-radius" in dep["id"]:
            # The wildcard input's own "id" here must be the concrete component-id list a real
            # layout would render, not the ALL-wildcard placeholder /_dash-dependencies reports.
            value = radius_ids if dep["property"] == "id" else radius_values
            inputs.append({"id": radius_ids, "property": dep["property"], "value": value})
        else:
            inputs.append({"id": dep["id"], "property": dep["property"], "value": scalar_values[dep["id"]]})
    return {
        "output": spec["output"],
        "outputs": [],
        "inputs": inputs,
        "state": spec.get("state", []),
        "changedPropIds": ["oid.children"],
    }


async def scenario_summary(client, args):
    spec = await _fetch_summary_callback_spec(client)
    body = _summary_request_body(spec, args.oid, args.dr, args.radius_arcsec)

    samples, errors = await _run_many(
        client, "POST", "/_dash-update-component", args.concurrency, args.requests, json=body
    )
    print(f"\n=== summary: viewer page fan-out over {len(_CATALOG_QUERY_NAMES)} catalogs ===")
    _print_stats("get_summary (HTTP fallback, batched)", samples, errors)


async def scenario_figure(client, args, fmt):
    url = f"/{args.dr}/figure/{args.oid}" + ("?format=pdf" if fmt == "pdf" else "")
    print(f"\n=== figure-{fmt}: GET {url} ===")
    samples, errors = await _run_many(client, "GET", url, args.concurrency, args.requests)
    _print_stats(f"figure {fmt}", samples, errors)


async def scenario_csv(client, args):
    url = f"/{args.dr}/csv/{args.oid}"
    print(f"\n=== csv: GET {url} ===")
    samples, errors = await _run_many(client, "GET", url, args.concurrency, args.requests)
    _print_stats("csv", samples, errors)


async def _heartbeat_health(client, stop_event, samples, errors_box):
    """Samples /health on a fixed cadence -- stands in for "an unrelated page load" while the
    flood below occupies the process pool."""
    while not stop_event.is_set():
        elapsed = await _timed_request(client, "GET", "/health")
        if elapsed is None:
            errors_box[0] += 1
        else:
            samples.append(elapsed)
        await asyncio.sleep(0.2)


async def scenario_flood(client, args):
    """Floods the figure process pool with concurrent PDF renders (the slower, LaTeX-backed
    format, so the pool stays busy longer) while sampling /health throughout, then compares
    against a quiet baseline -- the plan's own "CSV queues behind concurrent PDF renders on the
    shared pool" claim, checked from outside the process rather than measured in-process.
    """
    print(f"\n=== flood: baseline /health, no contention (n={args.requests}) ===")
    baseline_samples, baseline_errors = await _run_many(client, "GET", "/health", 1, args.requests)
    _print_stats("/health (quiet)", baseline_samples, baseline_errors)

    print(f"\n=== flood: {args.concurrency} concurrent PDF renders + /health sampled throughout ===")
    stop_event = asyncio.Event()
    health_samples = []
    health_errors = [0]
    heartbeat_task = asyncio.create_task(_heartbeat_health(client, stop_event, health_samples, health_errors))

    figure_url = f"/{args.dr}/figure/{args.oid}?format=pdf"
    flood_samples, flood_errors = await _run_many(client, "GET", figure_url, args.concurrency, args.requests)

    stop_event.set()
    await heartbeat_task

    _print_stats("figure pdf (under flood)", flood_samples, flood_errors)
    _print_stats("/health (under flood)", health_samples, health_errors[0])

    print(f"\n=== flood: CSV queued behind the same PDF flood (n={min(4, args.requests)}) ===")
    csv_url = f"/{args.dr}/csv/{args.oid}"
    flood2_task = asyncio.create_task(_run_many(client, "GET", figure_url, args.concurrency, args.requests))
    csv_samples, csv_errors = await _run_many(client, "GET", csv_url, 1, min(4, args.requests))
    await flood2_task
    _print_stats("csv (under PDF flood)", csv_samples, csv_errors)


SCENARIOS = {
    "summary": scenario_summary,
    "figure-png": lambda client, args: scenario_figure(client, args, "png"),
    "figure-pdf": lambda client, args: scenario_figure(client, args, "pdf"),
    "csv": scenario_csv,
    "flood": scenario_flood,
}


async def _run(args):
    scenarios = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    timeout = httpx.Timeout(args.timeout)
    async with httpx.AsyncClient(base_url=args.base_url, timeout=timeout) as client:
        print(f"base_url={args.base_url} oid={args.oid} dr={args.dr} concurrency={args.concurrency}\n")
        for name in scenarios:
            await SCENARIOS[name](client, args)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="local run or pr<N> preview, never production")
    parser.add_argument("--scenario", choices=[*SCENARIOS, "all"], default="all")
    parser.add_argument("--concurrency", type=int, default=4, help="simultaneous in-flight requests")
    parser.add_argument("--requests", type=int, default=12, help="total requests per scenario")
    parser.add_argument("--oid", default=DEFAULT_OID)
    parser.add_argument("--dr", default=DEFAULT_DR)
    parser.add_argument("--radius-arcsec", type=float, default=DEFAULT_RADIUS_ARCSEC)
    parser.add_argument("--timeout", type=float, default=60.0, help="per-request httpx timeout, seconds")
    args = parser.parse_args()

    asyncio.run(_run(args))


if __name__ == "__main__":
    main()

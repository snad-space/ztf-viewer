"""`aio-profile`: for each F8 candidate, does moving it further -- onto the process pool --
earn its pickling and child-process memory cost, over what it costs (or doesn't cost) today?

Four sites, per the plan:

  1. `ztf_viewer.lc_data.plot_data.plot_data`     -- per-observation python loop
  2. `ztf_viewer.pages.lc_csv._dfs_to_csv`         -- pandas concat/sort/to_csv
  3. `ztf_viewer.catalogs.ztf_ref._parse_fits`     -- astropy FITS parse
  4. the plotly figure construction inside `set_figure` (`ztf_viewer/pages/viewer.py`)

Sites 2 and 3 are already on `asyncio.to_thread`. Sites 1 and 4 are not offloaded at all today --
`grep to_thread ztf_viewer/` turns up neither `plot_data`'s loop nor `set_figure`'s plotly build,
they run inline in the coroutine. That is a correction to this section's framing, not just a
footnote: for those two, "promote to a process" is being asked of code that currently blocks the
loop directly, with no intermediate thread hop to beat.

Each site gets the same three numbers, real function against real `ztf_viewer.procpool.run_in_process`
and `asyncio.to_thread` (not simulated -- pickling both the call arguments and the return value is
included, since that is exactly where a DataFrame- or FITS-sized payload can lose):

  - single-call latency: inline vs thread vs process, best-of-N, at a realistic input size.
  - concurrent flood: N simultaneous calls, thread vs process, both total wall time and the worst
    gap in an unrelated heartbeat coroutine on the same loop (technique from `figure_pool_bench.py`)
    -- the actual question a page load cares about is "did this stall other requests", not the
    wall clock of one call in isolation.

Input sizes are reasoned, not measured, with one exception: the reference-catalog FITS payload.
`_parse_fits`'s synthetic bytes reproduce the row count and column dtypes of a real proxy response
downloaded during this benchmark's development
(`https://fits.ztf.snad.space/products/ref/000/field000633/zr/ccd07/q4/ztf_000633_zr_c07_q4_refpsfcat.fits`,
38,261 rows / 2.2 MB) -- `gil_bench.py`'s 2M-row control was ~50x larger than this real one. The
light-curve sizes for sites 1, 2 and 4 (single-oid observation counts, oid-group counts) are
estimates from typical ZTF DR cadence and are flagged as such in the PR description; they are not
pulled from a real API response.

Also checked here, not in `gil_bench.py`: whether `set_figure`'s actual return type survives the
trip at all. It doesn't -- `plotly.graph_objects.FigureWidget` fails to pickle even within a
single process (a plotly quirk: its dynamically-built class fails the `is` identity check pickle
needs), so a naive `run_in_process(set_figure, ...)` would not perform badly, it would crash. The
figure-construction benchmarks below build a plain `go.Figure` instead -- the closest picklable
proxy -- and time the `go.FigureWidget` wrap as a separate, local-only step.

Run: python plans/misc/profile_candidates_bench.py
Run: python plans/misc/profile_candidates_bench.py --n-concurrent 3 --repeats 3
"""

import argparse
import asyncio
import io
import sys
import time
from pathlib import Path

# Run as a script, `ztf_viewer` would otherwise resolve through the venv's editable-install
# pointer rather than this checkout -- put this repo root first, matching get_summary_bench.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from astropy.io import fits
from astropy.table import Table
from astropy.time import Time

from ztf_viewer.catalogs.ztf_ref import _parse_fits
from ztf_viewer.lc_data.plot_data import MJD_OFFSET, plot_data
from ztf_viewer.pages.lc_csv import _dfs_to_csv
from ztf_viewer.procpool import run_in_process, shutdown_pool
from ztf_viewer.util import ABZPMAG_JY, FILTERS_ORDER, LN10_04, immutabledefaultdict

LATENCY_REPEATS = 5

# One real oid's light curve is hundreds to a few thousand points over ZTF's ~8-year baseline at
# a few-day cadence per filter. "typical" is one moderately-sampled oid; "busy" stands in for
# either an unusually long baseline or the N-way gather across several neighbour oids landing in
# one `plot_data` call's shadow -- see the module docstring, these two are estimates.
N_OBS_TYPICAL = 1_500
N_OBS_BUSY = 20_000


# ---------------------------------------------------------------------------------------------
# Site 1 candidate: a numpy-vectorized rewrite of `plot_data`'s per-observation loop, benchmarked
# here only -- it does not touch `ztf_viewer/`. If the numbers below justify it, this becomes the
# PR 2 change and a correctness test pins it against the loop's output.
# ---------------------------------------------------------------------------------------------
def plot_data_vectorized(lc, mark_size=1, min_mjd=None, max_mjd=None, ref_mag=None, ref_magerr=None):
    if ref_mag is None:
        ref_mag = immutabledefaultdict(lambda: np.inf)
    if ref_magerr is None:
        ref_magerr = immutabledefaultdict(float)
    if min_mjd is None:
        min_mjd = -np.inf
    if max_mjd is None:
        max_mjd = np.inf
    if not lc:
        return []

    mjd_all = np.array([obs["mjd"] for obs in lc])
    mask = (mjd_all >= min_mjd) & (mjd_all <= max_mjd)
    idx = np.nonzero(mask)[0]
    if idx.size == 0:
        return []
    filtered = [lc[i] for i in idx]
    mjd = mjd_all[idx]
    mag = np.array([obs["mag"] for obs in filtered])
    magerr = np.array([obs["magerr"] for obs in filtered])
    ref_mag_arr = np.array([ref_mag[obs["oid"]] for obs in filtered])
    ref_magerr_arr = np.array([ref_magerr[obs["oid"]] for obs in filtered])

    ref_flux = 10 ** (-0.4 * (ref_mag_arr - ABZPMAG_JY))
    ref_fluxerr = LN10_04 * ref_flux * ref_magerr_arr
    flux_Jy = 10 ** (-0.4 * (mag - ABZPMAG_JY))
    fluxerr_Jy = LN10_04 * flux_Jy * magerr
    diffflux_Jy = flux_Jy - ref_flux
    difffluxerr_Jy = np.hypot(fluxerr_Jy, ref_fluxerr)

    bad = (diffflux_Jy <= 0) | (diffflux_Jy < difffluxerr_Jy)
    with np.errstate(divide="ignore", invalid="ignore"):
        diffmag = np.where(bad, np.inf, ABZPMAG_JY - 2.5 * np.log10(diffflux_Jy))
        diffmagerr_plus = np.where(bad, np.inf, -2.5 * np.log10(1 - difffluxerr_Jy / diffflux_Jy))
        diffmagerr_minus = np.where(bad, np.inf, 2.5 * np.log10(1 + difffluxerr_Jy / diffflux_Jy))

    mjd_offset = mjd - MJD_OFFSET
    dates = Time(mjd, format="mjd").strftime("%Y-%m-%d")

    for i, obs in enumerate(filtered):
        obs["mark_size"] = mark_size
        obs["flux_Jy"] = float(flux_Jy[i])
        obs["fluxerr_Jy"] = float(fluxerr_Jy[i])
        obs["diffflux_Jy"] = float(diffflux_Jy[i])
        obs["difffluxerr_Jy"] = float(difffluxerr_Jy[i])
        obs["ref_flux"] = float(ref_flux[i])
        obs["diffmag"] = float(diffmag[i])
        obs["diffmagerr_plus"] = float(diffmagerr_plus[i])
        obs["diffmagerr_minus"] = float(diffmagerr_minus[i])
        obs[f"mjd_{MJD_OFFSET}"] = float(mjd_offset[i])
        obs["date"] = str(dates[i])

    filtered.sort(key=lambda obs: (FILTERS_ORDER[obs["filter"]], obs["mjd"]))
    return filtered


# ---------------------------------------------------------------------------------------------
# Site 4 candidate: `set_figure`'s plotly construction is not factored into a standalone function
# in the app (it also interleaves an `await model_fit.get_curve(...)` call), so this mirrors the
# `lc_type == "full"`, `brightness_type == "mag"` branch -- the default page load -- closely
# enough to cost the same px.scatter call. Returns a plain `go.Figure`; `wrap_widget` below does
# the `go.FigureWidget` step separately since that step cannot leave this process (see docstring).
# ---------------------------------------------------------------------------------------------
def build_figure(lcs, bright="mag", brighterr="magerr"):
    records = [dict(obs, **{f"mjd_{MJD_OFFSET}": obs["mjd"] - MJD_OFFSET}) for lc in lcs.values() for obs in lc]
    df = pd.DataFrame.from_records(records)
    return px.scatter(
        df,
        x=f"mjd_{MJD_OFFSET}",
        y=bright,
        error_y=brighterr,
        color="filter",
        symbol="oid",
        size="mark_size",
        size_max=10,
        custom_data=["mjd", "oid", "fieldid", "rcid", "filter"],
        render_mode="auto",
    )


def wrap_widget(figure):
    fw = go.FigureWidget(figure)
    fw.layout.hovermode = "closest"
    return fw


# ---------------------------------------------------------------------------------------------
# Synthetic payload generators
# ---------------------------------------------------------------------------------------------
def synth_lc(n_obs, seed=0):
    rng = np.random.default_rng(seed)
    return [
        {
            "mjd": float(58000 + rng.uniform(0, 2000)),
            "mag": float(rng.uniform(15, 21)),
            "magerr": float(rng.uniform(0.01, 0.3)),
            "filter": ["zg", "zr", "zi"][i % 3],
            "oid": 1,
            "fieldid": 633,
            "rcid": 10,
        }
        for i in range(n_obs)
    ]


def synth_lc_dfs(n_oids, n_rows_per_oid, seed=0):
    rng = np.random.default_rng(seed)
    return [
        pd.DataFrame(
            {
                "oid": oid,
                "filter": rng.choice(["zg", "zr", "zi"], n_rows_per_oid),
                "mjd": rng.uniform(58000, 60000, n_rows_per_oid),
                "mag": rng.uniform(15, 22, n_rows_per_oid),
                "magerr": rng.uniform(0.01, 0.3, n_rows_per_oid),
                "clrcoeff": rng.uniform(-0.1, 0.1, n_rows_per_oid),
                "ref": rng.uniform(15, 22, n_rows_per_oid),
                "ref_err": rng.uniform(0.01, 0.3, n_rows_per_oid),
            }
        )
        for oid in range(n_oids)
    ]


def synth_fits_bytes(nrows, seed=0):
    """Reproduces the schema of a real downloaded refpsfcat.fits -- see module docstring."""
    rng = np.random.default_rng(seed)
    table = Table(
        {
            "sourceid": np.arange(nrows, dtype=np.int32),
            "xpos": rng.uniform(0, 3000, nrows).astype(np.float32),
            "ypos": rng.uniform(0, 3000, nrows).astype(np.float32),
            "ra": rng.uniform(0, 360, nrows),
            "dec": rng.uniform(-90, 90, nrows),
            "flux": rng.uniform(0, 1e5, nrows).astype(np.float32),
            "sigflux": rng.uniform(0, 100, nrows).astype(np.float32),
            "mag": rng.uniform(15, 22, nrows).astype(np.float32),
            "sigmag": rng.uniform(0.01, 0.5, nrows).astype(np.float32),
            "snr": rng.uniform(1, 100, nrows).astype(np.float32),
            "chi": rng.uniform(0, 5, nrows).astype(np.float32),
            "sharp": rng.uniform(-1, 1, nrows).astype(np.float32),
            "flags": np.zeros(nrows, dtype=np.int16),
        }
    )
    hdu = fits.BinTableHDU(table)
    primary = fits.PrimaryHDU()
    primary.header["MAGZP"] = 26.275
    primary.header["MAGZPRMS"] = 0.0257
    primary.header["INFOBITS"] = 0
    buf = io.BytesIO()
    fits.HDUList([primary, hdu]).writeto(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------------------------
def _time_call(fn, args):
    t0 = time.perf_counter()
    fn(*args)
    return time.perf_counter() - t0


async def _time_thread(fn, args):
    t0 = time.perf_counter()
    await asyncio.to_thread(fn, *args)
    return time.perf_counter() - t0


async def _time_process(fn, args):
    t0 = time.perf_counter()
    await run_in_process(fn, *args)
    return time.perf_counter() - t0


async def bench_latency(name, fn, args, repeats):
    inline = min(_time_call(fn, args) for _ in range(repeats))
    thread = min([await _time_thread(fn, args) for _ in range(repeats)])
    process = min([await _time_process(fn, args) for _ in range(repeats)])
    print(
        f"{name:38s} inline={inline * 1000:9.1f}ms  thread={thread * 1000:9.1f}ms  "
        f"process={process * 1000:9.1f}ms  thread/process={thread / process:5.2f}x"
    )


async def _heartbeat(stop_event):
    """Ticks on the loop as fast as it's allowed to; records the gap since the last tick.

    Same technique as `figure_pool_bench.py` -- this is the actual "did it stall other requests"
    metric, not the flood's own wall time.
    """
    gaps = []
    last = time.perf_counter()
    while not stop_event.is_set():
        await asyncio.sleep(0)
        now = time.perf_counter()
        gaps.append(now - last)
        last = now
    return gaps


async def _measure_flood(flood):
    stop_event = asyncio.Event()
    heartbeat_task = asyncio.create_task(_heartbeat(stop_event))
    t0 = time.perf_counter()
    await flood()
    elapsed = time.perf_counter() - t0
    stop_event.set()
    gaps = await heartbeat_task
    return elapsed, max(gaps) if gaps else 0.0


async def bench_concurrency(name, fn, args_list, repeats):
    n = len(args_list)

    async def flood_thread():
        await asyncio.gather(*(asyncio.to_thread(fn, *a) for a in args_list))

    async def flood_process():
        await asyncio.gather(*(run_in_process(fn, *a) for a in args_list))

    for label, flood in (("thread", flood_thread), ("process", flood_process)):
        best_total = float("inf")
        worst_gap = 0.0
        for _ in range(repeats):
            elapsed, gap = await _measure_flood(flood)
            best_total = min(best_total, elapsed)
            worst_gap = max(worst_gap, gap)
        print(
            f"{name:30s} n={n} {label:8s} best_total={best_total * 1000:8.1f}ms  "
            f"worst_max_gap={worst_gap * 1000:8.1f}ms"
        )


async def main(n_concurrent: int, repeats: int) -> None:
    print("=== warmup (pays cold import + font-cache cost in the child once) ===")
    await run_in_process(plot_data, synth_lc(10))
    await run_in_process(_dfs_to_csv, synth_lc_dfs(1, 10))
    await run_in_process(_parse_fits, synth_fits_bytes(10), "url", 0)
    await run_in_process(build_figure, {1: plot_data(synth_lc(10))})

    print("\n=== 1. plot_data -- loop vs vectorized, inline (no offload involved) ===")
    for n in (N_OBS_TYPICAL, N_OBS_BUSY):
        lc = synth_lc(n)
        loop_t = min(_time_call(plot_data, ([dict(o) for o in lc],)) for _ in range(LATENCY_REPEATS))
        vec_t = min(_time_call(plot_data_vectorized, ([dict(o) for o in lc],)) for _ in range(LATENCY_REPEATS))
        assert plot_data([dict(o) for o in lc]) == plot_data_vectorized([dict(o) for o in lc])
        print(f"n={n:6d}  loop={loop_t * 1000:8.1f}ms  vectorized={vec_t * 1000:7.1f}ms  speedup={loop_t / vec_t:.2f}x")

    print("\n=== 1. plot_data (original loop) -- offload round trip ===")
    for n in (N_OBS_TYPICAL, N_OBS_BUSY):
        lc = synth_lc(n)
        await bench_latency(f"plot_data n={n}", plot_data, ([dict(o) for o in lc],), LATENCY_REPEATS)

    print(f"\n=== 1. plot_data concurrency (n={n_concurrent}, {N_OBS_BUSY} obs each) ===")
    args_list = [([dict(o) for o in synth_lc(N_OBS_BUSY, seed=i)],) for i in range(n_concurrent)]
    await bench_concurrency("plot_data flood", plot_data, args_list, repeats)

    print("\n=== 2. lc_csv._dfs_to_csv -- single-call latency ===")
    for n_oids, n_rows in ((2, N_OBS_TYPICAL), (8, N_OBS_BUSY // 8)):
        dfs = synth_lc_dfs(n_oids, n_rows)
        await bench_latency(f"_dfs_to_csv oids={n_oids} rows={n_rows}", _dfs_to_csv, (dfs,), LATENCY_REPEATS)

    print(f"\n=== 2. lc_csv concurrency (n={n_concurrent}, 8 oids x {N_OBS_BUSY // 8} rows each) ===")
    args_list = [(synth_lc_dfs(8, N_OBS_BUSY // 8, seed=i),) for i in range(n_concurrent)]
    await bench_concurrency("_dfs_to_csv flood", _dfs_to_csv, args_list, repeats)

    print("\n=== 3. ztf_ref._parse_fits -- single-call latency (real-shaped 38,261-row payload) ===")
    fits_bytes = synth_fits_bytes(38_261)
    print(f"payload = {len(fits_bytes)} bytes")
    await bench_latency("_parse_fits n=38261", _parse_fits, (fits_bytes, "url", 5), LATENCY_REPEATS)

    print(f"\n=== 3. ztf_ref concurrency (n={n_concurrent}) ===")
    args_list = [(synth_fits_bytes(38_261, seed=i), "url", 5) for i in range(n_concurrent)]
    await bench_concurrency("_parse_fits flood", _parse_fits, args_list, repeats)

    print("\n=== 4. figure construction -- single-call latency (go.Figure, not go.FigureWidget) ===")
    for n in (N_OBS_TYPICAL, N_OBS_BUSY):
        lcs = {1: plot_data(synth_lc(n))}
        await bench_latency(f"build_figure n={n}", build_figure, (lcs,), LATENCY_REPEATS)
        figure = build_figure(lcs)
        wrap_t = min(_time_call(wrap_widget, (figure,)) for _ in range(LATENCY_REPEATS))
        print(f"  go.FigureWidget wrap (local only, not poolable): {wrap_t * 1000:.1f}ms")

    print(f"\n=== 4. figure construction concurrency (n={n_concurrent}, {N_OBS_BUSY} obs) ===")
    args_list = [({1: plot_data(synth_lc(N_OBS_BUSY, seed=i))},) for i in range(n_concurrent)]
    await bench_concurrency("build_figure flood", build_figure, args_list, repeats)

    shutdown_pool()


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--n-concurrent", type=int, default=6, help="simultaneous calls in each flood test")
    parser.add_argument("--repeats", type=int, default=3, help="repeats per flood, best total / worst gap kept")
    args = parser.parse_args()
    asyncio.run(main(args.n_concurrent, args.repeats))


if __name__ == "__main__":
    _main()

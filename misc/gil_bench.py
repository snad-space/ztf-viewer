"""Does a thread actually help the CPU-heavy work the viewer offloads?

Runs each workload as K identical tasks serially, then the same K tasks on K threads,
and reports the speedup. Two controls bracket the range: `time.sleep` must reach ~K
(the harness works), pure Python arithmetic must stay ~1 (the GIL is held throughout).
A workload near the arithmetic control gains nothing from a thread and belongs in a
process pool; one near the sleep control is already overlapping fine.

The workloads mirror the real call sites rather than reproducing them, so this stays a
standalone script with no import of the app.

Run: python misc/gil_bench.py
"""

import io
import time
from concurrent.futures import ThreadPoolExecutor

import matplotlib
import numpy as np
import pandas as pd
from astropy.io import fits
from astropy.table import Table

matplotlib.use("Agg")

import matplotlib.backends.backend_pgf  # noqa: E402
import matplotlib.figure  # noqa: E402

K = 4
REPEATS = 5

ABZPMAG_JY = 8.9
LN10_04 = 0.9210340371976184


def _fits_bytes(nrows):
    table = Table(
        {
            "sourceid": np.arange(nrows, dtype=np.int64),
            "ra": np.random.uniform(0, 360, nrows),
            "dec": np.random.uniform(-90, 90, nrows),
            "mag": np.random.uniform(15, 22, nrows),
            "magerr": np.random.uniform(0.01, 0.5, nrows),
        }
    )
    buf = io.BytesIO()
    table.write(buf, format="fits")
    return buf.getvalue()


def _lc_frames(n_frames, n_rows):
    return [
        pd.DataFrame(
            {
                "oid": np.full(n_rows, i, dtype=np.int64),
                "mjd": np.random.uniform(58000, 60000, n_rows),
                "mag": np.random.uniform(15, 22, n_rows),
                "magerr": np.random.uniform(0.01, 0.5, n_rows),
                "filter": np.random.choice(["zg", "zr", "zi"], n_rows),
            }
        )
        for i in range(n_frames)
    ]


def _series(n_series, n_epochs):
    return [
        {
            "mjd": np.sort(np.random.uniform(58000, 60000, n_epochs)),
            "mag": np.random.uniform(15, 22, n_epochs),
            "magerr": np.random.uniform(0.01, 0.5, n_epochs),
        }
        for _ in range(n_series)
    ]


FITS_BYTES = _fits_bytes(2_000_000)
LC_FRAMES = _lc_frames(8, 40_000)
PNG_SERIES = _series(6, 3_000)
PDF_SERIES = _series(3, 400)
LC_OBS = [
    {"mjd": float(t), "mag": float(m), "magerr": float(e), "oid": 1}
    for t, m, e in zip(
        np.random.uniform(58000, 60000, 120_000),
        np.random.uniform(15, 22, 120_000),
        np.random.uniform(0.01, 0.5, 120_000),
    )
]


def w_sleep():
    """Control: pure wait. Must reach ~K, or the harness is broken."""
    time.sleep(0.15)


def w_arithmetic():
    """Control: pure Python. Must stay ~1x -- the GIL is never released."""
    total = 0
    for i in range(3_000_000):
        total += i * i
    return total


def w_fits_parse():
    """catalogs/ztf_ref.py: parse a reference-catalog FITS payload from memory."""
    with fits.open(io.BytesIO(FITS_BYTES)) as hdul:
        table = Table(hdul[1].data)
    return float(table["mag"].sum()) + float(table["ra"].std())


def w_pandas_csv():
    """pages/lc_csv.py: concat the per-OID frames, sort, serialise."""
    df = pd.concat(LC_FRAMES, ignore_index=True).sort_values(["oid", "mjd"])
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return len(buf.getvalue())


def _figure(series):
    fig = matplotlib.figure.Figure(dpi=300, figsize=(6.4, 4.8), constrained_layout=True)
    ax = fig.subplots()
    for s in series:
        ax.errorbar(s["mjd"], s["mag"], yerr=s["magerr"], ls="", marker="o", ms=1)
    ax.invert_yaxis()
    ax.set_xlabel("MJD")
    ax.set_ylabel("mag")
    return fig


def w_png():
    """pages/figure.py save_fig, Agg branch."""
    buf = io.BytesIO()
    _figure(PNG_SERIES).savefig(buf, format="png")
    return len(buf.getvalue())


def w_pdf():
    """pages/figure.py save_fig, PGF branch -- shells out to LaTeX."""
    fig = _figure(PDF_SERIES)
    fig.canvas = matplotlib.backends.backend_pgf.FigureCanvasPgf(fig)
    buf = io.BytesIO()
    fig.savefig(buf, format="pdf")
    return len(buf.getvalue())


def w_python_loop():
    """lc_data/plot_data.py: the per-observation loop."""
    out = []
    for obs in LC_OBS:
        o = dict(obs)
        ref_flux = 10 ** (-0.4 * (25.0 - ABZPMAG_JY))
        o["flux"] = 10 ** (-0.4 * (o["mag"] - ABZPMAG_JY)) - ref_flux
        o["fluxerr"] = err = LN10_04 * o["flux"] * o["magerr"]
        o["snr"] = o["flux"] / err if err else 0.0
        out.append(o)
    return len(out)


WORKLOADS = [
    ("time.sleep (control: pure wait)", w_sleep),
    ("python arithmetic (control: GIL-bound)", w_arithmetic),
    ("astropy FITS parse, 2M rows", w_fits_parse),
    ("pandas concat+sort+to_csv", w_pandas_csv),
    ("matplotlib Agg PNG", w_png),
    ("matplotlib PGF/LaTeX PDF", w_pdf),
    ("per-observation python loop", w_python_loop),
]


def _best(run, fn, n):
    return min(run(fn, n) for _ in range(REPEATS))


def _serial(fn, n):
    start = time.perf_counter()
    for _ in range(n):
        fn()
    return time.perf_counter() - start


def _threaded(fn, n):
    with ThreadPoolExecutor(max_workers=n) as pool:
        start = time.perf_counter()
        list(pool.map(lambda _: fn(), range(n)))
        return time.perf_counter() - start


def main():
    for name, fn in WORKLOADS:
        if fn is not w_sleep:
            fn()  # warm up font caches, lazy imports, first-touch allocations

    print(f"{K} tasks, {K} threads, best of {REPEATS}\n")
    print(f"{'workload':40s} {'serial':>9s} {'threaded':>9s} {'speedup':>8s}")
    print("-" * 70)
    for name, fn in WORKLOADS:
        serial = _best(_serial, fn, K)
        threaded = _best(_threaded, fn, K)
        print(f"{name:40s} {serial:8.3f}s {threaded:8.3f}s {serial / threaded:7.2f}x")


if __name__ == "__main__":
    main()

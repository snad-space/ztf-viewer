"""Pins `plot_data`'s numpy-vectorized rewrite against the per-observation loop it replaced.

`plans/misc/profile_candidates_bench.py` measured the loop as the single largest contributor to
wall time in this module (dominated by constructing one `astropy.time.Time` per observation) and
about 10x slower than a batched, vectorized version at realistic sizes. `_plot_data_loop_reference`
below is that original loop, kept here only as a correctness oracle -- the module itself no longer
has two implementations to choose between.
"""

import math

import numpy as np
from astropy.time import Time

from ztf_viewer.lc_data.plot_data import MJD_OFFSET, plot_data
from ztf_viewer.util import ABZPMAG_JY, FILTERS_ORDER, LN10_04, immutabledefaultdict


def _plot_data_loop_reference(lc, mark_size=1, min_mjd=None, max_mjd=None, ref_mag=None, ref_magerr=None):
    if ref_mag is None:
        ref_mag = immutabledefaultdict(lambda: np.inf)
    if ref_magerr is None:
        ref_magerr = immutabledefaultdict(float)
    if min_mjd is None:
        min_mjd = -np.inf
    if max_mjd is None:
        max_mjd = np.inf

    data = []
    for obs in lc:
        if not min_mjd <= obs["mjd"] <= max_mjd:
            continue

        obs["mark_size"] = mark_size

        ref_flux = 10 ** (-0.4 * (ref_mag[obs["oid"]] - ABZPMAG_JY))
        ref_fluxerr = LN10_04 * ref_flux * ref_magerr[obs["oid"]]

        obs["flux_Jy"] = 10 ** (-0.4 * (obs["mag"] - ABZPMAG_JY))
        obs["fluxerr_Jy"] = LN10_04 * obs["flux_Jy"] * obs["magerr"]

        obs["diffflux_Jy"] = obs["flux_Jy"] - ref_flux
        obs["difffluxerr_Jy"] = np.hypot(obs["fluxerr_Jy"], ref_fluxerr)
        obs["ref_flux"] = ref_flux

        if obs["diffflux_Jy"] <= 0 or obs["diffflux_Jy"] < obs["difffluxerr_Jy"]:
            obs["diffmag"] = np.inf
            obs["diffmagerr_plus"] = np.inf
            obs["diffmagerr_minus"] = np.inf
        else:
            obs["diffmag"] = ABZPMAG_JY - 2.5 * math.log10(obs["diffflux_Jy"])
            obs["diffmagerr_plus"] = -2.5 * math.log10(1 - obs["difffluxerr_Jy"] / obs["diffflux_Jy"])
            obs["diffmagerr_minus"] = 2.5 * math.log10(1 + obs["difffluxerr_Jy"] / obs["diffflux_Jy"])

        obs[f"mjd_{MJD_OFFSET}"] = obs["mjd"] - MJD_OFFSET
        time = Time(obs["mjd"], format="mjd")
        obs["date"] = time.strftime("%Y-%m-%d")

        data.append(obs)

    return sorted(data, key=lambda obs: (FILTERS_ORDER[obs["filter"]], obs["mjd"]))


def _assert_same_result(loop_out, vec_out):
    assert len(loop_out) == len(vec_out)
    for a, b in zip(loop_out, vec_out):
        assert a.keys() == b.keys()
        for key, av in a.items():
            bv = b[key]
            if isinstance(av, float):
                assert (math.isinf(av) and math.isinf(bv) and (av > 0) == (bv > 0)) or math.isclose(
                    av, bv, rel_tol=1e-9, abs_tol=1e-12
                ), (key, av, bv)
            else:
                assert av == bv, (key, av, bv)


def _random_lc(n, seed, n_oids=1, filters=("zg", "zr", "zi")):
    rng = np.random.default_rng(seed)
    return [
        {
            "mjd": float(58000 + rng.uniform(0, 2000)),
            "mag": float(rng.uniform(14, 22)),
            "magerr": float(rng.uniform(0.005, 0.5)),
            "filter": filters[int(rng.integers(0, len(filters)))],
            "oid": int(rng.integers(1, n_oids + 1)),
        }
        for _ in range(n)
    ]


def test_plot_data_matches_reference_loop_on_realistic_random_input():
    lc = _random_lc(2000, seed=1, n_oids=3)
    ref_mag = immutabledefaultdict(lambda: np.inf, {1: 19.5, 2: 18.2, 3: 20.1})
    ref_magerr = immutabledefaultdict(float, {1: 0.02, 2: 0.05, 3: 0.01})

    loop_out = _plot_data_loop_reference(
        [dict(o) for o in lc], mark_size=3, min_mjd=58200.0, max_mjd=59800.0, ref_mag=ref_mag, ref_magerr=ref_magerr
    )
    vec_out = plot_data(
        [dict(o) for o in lc], mark_size=3, min_mjd=58200.0, max_mjd=59800.0, ref_mag=ref_mag, ref_magerr=ref_magerr
    )
    assert len(vec_out) > 0
    _assert_same_result(loop_out, vec_out)


def test_plot_data_matches_reference_loop_with_default_ref_mag():
    """Default ref_mag/ref_magerr (no reference catalog match) drives ref_flux to zero."""
    lc = _random_lc(500, seed=2)
    loop_out = _plot_data_loop_reference([dict(o) for o in lc])
    vec_out = plot_data([dict(o) for o in lc])
    _assert_same_result(loop_out, vec_out)


def test_plot_data_matches_reference_loop_on_negative_diffflux():
    """Observations fainter than the reference flip diffflux_Jy negative -- the inf branch."""
    lc = [
        {"mjd": 58500.0 + i, "mag": 25.0, "magerr": 0.3, "filter": "zg", "oid": 1}  # much fainter than ref
        for i in range(20)
    ]
    ref_mag = immutabledefaultdict(lambda: np.inf, {1: 15.0})
    ref_magerr = immutabledefaultdict(float, {1: 0.01})
    loop_out = _plot_data_loop_reference([dict(o) for o in lc], ref_mag=ref_mag, ref_magerr=ref_magerr)
    vec_out = plot_data([dict(o) for o in lc], ref_mag=ref_mag, ref_magerr=ref_magerr)
    assert all(math.isinf(obs["diffmag"]) for obs in vec_out)
    _assert_same_result(loop_out, vec_out)


def test_plot_data_empty_input():
    assert plot_data([]) == []


def test_plot_data_all_observations_filtered_out_by_mjd_range():
    lc = _random_lc(10, seed=3)
    assert plot_data([dict(o) for o in lc], min_mjd=1.0, max_mjd=2.0) == []

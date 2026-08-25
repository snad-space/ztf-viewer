"""`plot_data`'s output contract: the photometry it derives, the ordering, and the mutation.

`plot_data` derives everything from AB magnitudes, so with `ABZPMAG_JY = 8.9` the magnitudes
below convert to exact round fluxes and the expected values can be written as literals.
"""

import numpy as np
import pytest

from ztf_viewer.lc_data.plot_data import MJD_OFFSET, plot_data
from ztf_viewer.util import ABZPMAG_JY, immutabledefaultdict

MAG_1_JY = ABZPMAG_JY
MAG_1E4_JY = 18.9
MAG_1E5_JY = 21.4

DERIVED_KEYS = {
    "mark_size",
    "flux_Jy",
    "fluxerr_Jy",
    "diffflux_Jy",
    "difffluxerr_Jy",
    "ref_flux",
    "diffmag",
    "diffmagerr_plus",
    "diffmagerr_minus",
    f"mjd_{MJD_OFFSET}",
    "date",
}


def _obs(mjd=58000.0, mag=MAG_1E4_JY, magerr=0.1, band="zg", oid=1):
    return {"mjd": mjd, "mag": mag, "magerr": magerr, "filter": band, "oid": oid}


def _ref(mag=None, magerr=None):
    ref_mag = immutabledefaultdict(lambda: np.inf, {} if mag is None else {1: mag})
    ref_magerr = immutabledefaultdict(float, {} if magerr is None else {1: magerr})
    return {"ref_mag": ref_mag, "ref_magerr": ref_magerr}


@pytest.mark.parametrize("mag, flux_Jy", [(MAG_1_JY, 1.0), (MAG_1E4_JY, 1e-4), (MAG_1E5_JY, 1e-5)])
def test_flux_is_the_ab_magnitude_in_janskys(mag, flux_Jy):
    (obs,) = plot_data([_obs(mag=mag)])
    assert obs["flux_Jy"] == pytest.approx(flux_Jy)


def test_flux_uncertainty_scales_with_flux_and_magerr():
    (obs,) = plot_data([_obs(mag=MAG_1E4_JY, magerr=0.1)])
    assert obs["fluxerr_Jy"] == pytest.approx(9.210340371976186e-06)


def test_without_a_reference_match_diffmag_is_the_input_magnitude():
    """An unmatched oid gets `ref_mag = inf`, i.e. zero reference flux, so nothing is subtracted."""
    (obs,) = plot_data([_obs(mag=MAG_1E4_JY)])
    assert obs["ref_flux"] == 0.0
    assert obs["diffflux_Jy"] == pytest.approx(1e-4)
    assert obs["diffmag"] == pytest.approx(MAG_1E4_JY)


def test_reference_flux_is_subtracted_from_the_observation():
    (obs,) = plot_data([_obs(mag=MAG_1E4_JY)], **_ref(mag=MAG_1E5_JY))
    assert obs["ref_flux"] == pytest.approx(1e-5)
    assert obs["diffflux_Jy"] == pytest.approx(9e-5)
    assert obs["diffmag"] == pytest.approx(19.014393726401686)


def test_reference_uncertainty_enters_the_error_in_quadrature():
    (obs,) = plot_data([_obs(mag=MAG_1E4_JY, magerr=0.1)], **_ref(mag=MAG_1E5_JY, magerr=0.1))
    assert obs["difffluxerr_Jy"] == pytest.approx(9.256277516654899e-06)


def test_reference_is_looked_up_per_oid():
    """One light curve can carry several oids -- see `get_antares_lc`."""
    ref_mag = immutabledefaultdict(lambda: np.inf, {1: MAG_1E5_JY, 2: MAG_1_JY})
    first, second = plot_data([_obs(oid=1), _obs(oid=2, mjd=58001.0)], ref_mag=ref_mag)
    assert first["ref_flux"] == pytest.approx(1e-5)
    assert second["ref_flux"] == pytest.approx(1.0)


def test_an_observation_fainter_than_its_reference_has_no_difference_magnitude():
    (obs,) = plot_data([_obs(mag=MAG_1E5_JY)], **_ref(mag=MAG_1E4_JY))
    assert obs["diffflux_Jy"] < 0
    assert obs["diffmag"] == np.inf
    assert obs["diffmagerr_plus"] == np.inf
    assert obs["diffmagerr_minus"] == np.inf


def test_a_difference_flux_below_its_own_uncertainty_has_no_difference_magnitude():
    """`magerr = 2` puts the flux error above the flux itself, the other branch into `inf`."""
    (obs,) = plot_data([_obs(mag=MAG_1E4_JY, magerr=2.0)])
    assert obs["diffflux_Jy"] > 0
    assert obs["diffflux_Jy"] < obs["difffluxerr_Jy"]
    assert obs["diffmag"] == np.inf
    assert obs["diffmagerr_plus"] == np.inf
    assert obs["diffmagerr_minus"] == np.inf


@pytest.mark.parametrize("mjd, date", [(58000.0, "2017-09-04"), (58200.5, "2018-03-23"), (59000.0, "2020-05-31")])
def test_date_and_offset_mjd_come_from_the_observation_mjd(mjd, date):
    (obs,) = plot_data([_obs(mjd=mjd)])
    assert obs["date"] == date
    assert obs[f"mjd_{MJD_OFFSET}"] == pytest.approx(mjd - MJD_OFFSET)


def test_mjd_range_bounds_are_inclusive():
    lc = [_obs(mjd=mjd) for mjd in (57999.0, 58000.0, 58001.0, 58002.0)]
    out = plot_data(lc, min_mjd=58000.0, max_mjd=58001.0)
    assert [obs["mjd"] for obs in out] == [58000.0, 58001.0]


def test_output_is_sorted_by_filter_then_mjd():
    lc = [
        _obs(mjd=58002.0, band="zr"),
        _obs(mjd=58001.0, band="zg"),
        _obs(mjd=58000.0, band="zr"),
        _obs(mjd=58003.0, band="zg"),
    ]
    out = plot_data(lc)
    assert [(obs["filter"], obs["mjd"]) for obs in out] == [
        ("zg", 58001.0),
        ("zg", 58003.0),
        ("zr", 58000.0),
        ("zr", 58002.0),
    ]


def test_mark_size_is_recorded_on_every_observation():
    out = plot_data([_obs(), _obs(mjd=58001.0)], mark_size=3)
    assert [obs["mark_size"] for obs in out] == [3, 3]


def test_the_input_dicts_are_mutated_in_place_and_returned():
    obs = _obs()
    (out,) = plot_data([obs])
    assert out is obs
    assert DERIVED_KEYS <= set(obs)


def test_derived_values_are_plain_python_scalars():
    """They are serialized to the browser, where numpy scalars do not survive the round trip."""
    (obs,) = plot_data([_obs()])
    for key in DERIVED_KEYS - {"mark_size", "date"}:
        assert type(obs[key]) is float, key
    assert type(obs["date"]) is str


def test_empty_input():
    assert plot_data([]) == []


def test_all_observations_filtered_out_by_mjd_range():
    assert plot_data([_obs(mjd=58000.0)], min_mjd=1.0, max_mjd=2.0) == []

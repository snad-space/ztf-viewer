import numpy as np
import pandas as pd
import pytest

from ztf_viewer.catalogs.conesearch.fink_lsst import FinkLsstQuery

MAG_1E4_JY = 18.9


def _source(*, science_flux=1e5, psf_flux=-2e4):
    return {
        "r:diaObjectId": 313791827794198596,
        "r:midpointMjdTai": 61344.3,
        "r:ra": 9.83,
        "r:dec": -42.48,
        "r:band": "y",
        "r:psfFlux": psf_flux,
        "r:psfFluxErr": 1e3,
        "r:scienceFlux": science_flux,
        "r:scienceFluxErr": 1e3,
    }


def test_lsst_apparent_flux_is_science_flux_and_difference_is_psf_flux():
    obs = FinkLsstQuery._to_light_curve(pd.DataFrame([_source()])).iloc[0]
    assert obs["flux_Jy"] == pytest.approx(1e-4)
    assert obs["mag"] == pytest.approx(MAG_1E4_JY)
    assert obs["diffflux_Jy"] == pytest.approx(-2e-5)
    assert obs["filter"] == "Fink/LSST y"


def test_lsst_object_id_is_a_string_exactly():
    """diaObjectId is above 2**53, so it can't survive as a JavaScript number."""
    obs = FinkLsstQuery._to_light_curve(pd.DataFrame([_source()])).iloc[0]
    assert obs["oid"] == "313791827794198596"


def test_lsst_non_positive_science_flux_is_kept_with_infinite_mag():
    obs = FinkLsstQuery._to_light_curve(pd.DataFrame([_source(science_flux=-1e3)])).iloc[0]
    assert obs["mag"] == np.inf
    assert obs["diffflux_Jy"] == pytest.approx(-2e-5)

import numpy as np
import pandas as pd
import pytest

from ztf_viewer.catalogs.conesearch.fink import alerts_to_light_curve
from ztf_viewer.catalogs.conesearch.fink_lsst import sources_to_light_curve
from ztf_viewer.util import ABZPMAG_JY

MAG_1E4_JY = 18.9
MAG_1E5_JY = 21.4
MISSING = -999.0


def _alert(
    *,
    magpsf=MAG_1E5_JY,
    isdiffpos="t",
    fid=1,
    magnr=MAG_1E4_JY,
    distnr=0.5,
    ps1_mag=MAG_1E4_JY,
    distpsnr1=0.5,
):
    return {
        "i:objectId": "ZTF21abfmbix",
        "i:jd": 2459396.75,
        "i:ra": 193.82,
        "i:dec": 2.9,
        "i:fid": fid,
        "i:magpsf": magpsf,
        "i:sigmapsf": 0.1,
        "i:isdiffpos": isdiffpos,
        "i:magnr": magnr,
        "i:sigmagnr": 0.0,
        "i:distnr": distnr,
        "i:distpsnr1": distpsnr1,
        "i:sgmag1": ps1_mag if fid == 1 else MISSING,
        "i:srmag1": ps1_mag if fid == 2 else MISSING,
        "i:simag1": ps1_mag if fid == 3 else MISSING,
    }


def _alerts_lc(**kwargs):
    return alerts_to_light_curve(pd.DataFrame([_alert(**kwargs)])).iloc[0]


def test_alert_difference_flux_is_magpsf_signed_by_isdiffpos():
    assert _alerts_lc(isdiffpos="t")["diffflux_Jy"] == pytest.approx(1e-5)
    assert _alerts_lc(isdiffpos="f")["diffflux_Jy"] == pytest.approx(-1e-5)


def test_alert_apparent_flux_adds_ztf_reference_under_the_alert():
    obs = _alerts_lc(magnr=MAG_1E4_JY, distnr=0.5, ps1_mag=ABZPMAG_JY)
    assert obs["ref_catalog"] == "ZTF"
    assert obs["flux_Jy"] == pytest.approx(1.1e-4)


def test_alert_falls_back_to_same_band_ps1_when_ztf_reference_is_far():
    obs = _alerts_lc(fid=2, magnr=ABZPMAG_JY, distnr=1.5, ps1_mag=MAG_1E4_JY, distpsnr1=0.5)
    assert obs["ref_catalog"] == "PS1"
    assert obs["filter"] == "Fink/ZTF r"
    assert obs["flux_Jy"] == pytest.approx(1.1e-4)


def test_alert_without_reference_has_zero_reference_flux():
    obs = _alerts_lc(magnr=MISSING, distnr=MISSING, distpsnr1=5.0)
    assert obs["ref_catalog"] == "none"
    assert obs["flux_Jy"] == pytest.approx(1e-5)
    assert obs["mag"] == pytest.approx(MAG_1E5_JY)


def test_alert_with_non_positive_apparent_flux_is_kept_with_infinite_mag():
    obs = _alerts_lc(isdiffpos="f", distnr=MISSING, distpsnr1=MISSING)
    assert obs["diffflux_Jy"] == pytest.approx(-1e-5)
    assert obs["mag"] == np.inf


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
    obs = sources_to_light_curve(pd.DataFrame([_source()])).iloc[0]
    assert obs["flux_Jy"] == pytest.approx(1e-4)
    assert obs["mag"] == pytest.approx(MAG_1E4_JY)
    assert obs["diffflux_Jy"] == pytest.approx(-2e-5)
    assert obs["filter"] == "Fink/LSST y"


def test_lsst_object_id_is_a_string_exactly():
    """diaObjectId is above 2**53, so it can't survive as a JavaScript number."""
    obs = sources_to_light_curve(pd.DataFrame([_source()])).iloc[0]
    assert obs["oid"] == "313791827794198596"


def test_lsst_non_positive_science_flux_is_kept_with_infinite_mag():
    obs = sources_to_light_curve(pd.DataFrame([_source(science_flux=-1e3)])).iloc[0]
    assert obs["mag"] == np.inf
    assert obs["diffflux_Jy"] == pytest.approx(-2e-5)

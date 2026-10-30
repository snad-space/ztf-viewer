from types import SimpleNamespace

import numpy as np
import pandas as pd
from astropy.coordinates import SkyCoord
from numpy.testing import assert_allclose

from ztf_viewer.util import FILTER_COLORS


async def test_regression_get_object_by_id():
    from ztf_viewer.catalogs.conesearch.antares import AntaresQuery

    id = "ZTF18aagrczj"
    expected = SkyCoord(ra=230.71268, dec=41.05182, unit="deg")
    antares_query = AntaresQuery("Test Antares")
    actual = await antares_query.resolve_name(id)
    assert isinstance(actual, SkyCoord)
    assert_allclose(actual.ra.deg, expected.ra.deg, atol=1e-4)
    assert_allclose(actual.dec.deg, expected.dec.deg, atol=1e-4)


def _locus_light_curve():
    from ztf_viewer.catalogs.conesearch.antares import AntaresQuery

    lightcurve = pd.DataFrame(
        {
            "alert_id": ["ztf_candidate:1", "lsst:2", "lsst:3", "ztf_upper_limit:4"],
            "ant_mjd": [60000.0, 61000.0, 61001.0, 60002.0],
            "ant_passband": ["g", "g", "y", "R"],
            "ant_mag": [18.0, 23.0, 24.0, np.nan],
            "ant_magerr": [0.1, 0.2, 0.3, np.nan],
            "ant_mag_corrected": [np.nan, 20.0, 21.0, np.nan],
            "ant_magerr_corrected": [np.nan, 0.01, 0.02, np.nan],
        }
    )
    locus = SimpleNamespace(locus_id="ANT2026test", lightcurve=lightcurve)
    return AntaresQuery._locus_to_light_curve(locus)


def test_locus_to_light_curve_separates_lsst_from_ztf_bands():
    lc = _locus_light_curve()
    assert [obs["filter"] for obs in lc] == ["ant_g", "ant_lsst_g", "ant_lsst_y"]
    assert all(obs["filter"] in FILTER_COLORS for obs in lc)


def test_locus_to_light_curve_lsst_mag_is_total_and_diffimg_mag_is_difference():
    _ztf, lsst_g, lsst_y = _locus_light_curve()
    assert (lsst_g["mag"], lsst_g["magerr"], lsst_g["diffimg_mag"], lsst_g["diffimg_magerr"]) == (20.0, 0.01, 23.0, 0.2)
    assert (lsst_y["mag"], lsst_y["magerr"], lsst_y["diffimg_mag"], lsst_y["diffimg_magerr"]) == (21.0, 0.02, 24.0, 0.3)


def test_locus_to_light_curve_ztf_keeps_the_difference_magnitude():
    ztf, *_lsst = _locus_light_curve()
    assert (ztf["mag"], ztf["magerr"]) == (18.0, 0.1)
    assert "diffimg_mag" not in ztf

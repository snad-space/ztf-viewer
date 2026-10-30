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


def test_locus_to_light_curve_separates_lsst_from_ztf_bands():
    from ztf_viewer.catalogs.conesearch.antares import AntaresQuery

    lightcurve = pd.DataFrame(
        {
            "alert_id": ["ztf_candidate:1", "lsst:2", "lsst:3", "ztf_upper_limit:4"],
            "ant_mjd": [60000.0, 61000.0, 61001.0, 60002.0],
            "ant_passband": ["g", "g", "y", "R"],
            "ant_mag": [18.0, 19.0, 20.0, np.nan],
            "ant_magerr": [0.1, 0.2, 0.3, np.nan],
        }
    )
    locus = SimpleNamespace(locus_id="ANT2026test", lightcurve=lightcurve)

    lc = AntaresQuery._locus_to_light_curve(locus)

    assert [obs["filter"] for obs in lc] == ["ant_g", "ant_lsst_g", "ant_lsst_y"]
    assert all(obs["filter"] in FILTER_COLORS for obs in lc)

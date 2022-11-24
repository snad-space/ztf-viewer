from astropy.coordinates import SkyCoord
from numpy.testing import assert_allclose


def test_regression_get_object_by_id():
    from ztf_viewer.catalogs.conesearch.tns import TnsQuery

    id = "2018lwh"
    expected = SkyCoord(ra=247.45543, dec=24.77282, unit="deg")
    tns_query = TnsQuery("Test TNS")
    actual = tns_query.resolve_name(id)
    assert isinstance(actual, SkyCoord)
    assert_allclose(actual.ra.deg, expected.ra.deg)
    assert_allclose(actual.dec.deg, expected.dec.deg)

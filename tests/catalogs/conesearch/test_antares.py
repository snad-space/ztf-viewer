from astropy.coordinates import SkyCoord
from numpy.testing import assert_allclose


def test_regression_get_object_by_id():
    from ztf_viewer.catalogs.conesearch.antares import AntaresQuery

    id = "ZTF18aagrczj"
    expected = SkyCoord(ra=230.71268, dec=41.05182, unit="deg")
    antares_query = AntaresQuery("Test Antares")
    actual = antares_query.resolve_name(id)
    assert isinstance(actual, SkyCoord)
    assert_allclose(actual.ra.deg, expected.ra.deg, atol=1e-4)
    assert_allclose(actual.dec.deg, expected.dec.deg, atol=1e-4)

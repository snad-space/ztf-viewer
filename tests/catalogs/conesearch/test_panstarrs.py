import pytest
from astropy.coordinates import SkyCoord
from numpy.testing import assert_array_less

# Coordinates of a known ZTF object with PS1 coverage
_RA = 230.71268
_DEC = 41.05182
_RADIUS_DEG = 0.05


@pytest.fixture(scope="module")
def stack_table():
    import requests as req
    from ztf_viewer.catalogs.conesearch.panstarrs import _panstarrs_request

    with req.Session() as session:
        return _panstarrs_request(session, "dr2", "stack", ra=_RA, dec=_DEC, radius=_RADIUS_DEG)


def test_stack_returns_rows(stack_table):
    assert len(stack_table) > 0


def test_stack_has_expected_columns(stack_table):
    for col in ("objID", "raMean", "decMean", "gPSFMag", "rPSFMag"):
        assert col in stack_table.colnames


def test_stack_coordinates_in_range(stack_table):
    # All returned objects should be within the search radius
    coord = SkyCoord(ra=_RA, dec=_DEC, unit="deg")
    sources = SkyCoord(ra=stack_table["raMean"], dec=stack_table["decMean"], unit="deg")
    sep = coord.separation(sources).deg
    assert_array_less(sep, _RADIUS_DEG + 0.01)


def test_stack_missing_values_are_masked_not_string(stack_table):
    """Regression test for https://github.com/snad-space/ztf-viewer/issues/565

    The MAST API returns the string "None" for missing numeric values.
    Verify they are parsed as masked entries, not left as strings.
    """
    # pmra has many missing values at this position (most sources have no proper motion)
    assert "pmra" in stack_table.colnames
    assert stack_table["pmra"].mask.any(), "expected some masked pmra values"
    # No string 'None' should survive into the table
    unmasked = stack_table["pmra"][~stack_table["pmra"].mask]
    assert all(isinstance(v, float) for v in unmasked), "unmasked pmra values should be float"


def test_query_region():
    """End-to-end test through PanstarrsDr2StackedQuery._query_region.

    The base class passes radius as a string of arcseconds, e.g. "180.0s".
    """
    from astropy.coordinates import SkyCoord
    from ztf_viewer.catalogs.conesearch.panstarrs import PanstarrsDr2StackedQuery

    q = PanstarrsDr2StackedQuery("test")
    coord = SkyCoord(ra=_RA, dec=_DEC, unit="deg")
    table = q._query_region(coord, f"{_RADIUS_DEG * 3600}s")
    assert len(table) > 0
    assert "raMean" in table.colnames

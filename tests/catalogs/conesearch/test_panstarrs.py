import pytest
from astropy.coordinates import SkyCoord
from numpy.testing import assert_array_less

# Coordinates of a known ZTF object with PS1 coverage
_RA = 230.71268
_DEC = 41.05182
_RADIUS_DEG = 0.05


@pytest.fixture(scope="module")
def stack_table():
    import asyncio

    from ztf_viewer.catalogs.conesearch.panstarrs import _panstarrs_request

    async def fetch():
        return await _panstarrs_request("dr2", "stack", ra=_RA, dec=_DEC, radius=_RADIUS_DEG)

    return asyncio.run(fetch())


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


async def test_query_region():
    """End-to-end test through PanstarrsDr2StackedQuery._query_region.

    The base class passes radius as a string of arcseconds, e.g. "180.0s".
    """
    from astropy.coordinates import SkyCoord

    from ztf_viewer.catalogs.conesearch.panstarrs import PanstarrsDr2StackedQuery

    q = PanstarrsDr2StackedQuery("test")
    coord = SkyCoord(ra=_RA, dec=_DEC, unit="deg")
    table = await q._query_region(coord, f"{_RADIUS_DEG * 3600}s")
    assert len(table) > 0
    assert "raMean" in table.colnames


# ---------------------------------------------------------------------------------------------
# Objects with no single-epoch detections -- https://github.com/snad-space/ztf-viewer/issues/150
#
# A stacked object can be visible on the stack image and still have nothing in the detections
# table, only upper limits. The viewer offered its light curve anyway, plotting nothing, and
# linked its name to a detections page that answers "No records found".
# ---------------------------------------------------------------------------------------------


def _stack_row(**overrides):
    """One row shaped like `_query_region` returns it."""
    from astropy.table import Table

    columns = {"objID": [181862059718856450], "raMean": [205.97189667], "decMean": [61.55477902]}
    columns |= {key: [value] for key, value in overrides.items()}
    return Table(columns)[0]


@pytest.fixture(scope="module")
def query():
    """The singleton the app itself uses; the registry refuses a second query of a given name."""
    from ztf_viewer.catalogs.conesearch import PANSTARRS_DR2_QUERY

    return PANSTARRS_DR2_QUERY


def test_no_detections_is_recognised(query):
    assert query.has_detections(_stack_row(nDetections=0)) is False


def test_detections_are_recognised(query):
    assert query.has_detections(_stack_row(nDetections=40)) is True


def test_an_unknown_detection_count_is_taken_as_having_them(query):
    """Only a definite zero is acted on: the detections page is the better one when in doubt."""
    from numpy import ma

    assert query.has_detections(_stack_row()) is True
    assert query.has_detections(_stack_row(nDetections=ma.array([0], mask=[True])[0])) is True
    assert query.has_detections(None) is True


def test_an_object_with_detections_links_to_the_detections_table(query):
    row = _stack_row(nDetections=40)
    assert query.get_url(row["objID"], row=row) == (
        "https://catalogs.mast.stsci.edu/panstarrs/detections.html?objID=181862059718856450"
    )


def test_an_object_without_detections_links_to_the_stack_image(query):
    """The detections page has nothing for it; the stack image is what it was detected on."""
    row = _stack_row(nDetections=0)
    url = query.get_url(row["objID"], row=row)
    assert url.startswith("https://ps1images.stsci.edu/cgi-bin/ps1cutouts?")
    assert "pos=205.97189667+61.55477902" in url
    assert "filetypes=stack" in url

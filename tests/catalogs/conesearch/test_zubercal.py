"""Zubercal's cone search: detections come back one per row and have to be folded into objects."""

import numpy as np
import pytest
from astropy.coordinates import SkyCoord
from nested_pandas import NestedFrame

# A bright ZTF-covered star, RR Lyr
_RA = 291.36625
_DEC = 42.78436


def _rows():
    """Two objects' detections, interleaved and out of time order, as the service returns them."""
    return NestedFrame.from_records(
        [
            {"objectid": 1, "objra": 10.0, "objdec": 20.0, "mjd": 59000.0, "band": "r", "mag": 18.0, "magerr": 100},
            {"objectid": 2, "objra": 10.01, "objdec": 20.0, "mjd": 58000.0, "band": "g", "mag": 19.0, "magerr": 200},
            {"objectid": 1, "objra": 10.002, "objdec": 20.0, "mjd": 58500.0, "band": "g", "mag": 18.5, "magerr": 50},
        ]
    )


@pytest.fixture(scope="module")
def query():
    """One instance for the module: the registry refuses a second query of a given name."""
    from ztf_viewer.catalogs.conesearch.zubercal import ZubercalQuery

    return ZubercalQuery("test-zubercal")


def _serve(query, rows):
    """Answer this query's next cone search with `rows` instead of asking the service."""

    async def api_query_region(ra, dec, radius_arcsec):
        return rows

    query._api_query_region = api_query_region


async def _table(query, rows=None):
    _serve(query, _rows() if rows is None else rows)
    return await query._query_region(SkyCoord(10.0, 20.0, unit="deg"), "1.0s")


def _row(table, objectid):
    """The object's row. Row order is the packing's, not the catalog's, so never index by it."""
    return table[list(table["objectid"]).index(objectid)]


async def test_detections_are_grouped_into_one_row_per_ps1_object(query):
    table = await _table(query)

    assert set(table["objectid"]) == {1, 2}
    assert _row(table, 1)["n_obs"] == 2
    assert _row(table, 2)["n_obs"] == 1
    # The position is the one the earliest detection carries, not an average of them all
    assert _row(table, 1)["objra"] == pytest.approx(10.002)


async def test_light_curve_is_sorted_and_in_magnitude_units(query):
    table = await _table(query)
    light_curve = query.light_curve(1, row=_row(table, 1))

    assert [obs["mjd"] for obs in light_curve] == [58500.0, 59000.0]
    # magerr is stored as an integer count of 1e-4 mag
    assert [obs["magerr"] for obs in light_curve] == pytest.approx([0.005, 0.01])
    assert all(obs["oid"] == 1 for obs in light_curve)


async def test_light_curve_filters_are_ones_the_figures_can_colour(query):
    """Bare band names collide with other surveys' and have no colour of their own."""
    from ztf_viewer.util import FILTER_COLORS

    table = await _table(query)
    light_curve = query.light_curve(1, row=_row(table, 1))

    assert {obs["filter"] for obs in light_curve} == {"zuber_g", "zuber_r"}
    assert all(obs["filter"] in FILTER_COLORS for obs in light_curve)


async def test_an_object_whose_detections_are_all_unusable_is_dropped(query):
    """Object 2 has one detection and no usable error, so there is nothing to show for it."""
    rows = _rows()
    rows.loc[rows["objectid"] == 2, "magerr"] = 0

    table = await _table(query, rows)

    assert set(table["objectid"]) == {1}


async def test_the_closest_object_is_the_one_plotted(query):
    """Zubercal resolves ZTF's own blends, so the nearest match is the object asked about."""
    _serve(query, _rows())

    row = await query.find_closest(10.0, 20.0, 60.0)

    assert row["objectid"] == 1


async def test_live_cone_search_returns_a_light_curve():
    from ztf_viewer.catalogs.conesearch import ZUBERCAL_QUERY

    table = await ZUBERCAL_QUERY.find(_RA, _DEC, 1.0)

    assert len(table) > 0
    assert np.all(table["n_obs"] > 0)
    light_curve = ZUBERCAL_QUERY.light_curve(table["objectid"][0], row=table[0])
    assert len(light_curve) == table["n_obs"][0]
    assert {"oid", "mjd", "mag", "magerr", "filter"} <= set(light_curve[0])

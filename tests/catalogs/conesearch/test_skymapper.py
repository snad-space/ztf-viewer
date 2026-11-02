"""SkyMapper DR4's cone search: one row per object, detections nested, and flagged ones dropped."""

import numpy as np
import pytest
from astropy.coordinates import SkyCoord
from nested_pandas import NestedFrame

from ztf_viewer.catalogs.conesearch import SKYMAPPER_DR4_QUERY

# A southern field inside ZTF's footprint
_RA = 181.4
_DEC = -24.41


def _object(object_id, ra, dec, *, n=3, **photometry):
    """An object with `n` clean detections, any photometry column overridable."""
    return {
        "object_id": object_id,
        "raj2000": ra,
        "dej2000": dec,
        "date": [57003.0 - i for i in range(n)],
        "filter": ["g", "r", "i"][:n],
        "mag_psf": [18.0 + 0.1 * i for i in range(n)],
        "e_mag_psf": [0.02] * n,
        "flags": [0] * n,
        "nimaflags": [0] * n,
        "img_qual": [1] * n,
    } | photometry


def _frame(objects):
    """The objects as the parquet answer is read back: photometry in a nested column."""
    return NestedFrame.from_lists(
        NestedFrame.from_records(objects),
        base_columns=["object_id", "raj2000", "dej2000"],
        name="photometry",
    )


def _rows():
    return _frame([_object(1, 10.0, 20.0), _object(2, 10.005, 20.0, n=2)])


@pytest.fixture(scope="module")
def query():
    """One instance for the module: the registry refuses a second query of a given name."""
    from ztf_viewer.catalogs.conesearch.skymapper import SkyMapperDr4Query

    return SkyMapperDr4Query("test-skymapper")


def _serve(query, rows):
    """Answer this query's next cone search with `rows` instead of asking the service."""

    async def api_query_region(ra, dec, radius_arcsec):
        return rows

    query._api_query_region = api_query_region


async def _table(query, rows=None):
    _serve(query, _rows() if rows is None else rows)
    return await query._query_region(SkyCoord(10.0, 20.0, unit="deg"), "1.0s")


def _row(table, object_id):
    """The object's row. Row order is the packing's, not the catalog's, so never index by it."""
    return table[list(table["object_id"]).index(object_id)]


async def test_one_row_per_object(query):
    table = await _table(query)

    assert set(table["object_id"]) == {1, 2}
    assert _row(table, 1)["n_obs"] == 3
    assert _row(table, 2)["n_obs"] == 2


async def test_light_curve_is_sorted_and_keeps_ab_magnitudes_as_they_are(query):
    """DR4 magnitudes are AB already, the system the rest of the app plots in."""
    table = await _table(query)
    light_curve = query.light_curve(1, row=_row(table, 1))

    assert [obs["mjd"] for obs in light_curve] == [57001.0, 57002.0, 57003.0]
    assert [obs["mag"] for obs in light_curve] == pytest.approx([18.2, 18.1, 18.0])
    assert [obs["magerr"] for obs in light_curve] == pytest.approx([0.02] * 3)
    assert all(obs["oid"] == 1 for obs in light_curve)


async def test_light_curve_filters_are_ones_the_figures_can_colour(query):
    """Bare band names collide with other surveys' and have no colour of their own."""
    from ztf_viewer.util import FILTER_COLORS

    table = await _table(query)
    light_curve = query.light_curve(1, row=_row(table, 1))

    assert {obs["filter"] for obs in light_curve} == {"sm_g", "sm_r", "sm_i"}
    assert all(obs["filter"] in FILTER_COLORS for obs in light_curve)


@pytest.mark.parametrize(
    "bad",
    [
        {"flags": [0, 4, 0]},
        {"nimaflags": [0, 5, 0]},
        {"img_qual": [1, 3, 1]},
        {"e_mag_psf": [0.02, np.nan, 0.02]},
    ],
)
async def test_detections_failing_the_dr4_quality_cuts_are_dropped(query, bad):
    table = await _table(query, _frame([_object(1, 10.0, 20.0, **bad)]))

    light_curve = query.light_curve(1, row=_row(table, 1))
    assert [obs["filter"] for obs in light_curve] == ["sm_i", "sm_g"]


async def test_detections_with_only_benign_flags_are_kept(query):
    """Flags 1 and 2 (a bright neighbour, a deblend) and a few masked pixels pass DR4's own cut."""
    rows = _frame([_object(1, 10.0, 20.0, flags=[1, 2, 3], nimaflags=[4, 0, 1], img_qual=[2, 2, 1])])

    table = await _table(query, rows)

    assert _row(table, 1)["n_obs"] == 3


async def test_an_object_whose_detections_are_all_unusable_is_dropped(query):
    rows = _frame([_object(1, 10.0, 20.0), _object(2, 10.005, 20.0, n=2, img_qual=[3, 3])])

    table = await _table(query, rows)

    assert set(table["object_id"]) == {1}


async def test_the_closest_object_is_the_one_plotted(query):
    _serve(query, _rows())

    row = await query.find_closest(10.0, 20.0, 60.0)

    assert row["object_id"] == 1


async def test_live_cone_search_returns_a_light_curve():
    table = await SKYMAPPER_DR4_QUERY.find(_RA, _DEC, 60.0)

    assert len(table) > 0
    assert np.all(table["n_obs"] > 0)
    light_curve = SKYMAPPER_DR4_QUERY.light_curve(table["object_id"][0], row=table[0])
    assert len(light_curve) == table["n_obs"][0]
    assert {"oid", "mjd", "mag", "magerr", "filter"} <= set(light_curve[0])

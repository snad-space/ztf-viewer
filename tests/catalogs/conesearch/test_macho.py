"""MACHO's cone search: both bands share an epoch row, and Kron-Cousins V / R become AB."""

import numpy as np
import pytest
from astropy.coordinates import SkyCoord
from nested_pandas import NestedFrame

from ztf_viewer.catalogs.conesearch import MACHO_QUERY

# A Galactic bulge field inside ZTF's footprint
_RA = 278.1
_DEC = -13.2


def _star(starid, ra, dec, *, n=2, **lc):
    """A star with `n` clean epochs in both bands, any light-curve column overridable."""
    return {
        "starid": starid,
        "fieldid": 301,
        "tileid": 45950,
        "seqn": starid,
        "ra": ra,
        "dec": dec,
        "dateobs": [49002.0 - i for i in range(n)],
        "bmag": [-5.0] * n,
        "berr": [0.05] * n,
        "btype": [1.0] * n,
        "kv": [18.0 + 0.1 * i for i in range(n)],
        "rmag": [-6.0] * n,
        "rerr": [0.04] * n,
        "rtype": [1.0] * n,
        "kr": [17.0 + 0.1 * i for i in range(n)],
    } | lc


def _frame(stars):
    """The stars as the parquet answer is read back: photometry in a nested column."""
    return NestedFrame.from_lists(
        NestedFrame.from_records(stars),
        base_columns=["starid", "fieldid", "tileid", "seqn", "ra", "dec"],
        name="lc",
    )


def _rows():
    return _frame([_star(1, 10.0, 20.0), _star(2, 10.005, 20.0, n=1)])


@pytest.fixture(scope="module")
def query():
    """One instance for the module: the registry refuses a second query of a given name."""
    from ztf_viewer.catalogs.conesearch.macho import MachoQuery

    return MachoQuery("test-macho")


def _serve(query, rows):
    """Answer this query's next cone search with `rows` instead of asking the service."""

    async def api_query_region(ra, dec, radius_arcsec):
        return rows

    query._api_query_region = api_query_region


async def _table(query, rows=None):
    _serve(query, _rows() if rows is None else rows)
    return await query._query_region(SkyCoord(10.0, 20.0, unit="deg"), "1.0s")


def _row(table, starid):
    """The star's row. Row order is the packing's, not the catalog's, so never index by it."""
    return table[list(table["starid"]).index(starid)]


def _band(light_curve, band):
    return [obs for obs in light_curve if obs["filter"] == f"macho_{band}"]


async def test_one_row_per_star_with_both_bands_of_each_epoch(query):
    table = await _table(query)

    assert set(table["starid"]) == {1, 2}
    assert _row(table, 1)["n_obs"] == 4
    assert _row(table, 2)["n_obs"] == 2
    assert _row(table, 1)["macho_id"] == "301.45950.1"


async def test_kron_cousins_magnitudes_are_converted_to_ab(query):
    """Blanton & Roweis 2007: V_AB = V + 0.02, R_AB = R + 0.21."""
    table = await _table(query)
    light_curve = query.light_curve(1, row=_row(table, 1))

    assert [obs["mag"] for obs in _band(light_curve, "V")] == pytest.approx([18.12, 18.02])
    assert [obs["mag"] for obs in _band(light_curve, "R")] == pytest.approx([17.31, 17.21])
    assert [obs["magerr"] for obs in _band(light_curve, "R")] == pytest.approx([0.04, 0.04])


async def test_light_curve_is_sorted_and_filters_are_ones_the_figures_can_colour(query):
    from ztf_viewer.util import FILTER_COLORS

    table = await _table(query)
    light_curve = query.light_curve(1, row=_row(table, 1))

    assert [obs["mjd"] for obs in light_curve] == sorted(obs["mjd"] for obs in light_curve)
    assert {obs["filter"] for obs in light_curve} == {"macho_V", "macho_R"}
    assert all(obs["filter"] in FILTER_COLORS for obs in light_curve)


@pytest.mark.parametrize(
    "bad",
    [
        # The catalog nulls kv where MACHO's cut flag rejects the blue band
        {"kv": [18.0, None]},
        {"btype": [1.0, 7.0]},
        {"btype": [1.0, 41.0]},
        {"bmag": [-5.0, -12.5]},
        {"berr": [0.05, None]},
    ],
)
async def test_a_band_failing_macho_quality_cuts_is_dropped_on_its_own(query, bad):
    """An epoch's red point survives a bad blue one: they are measured independently."""
    table = await _table(query, _frame([_star(1, 10.0, 20.0, **bad)]))
    light_curve = query.light_curve(1, row=_row(table, 1))

    assert [obs["mjd"] for obs in _band(light_curve, "V")] == [49002.0]
    assert len(_band(light_curve, "R")) == 2


async def test_template_boundary_types_are_kept(query):
    """MACHO's own averages accept types 21-26, a good measurement near a template chunk edge."""
    table = await _table(query, _frame([_star(1, 10.0, 20.0, btype=[21.0, 26.0])]))

    assert len(_band(query.light_curve(1, row=_row(table, 1)), "V")) == 2


async def test_a_star_with_no_usable_detections_is_dropped(query):
    rows = _frame([_star(1, 10.0, 20.0), _star(2, 10.005, 20.0, n=1, kv=[None], kr=[None])])

    table = await _table(query, rows)

    assert set(table["starid"]) == {1}


async def test_the_link_asks_macho_for_this_star_alone(query):
    table = await _table(query)

    url = query.get_url(1, row=_row(table, 1))

    assert url.startswith("https://machotap.asvo.nci.org.au/")
    assert "fieldid+%3D+301+AND+tileid+%3D+45950+AND+seqn+%3D+1" in url


async def test_live_cone_search_returns_a_light_curve():
    table = await MACHO_QUERY.find(_RA, _DEC, 5.0)

    assert len(table) > 0
    assert np.all(table["n_obs"] > 0)
    light_curve = MACHO_QUERY.light_curve(table["starid"][0], row=table[0])
    assert len(light_curve) == table["n_obs"][0]
    assert {obs["filter"] for obs in light_curve} <= {"macho_V", "macho_R"}

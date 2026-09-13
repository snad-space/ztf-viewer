"""TESS's cone search: one row per sector, and the target worth plotting is not the nearest one."""

import pytest
from astropy.coordinates import SkyCoord
from nested_pandas import NestedFrame

# RR Lyr, observed by TESS
_RA = 291.36625
_DEC = 42.78436


def _sector(ticid, sector, ra, dec, *, n=4, quality=None, flux=None):
    return {
        "ticid": ticid,
        "sector": sector,
        "ra_obj": ra,
        "dec_obj": dec,
        "time": [2000.0 + i for i in range(n)],
        "sap_flux": [1.5e4] * n if flux is None else flux,
        "sap_flux_err": [1.5e2] * n,
        "quality": [0] * n if quality is None else quality,
    }


def _frame(sectors):
    """The sectors as the parquet answer is read back: photometry in a nested column."""
    return NestedFrame.from_lists(
        NestedFrame.from_records(sectors),
        base_columns=["ticid", "sector", "ra_obj", "dec_obj"],
        name="lightcurve",
    )


def _rows():
    """A near target seen in one sector and a farther one seen in two."""
    return _frame(
        [
            _sector(10, 1, 10.0, 20.0),
            _sector(20, 1, 10.005, 20.0),
            _sector(20, 2, 10.005, 20.0),
        ]
    )


@pytest.fixture(scope="module")
def query():
    """One instance for the module: the registry refuses a second query of a given name."""
    from ztf_viewer.catalogs.conesearch.tess import TessLightCurveQuery

    return TessLightCurveQuery("test-tess")


def _serve(query, rows):
    """Answer this query's next cone search with `rows` instead of asking the service."""

    async def api_query_region(ra, dec, radius_arcsec):
        return rows

    query._api_query_region = api_query_region


async def _table(query, rows=None):
    _serve(query, _rows() if rows is None else rows)
    return await query._query_region(SkyCoord(10.0, 20.0, unit="deg"), "1.0s")


def _row(table, ticid):
    """The target's row. Row order is the packing's, not the catalog's, so never index by it."""
    return table[list(table["ticid"]).index(ticid)]


async def test_sectors_are_grouped_into_one_row_per_tic(query):
    table = await _table(query)

    assert set(table["ticid"]) == {10, 20}
    assert _row(table, 10)["n_obs"] == 4
    # Both of this one's sectors are in the same light curve
    assert _row(table, 20)["n_obs"] == 8


async def test_the_longest_light_curve_is_plotted_not_the_closest(query):
    """A TESS pixel is 21 arcsec, so every target in the cone is the same blend."""
    _serve(query, _rows())

    table = await query.find(10.0, 20.0, 60.0)
    row = await query.find_closest(10.0, 20.0, 60.0)

    assert table["ticid"][0] == 10, "the nearest target is the other one"
    assert row["ticid"] == 20


async def test_flux_becomes_magnitude_and_time_becomes_mjd(query):
    from ztf_viewer.catalogs.conesearch.tess import BTJD_TO_MJD, TESS_ZP_MAG

    table = await _table(query)
    light_curve = query.light_curve(10, row=_row(table, 10))

    assert light_curve[0]["mjd"] == pytest.approx(2000.0 + BTJD_TO_MJD)
    # 15000 e-/s is Tmag 10 by definition of the zero point
    assert TESS_ZP_MAG == pytest.approx(20.44)
    assert light_curve[0]["mag"] == pytest.approx(10.0, abs=1e-3)
    assert light_curve[0]["filter"] == "TESS"


async def test_cadences_the_pipeline_flagged_are_dropped(query):
    rows = _frame([_sector(10, 1, 10.0, 20.0, quality=[0, 128, 0, 0], flux=[1.5e4, 1.5e4, -3.0, 1.5e4])])

    table = await _table(query, rows)

    # The flagged cadence and the negative flux both go; two of four are left
    assert _row(table, 10)["n_obs"] == 2


async def test_sectors_of_one_target_are_one_light_curve_in_time_order(query):
    table = await _table(query)
    light_curve = query.light_curve(20, row=_row(table, 20))

    assert len(light_curve) == 8
    assert [obs["mjd"] for obs in light_curve] == sorted(obs["mjd"] for obs in light_curve)
    assert {obs["sector"] for obs in light_curve} == {1, 2}


async def test_live_cone_search_returns_a_light_curve():
    from ztf_viewer.catalogs.conesearch import TESS_QUERY

    row = await TESS_QUERY.find_closest(_RA, _DEC, 1.0)
    light_curve = TESS_QUERY.light_curve(row["ticid"], row=row)

    assert len(light_curve) == row["n_obs"]
    assert {"oid", "mjd", "mag", "magerr", "filter"} <= set(light_curve[0])

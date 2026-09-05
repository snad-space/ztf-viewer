"""Tests for `SimbadQuery`, whose column contract broke silently under astroquery >=0.4.8.

astroquery started returning SIMBAD's own TAP column names: coordinates became `ra`/`dec` in
degrees where they had been `RA`/`DEC` in hours, and `otypes` turned from one comma-separated
cell into a joined table with one row per type. This class kept asking for the old names, so
every cone search raised `KeyError: 'RA'` — invisible on a page, because `get_summary` treats a
`KeyError` from one catalog as "no match" and moves on.

So the live test below asserts the *contract* rather than any one column: every key the viewer
renders must exist, and the returned coordinates must actually land inside the search radius,
which is what an hours/degrees mix-up breaks. The offline tests cover the collapse of SIMBAD's
one-row-per-measurement answer, using a table shaped like a real response.
"""

import numpy as np
import pytest
from astropy.table import Table
from numpy import ma

# Two objects as SIMBAD returns them with `otypes`, `mesdistance` and `mesVar` requested: the
# first as the cross product of 2 object types x 2 distance measurements (one variability
# measurement), the second with no measurements at all, so its `mes*` cells are masked.
RAW_ROWS = {
    "main_id": [
        "V* RR Lyr",
        "V* RR Lyr",
        "V* RR Lyr",
        "V* RR Lyr",
        "2MASS J05343217+2200560",
        "2MASS J05343217+2200560",
    ],
    "ra": [291.36637, 291.36637, 291.36637, 291.36637, 83.63410, 83.63410],
    "dec": [42.78431, 42.78431, 42.78431, 42.78431, 22.01556, 22.01556],
    "otype": ["RR*", "RR*", "RR*", "RR*", "*", "*"],
    "otypes.otype": ["RR*", "V*", "RR*", "V*", "*", "NIR"],
    "mesdistance.mespos": ma.array([2, 2, 1, 1, 0, 0], mask=[False, False, False, False, True, True]),
    "mesdistance.dist": ma.array([0.3, 0.3, 250.947, 250.947, 0.0, 0.0], mask=[False] * 4 + [True] * 2),
    "mesdistance.unit": ma.array(["kpc", "kpc", "pc", "pc", "", ""], mask=[False] * 4 + [True] * 2),
    "mesvar.mespos": ma.array([1, 1, 1, 1, 0, 0], mask=[False] * 4 + [True] * 2),
    "mesvar.vartyp": ma.array(["RRAB"] * 4 + ["", ""], mask=[False] * 4 + [True] * 2),
    "mesvar.period": ma.array([0.5668] * 4 + [0.0, 0.0], mask=[False] * 4 + [True] * 2),
}


@pytest.fixture
def simbad_query():
    # Deferred: a module-level import would run during collection, before conftest forces the
    # memory-backed unavailable_catalogs singleton, and eagerly connect to Redis instead.
    from ztf_viewer.catalogs.conesearch.simbad import SimbadQuery

    return SimbadQuery


def collapsed_row(table, main_id):
    (index,) = np.flatnonzero(table["main_id"] == main_id)
    return table[int(index)]


def test_measurement_cross_product_collapses_to_one_row_per_object(simbad_query):
    """SIMBAD answers a 5″ cone search on RR Lyr with 48 rows for that one star."""
    table = simbad_query._one_row_per_object(Table(RAW_ROWS))

    assert len(table) == 2, "one row per object, not per (object x otype x distance x variability)"
    assert sorted(table["main_id"]) == ["2MASS J05343217+2200560", "V* RR Lyr"]


def test_each_measurement_group_keeps_the_measurement_simbad_prefers(simbad_query):
    """`mespos` 1 is SIMBAD's preferred measurement, and the rows do not arrive in that order.

    Keeping whichever row came back first would have shown RR Lyr at 0.3 kpc — the rounded
    second-choice distance — instead of the 250.947 pc SIMBAD puts first.
    """
    table = simbad_query._one_row_per_object(Table(RAW_ROWS))

    row = collapsed_row(table, "V* RR Lyr")
    assert row["mesdistance.dist"] == pytest.approx(250.947)
    assert row["mesdistance.unit"] == "pc"
    assert row["mesvar.vartyp"] == "RRAB"
    assert row["mesvar.period"] == pytest.approx(0.5668)


def test_all_object_types_are_kept_in_one_cell(simbad_query):
    """The "Other types" column, which `otypes` used to deliver as a single cell."""
    table = simbad_query._one_row_per_object(Table(RAW_ROWS))

    assert collapsed_row(table, "V* RR Lyr")["__otypes"] == "RR*, V*", "listed once each, in SIMBAD's order"
    assert collapsed_row(table, "2MASS J05343217+2200560")["__otypes"] == "*, NIR"


def test_object_with_no_measurements_survives_the_collapse(simbad_query):
    """Most objects have neither a distance nor a variability measurement.

    SIMBAD left-joins nulls for them, so the collapse has no `mespos` to rank by and must keep
    the object anyway — dropping it would silently shrink the cross-match table.
    """
    table = simbad_query._one_row_per_object(Table(RAW_ROWS))

    row = collapsed_row(table, "2MASS J05343217+2200560")
    assert row["otype"] == "*"
    assert ma.is_masked(row["mesdistance.dist"])


def test_distance_column_uses_the_per_row_unit(simbad_query):
    """`mesdistance` reports pc, kpc or Mpc per measurement, so the unit is per row."""
    from astropy import units

    table = simbad_query._one_row_per_object(Table(RAW_ROWS))
    simbad_query.add_distance_column(None, table)

    assert collapsed_row(table, "V* RR Lyr")["__distance"] == 250.947 * units.pc
    assert collapsed_row(table, "2MASS J05343217+2200560")["__distance"] is None, "no measurement, no distance"


def test_empty_answer_is_passed_through(simbad_query):
    """`find()` turns an empty table into NotFound itself; the collapse must not raise first."""
    assert simbad_query._one_row_per_object(None) is None
    assert len(simbad_query._one_row_per_object(Table(RAW_ROWS)[:0])) == 0


async def test_cone_search(simbad_query):
    """Regression test against the real SIMBAD service, on the Crab pulsar's position.

    V* CM Tau (the Crab) sits 0.4″ from this position, and its neighbour 2MASS
    J05343217+2200560 is ~5″ away, so a 10″ cone returns two objects with different amounts of
    measurement data.
    """
    from astropy.coordinates import SkyCoord

    from ztf_viewer.util import to_str

    query = simbad_query("Test Simbad")
    ra, dec = 83.633, 22.0145
    table = await query.find(ra, dec, 10.0)

    for column in query.columns:
        assert column in table.colnames, f"the viewer renders {column!r}, which SIMBAD no longer returns"

    assert len(set(table["main_id"])) == len(table), "duplicate objects left by the measurement joins"
    assert "V* CM Tau" in list(table["__objname"])

    # The coordinates have to land inside the cone we asked for: `RA`/`DEC` in hours would have
    # put every object 15x too far east, and the KeyError that this class raised before hid that.
    assert np.all(table["separation"] <= 10.0)
    assert SkyCoord(ra, dec, unit="deg").separation(table["__coord"][0]).arcsec < 1.0

    crab = collapsed_row(table, "V* CM Tau")
    assert crab["__type"] == "Psr"
    assert "SN*" in crab["__otypes"], f"the Crab is a supernova remnant; got {crab['__otypes']!r}"
    assert to_str(crab["__distance"]) == "2000.00 pc"

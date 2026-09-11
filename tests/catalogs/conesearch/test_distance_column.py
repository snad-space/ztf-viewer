"""`__distance` for the two Bailer-Jones distance catalogs.

`masked * units.pc` is plain `0 pc` -- the mask is dropped, not propagated -- so a source whose
distance the catalog does not give was reported as sitting at zero distance: shown as "0.0 pc" in
the summary, and fed to Bayestar, which then answered with an extinction for distance zero.
"""

import numpy as np
import pytest
from astropy import units
from astropy.table import QTable, Table
from numpy import ma

from ztf_viewer.catalogs.conesearch._base import distance_quantity
from ztf_viewer.util import to_str


def test_a_missing_distance_does_not_become_zero():
    assert distance_quantity(ma.array([100.0, 0.0], mask=[False, True]), units.pc)[1] != 0 * units.pc


def test_a_missing_distance_is_not_a_number():
    quantity = distance_quantity(ma.array([100.0, 0.0], mask=[False, True]), units.pc)
    assert np.isfinite(quantity[0].value)
    assert not np.isfinite(quantity[1].value)


def test_a_given_distance_is_kept():
    assert distance_quantity(ma.array([100.0], mask=[False]), units.pc)[0] == 100 * units.pc


def test_an_unmasked_column_is_kept():
    """Neither catalog's column is masked in practice; that path must stay untouched."""
    quantity = distance_quantity(np.array([100.0, 250.0]), units.pc)
    assert list(quantity.value) == [100.0, 250.0]
    assert quantity.unit == units.pc


def test_a_missing_distance_is_not_shown():
    """`to_str` renders a distance for the summary; it used to make "0.0 pc" of a missing one."""
    quantity = distance_quantity(ma.array([0.0], mask=[True]), units.pc)
    assert to_str(quantity[0]) == ""


def test_a_given_distance_is_shown():
    assert to_str(distance_quantity(ma.array([250.0], mask=[False]), units.pc)[0]) == "250.00 pc"


@pytest.mark.parametrize("catalog_name", ["Gaia EDR3 Distances", "Gaia DR2 Distances"])
def test_the_catalogs_use_it(catalog_name):
    """Both build `__distance` the same way, so both get the same treatment."""
    from ztf_viewer.catalogs.conesearch import get_catalog_query

    query = get_catalog_query(catalog_name)
    column = {"Gaia EDR3 Distances": "rgeo", "Gaia DR2 Distances": "rest"}[catalog_name]
    table = Table({column: ma.array([100.0, 0.0], mask=[False, True])})
    query.add_distance_column(table)

    assert table["__distance"].unit == units.pc
    assert np.isfinite(table["__distance"][0])
    assert not np.isfinite(table["__distance"][1])


def test_the_row_a_page_reads_still_carries_the_unit():
    """`get_summary` takes one row through `QTable`, which is what reaches Bayestar."""
    table = Table({"separation": [1.0]})
    table["__distance"] = distance_quantity(ma.array([250.0], mask=[False]), units.pc)
    assert QTable(table[0])["__distance"].to_value(units.pc) == pytest.approx([250.0])

"""Tests for GaiaDr3Query.add_prob_class_columns — covers the fix for issue #310.

Vizier returns masked (missing) probability values as numpy.ma.masked, not
None. The bug compared against `None`, so a masked probability slipped
through into the classifications dict and was later rendered as "--%".

Also covers `_table_to_light_curve`'s filter naming, which the rest of the app keys colours
and legend entries on.
"""

import pytest
from astropy.table import Table
from numpy import ma


@pytest.mark.asyncio
async def test_add_prob_class_columns_skips_masked_probability():
    # Deferred: a module-level import would run during collection, before conftest forces the
    # memory-backed unavailable_catalogs singleton, and eagerly connect to Redis instead.
    from ztf_viewer.catalogs.conesearch.gaia_dr3 import GaiaDr3Query

    table = Table(
        {
            "PQSO": ma.array([0.706, 0.0], mask=[False, True]),
            "PGal": ma.array([0.0, 0.0], mask=[True, True]),
            "PSS": ma.array([0.0, 0.5], mask=[True, False]),
        }
    )

    await GaiaDr3Query.add_prob_class_columns(None, table)

    assert table["classifications"][0] == {"Quasar": pytest.approx(0.706)}
    assert table["classifications"][1] == {"single star": pytest.approx(0.5)}


def _epoch_photometry_table(n=2):
    """The columns `_table_to_light_curve` reads out of a Gaia DR3 epoch-photometry table."""
    columns = {}
    for band in ("g", "bp", "rp"):
        columns[f"variability_flag_{band}_reject"] = [False] * n
    columns["g_transit_time"] = [1000.0 + i for i in range(n)]
    columns["g_transit_flux"] = [1e4] * n
    columns["g_transit_flux_over_error"] = [100.0] * n
    for band in ("bp", "rp"):
        columns[f"{band}_obs_time"] = [1000.0 + i for i in range(n)]
        columns[f"{band}_flux"] = [1e4] * n
        columns[f"{band}_flux_over_error"] = [100.0] * n
    return Table(columns)


def test_light_curve_filters_are_prefixed_with_the_survey():
    """The bare band names collide with other surveys' and are absent from `FILTER_COLORS`, so
    the downloadable figure raised a `KeyError` on a Gaia light curve instead of rendering."""
    from types import SimpleNamespace

    from ztf_viewer.catalogs.conesearch.gaia_dr3 import GaiaDr3Query
    from ztf_viewer.util import FILTER_COLORS

    # Only the passband constants are read, so building the real query object -- which opens an
    # astroquery session -- is not needed
    query = SimpleNamespace(BANDS=GaiaDr3Query.BANDS, AB_ZP=GaiaDr3Query.AB_ZP, AB_ZP_ERR=GaiaDr3Query.AB_ZP_ERR)
    lc = GaiaDr3Query._table_to_light_curve(query, 42, _epoch_photometry_table())

    assert {obs["filter"] for obs in lc} == {"gaia_G", "gaia_BP", "gaia_RP"}
    # Every one of them has to be a filter the figures know how to colour
    assert all(obs["filter"] in FILTER_COLORS for obs in lc)

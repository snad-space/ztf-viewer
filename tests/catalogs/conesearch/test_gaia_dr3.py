"""Tests for GaiaDr3Query.add_prob_class_columns — covers the fix for issue #310.

Vizier returns masked (missing) probability values as numpy.ma.masked, not
None. The bug compared against `None`, so a masked probability slipped
through into the classifications dict and was later rendered as "--%".
"""

import pytest
from astropy.table import Table
from numpy import ma

from ztf_viewer.catalogs.conesearch.gaia_dr3 import GaiaDr3Query


@pytest.mark.asyncio
async def test_add_prob_class_columns_skips_masked_probability():
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

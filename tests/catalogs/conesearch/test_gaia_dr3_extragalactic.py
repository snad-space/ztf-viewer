"""https://github.com/snad-space/ztf-viewer/issues/167

Vizier I/356, Gaia DR3 Part 2, is two tables, and the viewer registers one catalog for each.
What matters downstream is that `z` becomes `__redshift` and so a `__distance`, because the
summary quotes both, and that the asymmetric confidence interval survives into `_z`.
"""

import pickle

import numpy as np
import pytest
from astropy import units

from ztf_viewer.catalogs.conesearch.gaia_dr3_extragalactic import (
    GaiaDr3GalaxyCandidates,
    GaiaDr3QsoCandidates,
)

# 3C 273, the brightest quasar in the ZTF footprint, z = 0.158
_QSO_RA = 187.27792
_QSO_DEC = 2.05239

# A patch with enough Gaia DR3 galaxy candidates that some carry a UGC redshift and some do not
_GALAXY_RA = 195.0
_GALAXY_DEC = 28.0


def _distance_mpc(table, row):
    """`__distance` is a bare float with the unit on the column, or a Quantity when the column
    went object-dtype because some rows have no redshift. `viewer._row_distance` accepts both."""
    value = row["__distance"]
    if isinstance(value, units.Quantity):
        return value.to_value(units.Mpc)
    return (value * table["__distance"].unit).to_value(units.Mpc)


async def test_qso_candidates_find_3c273():
    table = await GaiaDr3QsoCandidates("Test Gaia DR3 QSO Candidates").find(_QSO_RA, _QSO_DEC, 5.0)

    assert len(table) == 1
    row = table[0]
    assert row["__type"] == "AGN"
    assert row["__redshift"] == pytest.approx(0.1601, abs=1e-4)
    assert _distance_mpc(table, row) > 700.0
    # `find` is `@cache()`-decorated, and the Redis backend pickles what it stores
    assert pickle.loads(pickle.dumps(table)) is not None


async def test_qso_candidates_render_the_redshift_interval():
    table = await GaiaDr3QsoCandidates("Test Gaia DR3 QSO Candidates interval").find(_QSO_RA, _QSO_DEC, 5.0)

    assert "0.160" in table["_z"][0]
    assert "superscript" in table["_z"][0], "the QSOC confidence interval is not rendered"


async def test_galaxy_candidates_find():
    table = await GaiaDr3GalaxyCandidates("Test Gaia DR3 Galaxy Candidates").find(_GALAXY_RA, _GALAXY_DEC, 600.0)

    assert len(table) > 0
    assert "separation" in table.colnames
    assert "__distance" in table.colnames
    assert pickle.loads(pickle.dumps(table)) is not None


async def test_galaxy_candidates_tolerate_a_missing_redshift():
    """Most candidates have no UGC redshift, and a masked one must not break the rest of the row."""
    table = await GaiaDr3GalaxyCandidates("Test Gaia DR3 Galaxy Candidates masked").find(_GALAXY_RA, _GALAXY_DEC, 600.0)

    masked = [row for row in table if np.ma.is_masked(row["__redshift"])]
    assert masked, "expected at least one candidate with no redshift in this field"
    assert masked[0]["_z"] == ""

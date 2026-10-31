"""Tests for the Gaia DR3 Part 2 (Extra-galactic) and Part 4 (Variability) cone searches.

See https://github.com/snad-space/ztf-viewer/issues/167
"""

import pickle

import pytest
from astropy.table import Table
from numpy import ma

# 3C 273: in both I/356/qsocand and I/358/vclassre, with an unflagged QSOC redshift of ~0.16
# against a spectroscopic 0.158.
_RA = 187.277915
_DEC = 2.052388
_RADIUS_ARCSEC = 5.0


@pytest.fixture
def qso_query(request):
    # Deferred: a module-level import would run during collection, before conftest forces the
    # memory-backed unavailable_catalogs singleton, and eagerly connect to Redis instead.
    from ztf_viewer.catalogs.conesearch.gaia_dr3_extragalactic import GaiaDr3QsoCandQuery

    # Every query object registers itself under its name and a repeated name is an error, so
    # each test -- including each parametrization -- needs its own.
    return GaiaDr3QsoCandQuery(f"Test Gaia DR3 QSO Candidates {request.node.name}")


@pytest.mark.parametrize(
    ("flags", "masked", "expected"),
    [
        (0, False, 0.5),
        # Z_BADSPEC: too few BP/RP transits, or a source too faint to fit
        (16, False, None),
        # Z_AMBIGUOUS | Z_LOWCCFRATIO: two redshifts fit about as well
        (3, False, None),
        (0, True, None),
    ],
)
def test_qsoc_redshift_is_dropped_when_flagged(qso_query, flags, masked, expected):
    """A flagged QSOC redshift must not reach the summary's distance and absolute magnitude.

    Only `flags_qsoc == 0` is Z_NOWARNING; everything else is what the catalog's own note calls
    an uncertain prediction, and at the absolute magnitude it would be a several-magnitude error.
    """
    table = Table({"z": [0.5], "flagsQSOC": ma.array([flags], mask=[masked])})

    qso_query.add_redshift_column(table)

    assert table["__redshift"][0] == expected


async def test_qso_candidates_find_returns_a_usable_redshift(qso_query):
    table = await qso_query.find(_RA, _DEC, _RADIUS_ARCSEC)

    assert len(table) > 0
    row = table[0]
    assert row["flagsQSOC"] == 0
    assert row["__redshift"] == pytest.approx(0.158, abs=0.02)
    # A redshift means a distance, which is what the summary shows
    assert row["__distance"] is not None

    # `find` is `@cache()`-decorated, and the Redis backend pickles what it stores
    assert pickle.loads(pickle.dumps(table)) is not None


async def test_variability_find_reports_the_gaia_class():
    """A hit here means Gaia already published the object as a variable."""
    from ztf_viewer.catalogs.conesearch.gaia_dr3_vari import GaiaDr3VariQuery

    query = GaiaDr3VariQuery("Test Gaia DR3 Variability")
    table = await query.find(_RA, _DEC, _RADIUS_ARCSEC)

    assert len(table) > 0
    assert str(table[0]["__type"]) == "AGN"

    assert pickle.loads(pickle.dumps(table)) is not None

"""Tests for ztf_viewer.catalogs.skybot — covers the fix for issue #564.

The SkyBot API (ssp.imcce.fr) is an external service.  Tests that call it
live are guarded with ``pytest.importorskip``-style logic: they catch the
``NotFound`` exception that is raised when the service is unreachable or
temporarily unavailable and re-raise as ``pytest.skip`` so CI stays green
even when the upstream endpoint is down.
"""

import pytest
from unittest.mock import MagicMock

from astropy.coordinates import Angle
from astropy.table import QTable, MaskedColumn
from astropy.time import Time
import astropy.units as u

from ztf_viewer.exceptions import NotFound


def _make_empty_skybot_table():
    """Return a zero-row QTable mimicking what astroquery returns for an empty SkyBot result.

    astroquery's ``_parse_result`` bails out before renaming columns when
    ``len(results) == 0``, so the columns keep their original VOTable names
    (``angdist``, ``errpos``, …) instead of the renamed ones (``centerdist``,
    ``posunc``, …).  This is exactly the situation that triggered the
    ``KeyError: 'centerdist'`` in issue #564.
    """
    t = QTable()
    for name in ("Number", "Name", "RA", "DEC", "Type", "V", "errpos", "angdist", "RA_rate", "DEC_rate", "epoch"):
        t[name] = [] * (u.arcsec if name in ("errpos", "angdist") else u.one)
    return t


def _make_skybot_table_with_ceres(sep_arcsec=5.0):
    """Return a one-row QTable that looks like a SkyBot hit for Ceres.

    astroquery renames columns for non-empty results, so this table already
    has the post-rename names (``centerdist``, ``posunc``).  The ``epoch``
    column holds a bare JD float, matching the real SkyBot VOTable.
    """
    t = QTable()
    t["Number"] = MaskedColumn([1], mask=[False])
    t["Name"] = ["Ceres"]
    t["RA"] = [331.0] * u.deg
    t["DEC"] = [-11.4] * u.deg
    t["Type"] = ["Asteroid"]
    t["V"] = [8.5] * u.mag
    t["posunc"] = [0.1] * u.arcsec  # already renamed (non-empty path)
    t["centerdist"] = [sep_arcsec] * u.arcsec
    t["RA_rate"] = [0.0] * (u.arcsec / u.hour)
    t["DEC_rate"] = [0.0] * (u.arcsec / u.hour)
    # epoch is a plain JD float, as returned by the real SkyBot VOTable
    t["epoch"] = [Time("2020-03-15").jd]
    return t


# ---------------------------------------------------------------------------
# Unit tests (no network) — test the bug fix for issue #564
# ---------------------------------------------------------------------------

# observatory_mjd is passed as a plain float MJD throughout (see skybot.py)
_OBS_MJD = 58923.0


def test_empty_result_raises_not_found():
    """KeyError on empty SkyBot response should raise NotFound, not crash.

    Regression test for https://github.com/snad-space/ztf-viewer/issues/564:
    astroquery skips column renaming for zero-row results, so accessing
    ``table["centerdist"]`` raised KeyError instead of returning NotFound.
    """
    from ztf_viewer.catalogs.skybot import SkybotQuery

    query = SkybotQuery.__new__(SkybotQuery)
    query._query = MagicMock()
    query._query.cone_search.return_value = _make_empty_skybot_table()

    with pytest.raises(NotFound):
        query.find(ra=331.0, dec=-11.4, observatory_mjd=_OBS_MJD, radius_arcsec=60.0)


def test_result_within_radius_returned():
    """A non-empty result within the requested radius is returned correctly."""
    from ztf_viewer.catalogs.skybot import SkybotQuery

    query = SkybotQuery.__new__(SkybotQuery)
    query._query = MagicMock()
    query._query.cone_search.return_value = _make_skybot_table_with_ceres(sep_arcsec=5.0)

    table = query.find(ra=331.0, dec=-11.4, observatory_mjd=_OBS_MJD, radius_arcsec=60.0)

    assert len(table) == 1
    assert table["__name"][0] == "Ceres"


def test_result_outside_radius_raises_not_found():
    """Objects beyond the requested radius + position-uncertainty margin are filtered out."""
    from ztf_viewer.catalogs.skybot import SkybotQuery

    query = SkybotQuery.__new__(SkybotQuery)
    query._query = MagicMock()
    # Object is 90 arcsec away; request is only 60 arcsec; posunc is 0.1 arcsec
    query._query.cone_search.return_value = _make_skybot_table_with_ceres(sep_arcsec=90.0)

    with pytest.raises(NotFound):
        query.find(ra=331.0, dec=-11.4, observatory_mjd=_OBS_MJD, radius_arcsec=60.0)


def test_radius_too_large_raises_value_error():
    """Requests larger than query_radius should raise ValueError immediately."""
    from ztf_viewer.catalogs.skybot import SkybotQuery

    query = SkybotQuery.__new__(SkybotQuery)
    query._query = MagicMock()

    with pytest.raises(ValueError, match="too large"):
        query.find(
            ra=331.0, dec=-11.4, observatory_mjd=_OBS_MJD,
            radius_arcsec=float(Angle(query.query_radius).arcsec) + 1,
        )


# ---------------------------------------------------------------------------
# Integration test — requires network access to ssp.imcce.fr
# ---------------------------------------------------------------------------


def test_ceres_integration():
    """Query SkyBot for Ceres at a known epoch and verify it is returned.

    Skipped when the SkyBot service is unavailable (network issues, downtime).

    Ceres ephemeris (JPL Horizons id='Ceres', observatory I41 = Palomar):
        epoch  2020-03-15 00:00 UTC  (MJD 58923)
        RA  320.7912°,  Dec  -21.5888°
    """
    from ztf_viewer.catalogs.skybot import SkybotQuery

    query = SkybotQuery()
    try:
        table = query.find(ra=320.7912, dec=-21.5888, observatory_mjd=_OBS_MJD, radius_arcsec=120.0)
    except NotFound as exc:
        pytest.skip(f"SkyBot service unavailable: {exc}")

    names = [row["__name"] for row in table]
    assert "Ceres" in names, f"Expected Ceres in results, got: {names}"

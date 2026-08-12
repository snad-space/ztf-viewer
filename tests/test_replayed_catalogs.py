"""Offline counterparts of the ``live`` tests: the same app code, recorded upstreams.

These run in the default ``pytest`` invocation with sockets blocked.  They are the
before/after net for the async migration: whatever ``aio-snad-apis`` /
``aio-conesearch`` / ``aio-gather`` do to the call sites, these assertions must keep
holding against the very same recorded bytes.

Imports live inside the test bodies — ``tests/conftest.py`` swaps the cache
implementation in ``pytest_runtest_setup`` and ``@cache()`` binds at import time.
"""

import pytest
from astropy.coordinates import SkyCoord
from numpy.testing import assert_allclose

OID = 633207400004730
DR = "dr8"


# --- SNAD APIs -------------------------------------------------------------------


def test_ztf_dr_meta():
    from ztf_viewer.catalogs.ztf_dr import find_ztf_oid

    meta = find_ztf_oid.get_meta(OID, DR)
    assert meta["filter"] == "zr"
    assert meta["fieldid"] == 633
    assert_allclose(find_ztf_oid.get_coord(OID, DR), (247.4554285, 24.772822), atol=1e-6)


def test_ztf_dr_light_curve():
    from ztf_viewer.catalogs.ztf_dr import find_ztf_oid

    lc = find_ztf_oid.get_lc(OID, DR)
    assert len(lc) > 0
    assert set(lc[0]) >= {"mjd", "mag", "magerr"}


def test_ztf_dr_circle():
    from ztf_viewer.catalogs.ztf_dr import find_ztf_circle

    j = find_ztf_circle.find(ra=247.4554285, dec=24.772822, radius_arcsec=1.0, dr=DR)
    assert str(OID) in j
    assert j[str(OID)]["separation"] == pytest.approx(0.0, abs=1e-2)


def test_features_versions_and_call():
    from ztf_viewer.lc_features import light_curve_features

    assert "latest" in light_curve_features.versions()
    features = light_curve_features(OID, DR, "latest")
    assert isinstance(features, dict) and features


def test_model_fit_list_models():
    from ztf_viewer.model_fit import model_fit

    response = model_fit.get_list_models()
    assert response.success
    assert response.data


def test_akb_bad_token_is_unauthorized():
    from ztf_viewer.akb import akb
    from ztf_viewer.exceptions import UnAuthorized

    with pytest.raises(UnAuthorized):
        akb.whoami("not-a-real-token")


def test_ztf_ref_get():
    """Exercises the ``astropy.io.fits.open(url)`` path, replayed via the same store."""
    from ztf_viewer.catalogs.ztf_ref import ztf_ref

    record = ztf_ref.get(OID, DR)
    assert record["sourceid"] == 4730
    assert record["mag"] == pytest.approx(-5.436)
    assert record["magzp"] == pytest.approx(26.275)


# --- cone-search catalogs --------------------------------------------------------


def test_tns_resolve_name():
    from ztf_viewer.catalogs.conesearch.tns import TnsQuery

    coord = TnsQuery("Test TNS").resolve_name("2018lwh")
    assert isinstance(coord, SkyCoord)
    assert_allclose((coord.ra.deg, coord.dec.deg), (247.45543, 24.77282))


def test_antares_resolve_name():
    from ztf_viewer.catalogs.conesearch.antares import AntaresQuery

    coord = AntaresQuery("Test Antares").resolve_name("ZTF18aagrczj")
    assert_allclose((coord.ra.deg, coord.dec.deg), (230.71268, 41.05182), atol=1e-4)


def test_ogle_cone_search():
    from ztf_viewer.catalogs.conesearch.ogle import OgleQuery

    table = OgleQuery("Test OGLE")._api_query_region(267.574250, -22.214500, radius_arcsec=5.0)
    ids = list(table["ID"])
    assert "OGLE-BLG-RRLYR-04010" in ids
    idx = ids.index("OGLE-BLG-RRLYR-04010")
    assert table["Type"][idx] == "RRLyr"
    # the light-curve PNG is replayed too, not stubbed out
    assert "data:image/png;base64," in table["light_curve"][idx]


def test_ogle_cone_search_not_found():
    from ztf_viewer.catalogs.conesearch.ogle import OgleQuery
    from ztf_viewer.exceptions import NotFound

    with pytest.raises(NotFound):
        OgleQuery("Test OGLE 2").find(ra=0.0, dec=60.0, radius_arcsec=1.0)


def test_otter_cone_search():
    from ztf_viewer.catalogs.conesearch.otter import OtterQuery

    table = OtterQuery("Test Otter")._api_query_region(ra=185.0, dec=12.0, radius_arcsec=3600.0)
    assert "SN2019duk" in list(table["default_name"])


def test_otter_cone_search_not_found():
    from ztf_viewer.catalogs.conesearch.otter import OtterQuery
    from ztf_viewer.exceptions import NotFound

    with pytest.raises(NotFound):
        OtterQuery("Test Otter 3")._api_query_region(ra=185.0, dec=12.0, radius_arcsec=1.0)


def test_panstarrs_stack_query():
    from ztf_viewer.catalogs.conesearch.panstarrs import PanstarrsDr2StackedQuery

    query = PanstarrsDr2StackedQuery("test")
    coord = SkyCoord(ra=230.71268, dec=41.05182, unit="deg")
    table = query._query_region(coord, f"{0.05 * 3600}s")
    assert len(table) > 0
    assert "raMean" in table.colnames
    # regression for issue #565: "None" strings must arrive masked, not as strings
    assert table["pmra"].mask.any()


def test_skybot_cone_search():
    """The Ceres cone search, offline.

    The live version of this test (``tests/catalogs/test_skybot.py``) is genuinely
    flaky — ssp.imcce.fr intermittently answers HTTP 500 with a perfectly valid
    VOTable body, and times out — which is exactly why it needs a replayed twin.
    """
    from ztf_viewer.catalogs.skybot import SkybotQuery

    result = SkybotQuery().find(ra=320.7912, dec=-21.5888, observatory_mjd=58923.0, radius_arcsec=120.0)
    assert "Ceres" in [row["__name"] for row in result]


def test_simbad_cone_search():
    from ztf_viewer.catalogs.conesearch.simbad import SimbadQuery

    coord = SkyCoord(ra=10.6847, dec=41.2687, unit="deg")  # M31
    table = SimbadQuery("Test Simbad")._query_region(coord, "10s")
    assert table is not None
    assert len(table) > 0
    assert "main_id" in table.colnames

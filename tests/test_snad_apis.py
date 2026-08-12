"""Live smoke tests for the first-party SNAD APIs.

These exist mainly as *recording entry points*: running them with ``--record-http``
captures the upstream responses that the offline suite replays (see
``tests/httpfixtures/README.md``).  They double as drift detectors for our own
services.

Imports stay inside the test bodies on purpose — ``tests/conftest.py`` swaps the cache
implementation in ``pytest_runtest_setup``, and ``@cache()`` binds at import time.
"""

import pytest

# Same object as tests/catalogs/test_ztf_ref.py, so the fixtures line up.
OID = 633207400004730
DR = "dr8"


@pytest.mark.live
def test_ztf_dr_find_oid():
    from ztf_viewer.catalogs.ztf_dr import find_ztf_oid

    meta = find_ztf_oid.get_meta(OID, DR)
    assert meta["filter"] == "zr"
    assert meta["fieldid"] == 633


@pytest.mark.live
def test_ztf_dr_circle():
    from ztf_viewer.catalogs.ztf_dr import find_ztf_circle

    j = find_ztf_circle.find(ra=247.4554285, dec=24.772822, radius_arcsec=1.0, dr=DR)
    assert str(OID) in j


@pytest.mark.live
def test_features_versions():
    from ztf_viewer.lc_features import light_curve_features

    versions = light_curve_features.versions()
    assert "latest" in versions


@pytest.mark.live
def test_features_call():
    from ztf_viewer.lc_features import light_curve_features

    features = light_curve_features(OID, DR, "latest")
    assert isinstance(features, dict)
    assert len(features) > 0


@pytest.mark.live
def test_model_fit_list_models():
    from ztf_viewer.model_fit import model_fit

    response = model_fit.get_list_models()
    assert response.success
    assert response.data


@pytest.mark.live
def test_akb_without_token_is_unauthorized():
    """The anonymous AKB path — recorded so the 401 branch is testable offline."""
    from ztf_viewer.akb import akb
    from ztf_viewer.exceptions import UnAuthorized

    with pytest.raises(UnAuthorized):
        akb.whoami("not-a-real-token")

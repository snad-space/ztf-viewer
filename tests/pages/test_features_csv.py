"""The features CSV route: rendering, query-parameter plumbing and error mapping.

Hermetic -- `light_curve_features` is stubbed out, so nothing here talks to the feature
extraction service. The endpoint is called directly rather than through a `TestClient`: building
one imports `ztf_viewer.__main__` and runs the ASGI lifespan, which registers Dash's `{path:path}`
catch-all on the shared app (see `tests/test_golden_http.py`), and none of that is needed to pin
what this module authors.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from starlette.datastructures import QueryParams

from ztf_viewer import config

# `ztf_viewer.catalogs` connects to Redis at import time unless told otherwise, and `lc_features`
# pulls it in. `tests/conftest.py`'s per-test hook runs too late for a collection-time import.
config.CACHE_TYPE = "memory"
config.UNAVAILABLE_CATALOGS_CACHE_TYPE = "memory"

from ztf_viewer.exceptions import NotFound
from ztf_viewer.pages import features_csv

DR = "dr24"
OID = 633207400004730

FEATURES = {"amplitude": 0.5, "beyond_1_std": 0.25, "anderson_darling_normal": 1.5}


def _request(query=""):
    return SimpleNamespace(query_params=QueryParams(query))


def test_features_to_csv_is_sorted_and_has_a_header():
    csv = features_csv.features_to_csv(FEATURES)
    assert csv.splitlines() == [
        "feature,value",
        "amplitude,0.5",
        "anderson_darling_normal,1.5",
        "beyond_1_std,0.25",
    ]


def test_features_to_csv_of_no_features():
    assert features_csv.features_to_csv({}) == "feature,value\r\n"


async def test_response_features_csv():
    async def fake_features(oid, dr, version, min_mjd=None, max_mjd=None):
        return FEATURES

    with patch.object(features_csv, "light_curve_features", fake_features):
        response = await features_csv.response_features_csv(DR, OID, _request())

    assert response.status_code == 200
    assert response.media_type == "text/csv"
    assert response.headers["content-disposition"] == f"attachment; filename={OID}_features.csv"
    assert response.body.decode().startswith("feature,value")


async def test_response_features_csv_passes_query_parameters_through():
    calls = []

    async def fake_features(oid, dr, version, min_mjd=None, max_mjd=None):
        calls.append((oid, dr, version, min_mjd, max_mjd))
        return FEATURES

    with patch.object(features_csv, "light_curve_features", fake_features):
        await features_csv.response_features_csv(DR, OID, _request("version=v0.2&min_mjd=58000.5&max_mjd=59000"))

    assert calls == [(OID, DR, "v0.2", 58000.5, 59000.0)]


async def test_response_features_csv_defaults_to_the_latest_version_and_no_mjd_limits():
    calls = []

    async def fake_features(oid, dr, version, min_mjd=None, max_mjd=None):
        calls.append((version, min_mjd, max_mjd))
        return FEATURES

    with patch.object(features_csv, "light_curve_features", fake_features):
        await features_csv.response_features_csv(DR, OID, _request())

    assert calls == [("latest", None, None)]


@pytest.mark.parametrize("query", ["min_mjd=not-a-number", "max_mjd=not-a-number"])
async def test_response_features_csv_rejects_a_non_float_mjd(query):
    async def fake_features(oid, dr, version, min_mjd=None, max_mjd=None):
        raise AssertionError("must not be called for an invalid query parameter")

    with patch.object(features_csv, "light_curve_features", fake_features):
        response = await features_csv.response_features_csv(DR, OID, _request(query))

    assert response.status_code == 400


async def test_response_features_csv_of_an_unknown_object():
    async def fake_features(oid, dr, version, min_mjd=None, max_mjd=None):
        raise NotFound

    with patch.object(features_csv, "light_curve_features", fake_features):
        response = await features_csv.response_features_csv(DR, OID, _request())

    assert response.status_code == 404

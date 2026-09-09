"""Light-curve feature CSV download route.

Kept out of `lc_csv.py`: the features come from the feature-extraction service rather than from
a light-curve catalog, and unlike a light curve they are a flat name -> value mapping, so the
CSV is two columns rather than one row per observation.
"""

import csv
from io import StringIO

from fastapi import Request

from ztf_viewer.app import app
from ztf_viewer.exceptions import NotFound
from ztf_viewer.lc_features import light_curve_features
from ztf_viewer.web import csv_response, error_response, query_args


def features_to_csv(features: dict) -> str:
    """Render a feature mapping as a two-column CSV, sorted by feature name."""
    string_io = StringIO()
    writer = csv.writer(string_io, lineterminator="\r\n")
    writer.writerow(["feature", "value"])
    writer.writerows(sorted(features.items()))
    return string_io.getvalue()


@app.server.api_route("/{dr}/features/{oid}")
async def response_features_csv(dr: str, oid: int, request: Request):
    """Download the light-curve features of a single OID as CSV.

    `version` selects the feature-extraction API version, mirroring the dropdown on the viewer
    page; `min_mjd`/`max_mjd` restrict the light curve the features are computed from, exactly
    as they do for the light-curve CSV.
    """
    args = query_args(request)

    version = args.get("version", "latest")

    mjd = {}
    for key in ("min_mjd", "max_mjd"):
        value = args.get(key, None)
        if value is not None:
            try:
                value = float(value)
            except ValueError:
                return error_response(f"{key} query parameter must be a float", 400)
        mjd[key] = value

    try:
        features = await light_curve_features(oid, dr, version=version, **mjd)
    except NotFound:
        return error_response("", 404)
    return csv_response(features_to_csv(features), filename=f"{oid}_features.csv")

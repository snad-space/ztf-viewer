from io import StringIO

import pandas as pd
from flask import Response, request

from ztf_viewer.app import app
from ztf_viewer.catalogs import find_ztf_oid
from ztf_viewer.exceptions import NotFound, CatalogUnavailable
from ztf_viewer.catalogs.ztf_ref import ztf_ref
from ztf_viewer.catalogs.conesearch import ANTARES_QUERY, GAIA_DR3, PANSTARRS_DR2_QUERY


def get_csv(dr, oids, min_mjd=None, max_mjd=None):
    dfs = []
    for oid in oids:
        lc = find_ztf_oid.get_lc(oid, dr, min_mjd=min_mjd, max_mjd=max_mjd)
        if lc is None:
            raise NotFound
        meta = find_ztf_oid.get_meta(oid, dr)
        oid_df = pd.DataFrame.from_records(lc)
        oid_df["oid"] = oid
        oid_df["filter"] = meta["filter"]

        try:
            ref = ztf_ref.get(oid, dr)
        except (NotFound, CatalogUnavailable):
            oid_df["ref"] = [None] * oid_df.shape[0]
            oid_df["ref_err"] = [None] * oid_df.shape[0]
        else:
            ref_mag = ref["mag"] + ref["magzp"]
            ref_err = ref["sigmag"]
            oid_df["ref"] = ref_mag
            oid_df["ref_err"] = ref_err

        dfs.append(oid_df)
    df = pd.concat(dfs, axis="index")
    df.sort_values(by="mjd", inplace=True)
    df = df[["oid", "filter", "mjd", "mag", "magerr", "clrcoeff", "ref", "ref_err"]]

    string_io = StringIO()
    df.to_csv(string_io, index=False)
    return string_io.getvalue()


@app.server.route("/<dr>/csv/<int:oid>")
def response_csv(dr, oid):
    try:
        other_oids = set(map(int, request.args.getlist("other_oid")))
    except ValueError:
        return "other_oid query parameter must be an integer", 400
    oids = set.union({oid}, other_oids)

    min_mjd = request.args.get("min_mjd", None)
    if min_mjd is not None:
        try:
            min_mjd = float(min_mjd)
        except ValueError:
            return "min_mjd query parameter must be a float", 400

    max_mjd = request.args.get("max_mjd", None)
    if max_mjd is not None:
        try:
            max_mjd = float(max_mjd)
        except ValueError:
            return "max_mjd query parameter must be a float", 400

    try:
        csv = get_csv(dr, oids, min_mjd=min_mjd, max_mjd=max_mjd)
    except NotFound:
        return "", 404
    return Response(
        csv,
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename={oid}.csv"},
    )


def _lc_to_csv_response(lc, filename):
    """Convert a list-of-dicts light curve to a CSV Flask Response."""
    if not lc:
        return "", 404
    df = pd.DataFrame.from_records(lc)
    df.sort_values(by="mjd", inplace=True)
    string_io = StringIO()
    df.to_csv(string_io, index=False)
    return Response(
        string_io.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename={filename}"},
    )


@app.server.route("/panstarrs/csv/<int:obj_id>")
def response_panstarrs_csv(obj_id):
    """Download Pan-STARRS DR2 light curve for a given objID as CSV."""
    try:
        lc = PANSTARRS_DR2_QUERY.light_curve(id=None, row={"objID": obj_id})
    except (NotFound, CatalogUnavailable):
        return "", 404
    return _lc_to_csv_response(lc, f"panstarrs_{obj_id}.csv")


@app.server.route("/gaia/csv/<int:source_id>")
def response_gaia_csv(source_id):
    """Download Gaia DR3 epoch photometry for a given Source ID as CSV."""
    try:
        lc = GAIA_DR3.light_curve(id=source_id)
    except (NotFound, CatalogUnavailable):
        return "", 404
    return _lc_to_csv_response(lc, f"gaia_{source_id}.csv")


@app.server.route("/antares/csv/<locus_id>")
def response_antares_csv(locus_id):
    """Download Antares light curve for a given locus ID as CSV."""
    try:
        lc = ANTARES_QUERY.light_curve(id=locus_id)
    except (NotFound, CatalogUnavailable):
        return "", 404
    return _lc_to_csv_response(lc, f"antares_{locus_id}.csv")

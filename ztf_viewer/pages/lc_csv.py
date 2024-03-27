from io import StringIO

import pandas as pd
from flask import Response, request

from ztf_viewer.app import app
from ztf_viewer.catalogs import find_ztf_oid
from ztf_viewer.exceptions import NotFound
from ztf_viewer.catalogs.ztf_ref import ztf_ref


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
        except NotFound:
            pass
        else:
            ref_mag = ref["mag"] + ref["magzp"]
            ref_err = ref["sigmag"]
            oid_df["ref"] = ref_mag
            oid_df["ref_err"] = ref_err

        dfs.append(oid_df)
    df = pd.concat(dfs, axis="index")
    df.sort_values(by="mjd", inplace=True)
    # df = df[["oid", "filter", "mjd", "mag", "magerr", "clrcoeff", "ref", "ref_err"]]
    try:
        df = df[["oid", "filter", "mjd", "mag", "magerr", "clrcoeff", "ref", "ref_err"]]
    except KeyError:
        df = df[["oid", "filter", "mjd", "mag", "magerr", "clrcoeff"]]

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

from io import StringIO

import pandas as pd
from flask import Response, request

from ztf_viewer.app import app
from ztf_viewer.catalogs import find_ztf_oid
from ztf_viewer.exceptions import NotFound


def get_csv(dr, oids):
    dfs = []
    for oid in oids:
        lc = find_ztf_oid.get_lc(oid, dr)
        if lc is None:
            raise NotFound
        meta = find_ztf_oid.get_meta(oid, dr)
        oid_df = pd.DataFrame.from_records(lc)
        oid_df["oid"] = oid
        oid_df["filter"] = meta["filter"]
        dfs.append(oid_df)
    df = pd.concat(dfs, axis="index")
    df.sort_values(by="mjd", inplace=True)
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
    try:
        csv = get_csv(dr, oids)
    except NotFound:
        return "", 404
    return Response(
        csv,
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename={oid}.csv"},
    )

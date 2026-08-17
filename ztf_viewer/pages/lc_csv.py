"""CSV download routes.

Registration order matters here: routes are matched in the order they are registered, first
match wins, so the specific catalog routes must be registered before the generic
`/{dr}/csv/{oid}` one.
"""

import asyncio
from io import StringIO

import pandas as pd
from fastapi import Request

from ztf_viewer.app import app
from ztf_viewer.catalogs import find_ztf_oid
from ztf_viewer.exceptions import NotFound, CatalogUnavailable
from ztf_viewer.catalogs.ztf_ref import ztf_ref
from ztf_viewer.catalogs.conesearch import ANTARES_QUERY, GAIA_DR3, PANSTARRS_DR2_QUERY
from ztf_viewer.web import csv_response, error_response, query_args


async def get_csv(dr, oids, min_mjd=None, max_mjd=None):
    dfs = []
    for oid in oids:
        lc = await find_ztf_oid.get_lc(oid, dr, min_mjd=min_mjd, max_mjd=max_mjd)
        if lc is None:
            raise NotFound
        meta = await find_ztf_oid.get_meta(oid, dr)
        oid_df = pd.DataFrame.from_records(lc)
        oid_df["oid"] = oid
        oid_df["filter"] = meta["filter"]

        try:
            ref = await ztf_ref.get(oid, dr)
        except NotFound, CatalogUnavailable:
            oid_df["ref"] = [None] * oid_df.shape[0]
            oid_df["ref_err"] = [None] * oid_df.shape[0]
        else:
            ref_mag = ref["mag"] + ref["magzp"]
            ref_err = ref["sigmag"]
            oid_df["ref"] = ref_mag
            oid_df["ref_err"] = ref_err

        dfs.append(oid_df)
    return await asyncio.to_thread(_dfs_to_csv, dfs)


def _dfs_to_csv(dfs):
    df = pd.concat(dfs, axis="index")
    df.sort_values(by="mjd", inplace=True)
    df = df[["oid", "filter", "mjd", "mag", "magerr", "clrcoeff", "ref", "ref_err"]]

    string_io = StringIO()
    df.to_csv(string_io, index=False)
    return string_io.getvalue()


def _lc_to_csv_response(lc, filename):
    """Convert a list-of-dicts light curve to a CSV response."""
    if not lc:
        return error_response("", 404)
    df = pd.DataFrame.from_records(lc)
    df.sort_values(by="mjd", inplace=True)
    string_io = StringIO()
    df.to_csv(string_io, index=False)
    return csv_response(string_io.getvalue(), filename=filename)


@app.server.api_route("/panstarrs/csv/{obj_id}")
async def response_panstarrs_csv(obj_id: int):
    """Download Pan-STARRS DR2 light curve for a given objID as CSV."""
    try:
        lc = await PANSTARRS_DR2_QUERY.light_curve(id=None, row={"objID": obj_id})
    except NotFound, CatalogUnavailable:
        return error_response("", 404)
    return _lc_to_csv_response(lc, f"panstarrs_{obj_id}.csv")


@app.server.api_route("/gaia/csv/{source_id}")
def response_gaia_csv(source_id: int):
    """Download Gaia DR3 epoch photometry for a given Source ID as CSV."""
    try:
        lc = GAIA_DR3.light_curve(id=source_id)
    except NotFound, CatalogUnavailable:
        return error_response("", 404)
    return _lc_to_csv_response(lc, f"gaia_{source_id}.csv")


@app.server.api_route("/antares/csv/{locus_id}")
def response_antares_csv(locus_id: str):
    """Download Antares light curve for a given locus ID as CSV."""
    try:
        lc = ANTARES_QUERY.light_curve(id=locus_id)
    except NotFound, CatalogUnavailable:
        return error_response("", 404)
    return _lc_to_csv_response(lc, f"antares_{locus_id}.csv")


# Keep last: `oid` is an int, so this also matches the catalog routes above.
@app.server.api_route("/{dr}/csv/{oid}")
async def response_csv(dr: str, oid: int, request: Request):
    args = query_args(request)

    try:
        other_oids = set(map(int, args.getlist("other_oid")))
    except ValueError:
        return error_response("other_oid query parameter must be an integer", 400)
    oids = set.union({oid}, other_oids)

    min_mjd = args.get("min_mjd", None)
    if min_mjd is not None:
        try:
            min_mjd = float(min_mjd)
        except ValueError:
            return error_response("min_mjd query parameter must be a float", 400)

    max_mjd = args.get("max_mjd", None)
    if max_mjd is not None:
        try:
            max_mjd = float(max_mjd)
        except ValueError:
            return error_response("max_mjd query parameter must be a float", 400)

    try:
        csv = await get_csv(dr, oids, min_mjd=min_mjd, max_mjd=max_mjd)
    except NotFound:
        return error_response("", 404)
    return csv_response(csv, filename=f"{oid}.csv")

from io import StringIO

import pandas as pd
from flask import Response

from ztf_viewer.app import app
from ztf_viewer.catalogs import find_ztf_oid
from ztf_viewer.exceptions import NotFound


def get_csv(dr, oid):
    lc = find_ztf_oid.get_lc(oid, dr)
    if lc is None:
        raise NotFound
    df = pd.DataFrame.from_records(lc)
    string_io = StringIO()
    df.to_csv(string_io, index=False)
    return string_io.getvalue()


@app.server.route('/<dr>/csv/<int:oid>')
def response_csv(dr, oid):
    try:
        csv = get_csv(dr, oid)
    except NotFound:
        return '', 404
    return Response(
        csv,
        mimetype='text/csv',
        headers={'Content-disposition': f'attachment; filename={oid}.csv'},
    )

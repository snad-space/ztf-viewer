from io import StringIO

import dash
import pandas as pd
from flask import Response


from cross import find_ztf_oid
from util import get_db_api_version_from_dr


def flask_csv(dr, oid):
    api_version = get_db_api_version_from_dr(dr)
    lc = find_ztf_oid.get_lc(oid, api_version)
    if lc is None:
        return '', 404
    df = pd.DataFrame.from_records(lc)
    string_io = StringIO()
    df.to_csv(string_io, index=False)
    return Response(
        string_io.getvalue(),
        mimetype='text/csv',
        headers={'Content-disposition': f'attachment; filename={oid}.csv'},
    )


app = dash.Dash(
    __name__,
    external_stylesheets=[],
    external_scripts=[],
)
app.config.suppress_callback_exceptions = True
app.server.route("/<dr>/csv/<int:oid>")(flask_csv)

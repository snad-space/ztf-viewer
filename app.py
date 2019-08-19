from io import StringIO

import dash
import pandas as pd
from flask import Response


from cross import find_ztf_oid


def flask_csv(oid):
    lc = find_ztf_oid.get_lc(oid)
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
app.server.route("/csv/<int:oid>")(flask_csv)

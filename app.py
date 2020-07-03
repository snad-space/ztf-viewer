from io import StringIO

import dash
import pandas as pd
from flask import Response


from cross import find_ztf_oid


def flask_csv(dr, oid):
    lc = find_ztf_oid.get_lc(oid, dr)
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


js9_css = [
    '/static/js9/js9support.css',
    '/static/js9/js9.css',
]

js9_js = [
    '/static/js/js9prefs.js',
    '/static/js9/js9support.min.js',
    '/static/js9/js9.min.js',
    '/static/js9/js9plugins.js',
]


app = dash.Dash(
    __name__,
    external_stylesheets=js9_css,
    external_scripts=js9_js,
)
app.config.suppress_callback_exceptions = True
app.server.route("/<dr>/csv/<int:oid>")(flask_csv)

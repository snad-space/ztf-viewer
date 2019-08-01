from io import StringIO

import dash
from flask import Response


from db import get_light_curve


def flask_csv(oid):
    lc = get_light_curve(oid)
    if lc is None:
        return ''
    string_io = StringIO()
    lc.to_csv(string_io, index=False)
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

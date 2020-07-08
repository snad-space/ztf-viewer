import dash_html_components as html
import flask
from dash.dependencies import Input, Output, State
from dash.exceptions import PreventUpdate
from dash_table import DataTable

from app import app
from secret import is_user_token_valid


def get_layout(pathname):
    return html.Div([
        html.H1('Anomaly knowledge base'),
        DataTable(
            id='anomaly-table',
            columns=[
                {'name': 'OID', 'id': 'oid'},
                {'name': 'Anomaly?', 'id': 'is_anomaly'},
                {'name': 'Field ID', 'id': 'fieldid'},
                {'name': 'Filter', 'id': 'filter'},
                {'name': 'Object type', 'id': 'object_type'},
                {'name': 'Description', 'id': 'description'},
            ]
        ),
    ])


@app.callback(
    Output('anomaly-table', 'data'),
    [Input('url', 'pathname')],
)
def set_table_data(pathname):
    if not is_user_token_valid(flask.request.cookies.get('login_token')):
        raise PreventUpdate
    return

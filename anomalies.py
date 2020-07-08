import dash_html_components as html
import flask
import pandas as pd
from dash.dependencies import Input, Output, State
from dash.exceptions import PreventUpdate
from dash_table import DataTable

from akb import akb
from app import app
from secret import is_user_token_valid


def get_layout(pathname):
    return html.Div([
        html.H1('Anomaly knowledge base'),
        DataTable(
            id='anomaly-table',
            columns=[
                {'name': 'OID', 'id': 'oid_link', 'presentation': 'markdown'},
                {'name': 'Tags', 'id': 'tags_str'},
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
    objs = akb.get_objects()
    objs = sorted(objs, key=lambda obj: obj['id'])
    for item in objs:
        oid = item['oid']
        item['oid_link'] = f'[{oid}](/view/{oid})'
        item['tags_str'] = ', '.join(item['tags'])
    return objs

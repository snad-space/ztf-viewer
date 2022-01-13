from datetime import datetime

from dash import html, Input, Output
from dash.exceptions import PreventUpdate
from dash.dash_table import DataTable

from ztf_viewer.akb import akb
from ztf_viewer.app import app


def get_layout(pathname):
    return html.Div([
        html.H1('Anomaly knowledge base'),
        DataTable(
            id='anomaly-table',
            columns=[
                {'name': 'OID', 'id': 'oid_link', 'presentation': 'markdown'},
                {'name': 'Tags', 'id': 'tags_str'},
                {'name': 'Description', 'id': 'description'},
                {'name': 'Changed by', 'id': 'changed_by'},
                {'name': 'Changed at', 'id': 'changed_at_datetime', 'type': 'datetime'},
            ],
            filter_action='native',
            sort_action='native',
            page_action='native',
            style_data={
                'whiteSpace': 'normal',
                'height': 'auto',
            },
        ),
        html.Br(),
        'See filtering syntax ',
        html.A('here', href='https://dash.plotly.com/datatable/filtering'),
    ])


@app.callback(
    Output('anomaly-table', 'data'),
    [Input('url', 'pathname')],
)
def set_table_data(pathname):
    if not akb.is_token_valid():
        raise PreventUpdate
    objs = akb.get_objects()
    objs = sorted(objs, key=lambda obj: obj['oid'])
    for item in objs:
        oid = item['oid']
        item['oid_link'] = f'[{oid}](/view/{oid})'
        item['tags_str'] = ', '.join(item['tags'])
        item['changed_at_datetime'] = datetime.fromisoformat(item['changed_at'].replace('Z', '+00:00'))
    return objs

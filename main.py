#!/usr/bin/env python3

import logging
import re

import dash_core_components as dcc
import dash_html_components as html
from dash.dependencies import Input, Output, State

from app import app
from viewer import get_layout as get_viewer_layout


app.layout = html.Div([
    dcc.Location(id='url', refresh=True),
    html.Div(
        [
            dcc.Input(
                id='input-oid',
                placeholder='oid',
                type='text',
                minLength=15,
                maxLength=15,
                n_submit=0,
            ),
            html.Button(
                'Go',
                id='button-oid',
                n_clicks=0,
            ),
        ]
    ),
    html.Div(id='page-content'),
])


@app.callback(
    Output('url', 'pathname'),
    [
        Input('button-oid', 'n_clicks'),
        Input('input-oid', 'n_submit'),
    ],
    state=[
        State('input-oid', 'value'),
        State('url', 'pathanme'),
    ]
)
def go_to_oid_view(n_clicks, n_submit, oid, current_pathaname):
    if (n_submit == 0 and n_clicks == 0) or oid is None:
        return current_pathaname
    return f'/view/{oid}'


@app.callback(
    Output('page-content', 'children'),
    [Input('url', 'pathname')]
)
def app_select_by_url(pathname):
    if re.search(r'/+$', pathname):
        return html.Div()
    if re.search(r'/+view/+\d{15}/*', pathname):
        return get_viewer_layout(pathname)
    return html.H1('404')


if __name__ == '__main__':
    app.run_server(debug=True)

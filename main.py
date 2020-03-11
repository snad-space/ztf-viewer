#!/usr/bin/env python3

import logging
import re
import urllib.parse

from astropy.coordinates.name_resolve import get_icrs_coordinates, NameResolveError

import dash_core_components as dcc
import dash_html_components as html
from dash.dependencies import Input, Output, State

from app import app
from search import get_layout as get_search_layout
from viewer import get_layout as get_viewer_layout


logging.basicConfig(level=logging.INFO)


app.layout = html.Div([
    dcc.Location(id='url', refresh=True),
    html.Div(
        [
            html.H1('ZTF object viewer'),
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
    html.Div(
        [
            dcc.Input(
                id='input-coord-or-name',
                placeholder='Coordinates or object name',
                type='text',
                minLength=1,
                maxLength=50,
                n_submit=0,
            ),
            dcc.Input(
                value='1',
                id='input-search-radius',
                placeholder='radius, arcsec',
                type='number',
                step='0.1',
                min='0',
                max='60',
                n_submit=0,
            ),
            html.Button(
                'Go',
                id='button-coord-or-name',
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
        Input('button-coord-or-name', 'n_clicks'),
        Input('input-coord-or-name', 'n_submit'),
        Input('input-search-radius', 'n_submit'),
    ],
    state=[
        State('input-oid', 'value'),
        State('input-coord-or-name', 'value'),
        State('input-search-radius', 'value'),
        State('url', 'pathanme'),
    ]
)
def go_to_url(n_clicks_oid, n_submit_oid, n_clicks_search,
              n_submit_coord_or_name, n_submit_radius,
              oid,
              coord_or_name, radius_arcsec,
              current_pathaname):
    if (n_submit_oid != 0 or n_clicks_oid != 0) and oid is not None:
        return f'/view/{oid}'
    if n_clicks_search != 0 or n_submit_coord_or_name != 0 or n_submit_radius != 0:
        coord_or_name = urllib.parse.quote(coord_or_name)
        return f'/search/{coord_or_name}/{radius_arcsec}'
    return current_pathaname


@app.callback(
    Output('page-content', 'children'),
    [Input('url', 'pathname')]
)
def app_select_by_url(pathname):
    if re.search(r'^/+$', pathname):
        return html.Div(
            [
                'Example: ',
                html.A('HZ Her, zg passband', href='/view/680113300005170'),
            ]
        )
    if re.search(r'^/+view/+\d{15}/*$', pathname):
        return get_viewer_layout(pathname)
    search_match = re.search(r'^/+search/(?P<coord_or_name>[^/]+)/(?P<radius_arcsec>[^/]+)/*$', pathname)
    if search_match:
        try:
            coord_or_name = urllib.parse.unquote(search_match['coord_or_name'])
            coordinates = get_icrs_coordinates(coord_or_name)
        except NameResolveError:
            return html.Div(
                [
                    html.H1('404'),
                    html.P('Cannot find such coordinate or name'),
                ]
            )
        try:
            radius_arcsec = float(search_match['radius_arcsec'])
        except ValueError:
            return html.Div(
                [
                    html.H1('404'),
                    html.P('Wrong radius format'),
                ]
            )

        return get_search_layout(coordinates, radius_arcsec)
    return html.H1('404')


def server():
    """Entrypoint for Gunicorn"""
    return app.server


if __name__ == '__main__':
    app.run_server(debug=True)

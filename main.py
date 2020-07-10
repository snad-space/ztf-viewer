#!/usr/bin/env python3

import logging
import pathlib
import re
import urllib.parse
from functools import partial

from astropy.coordinates.name_resolve import get_icrs_coordinates, NameResolveError

import dash_core_components as dcc
import dash_html_components as html
from dash.dependencies import Input, Output, State

from app import app
from search import get_layout as get_search_layout
from util import default_dr
from viewer import get_layout as get_viewer_layout


logging.basicConfig(level=logging.INFO)


app.layout = html.Div([
    dcc.Location(id='url', refresh=True),
    html.Div(
        [
            html.H1(
                [
                    html.A('SNAD ZTF', href='/'),
                    ' ',
                    # html.Div('DR1', id='dr1-switch', style={'display': 'inline-block'}),
                    # ' / ',
                    html.Div('DR2', id='dr2-switch', style={'display': 'inline-block'}),
                    ' / ',
                    html.Div('DR3', id='dr3-switch', style={'display': 'inline-block'}),
                    ' object viewer',
                ],
            ),
            dcc.Input(
                id='input-oid',
                placeholder='oid',
                type='text',
                minLength=15,
                maxLength=15,
                n_submit=0,
            ),
            html.Div(
                default_dr,
                id='data-release',
                style={'display': 'none'},
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
    Output('data-release', 'children'),
    [Input('url', 'pathname')],
)
def dr_from_url(url):
    parts = pathlib.Path(url).parts
    if len(parts) < 2:
        return default_dr
    if parts[1].lower().startswith('dr'):
        return parts[1]
    return default_dr


def dr_switch(current_dr, current_url, switch_dr):
    if switch_dr == current_dr:
        return current_dr.upper()
    if current_dr in current_url:
        switch_url = current_url.replace(current_dr, switch_dr)
    else:
        switch_url = f'/{switch_dr}{current_url}'
    return html.A(switch_dr.upper(), href=switch_url, style={'text-decoration-style': 'dashed'})


app.callback(
    Output('dr1-switch', 'children'),
    [Input('data-release', 'children')],
    state=[State('url', 'pathname')]
)(partial(dr_switch, switch_dr='dr1'))

app.callback(
    Output('dr2-switch', 'children'),
    [Input('data-release', 'children')],
    state=[State('url', 'pathname')]
)(partial(dr_switch, switch_dr='dr2'))


app.callback(
    Output('dr3-switch', 'children'),
    [Input('data-release', 'children')],
    state=[State('url', 'pathname')]
)(partial(dr_switch, switch_dr='dr3'))


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
        State('url', 'pathname'),
        State('data-release', 'children'),
    ]
)
def go_to_url(n_clicks_oid, n_submit_oid, n_clicks_search,
              n_submit_coord_or_name, n_submit_radius,
              oid,
              coord_or_name, radius_arcsec,
              current_pathaname,
              dr):
    if (n_submit_oid != 0 or n_clicks_oid != 0) and oid is not None:
        return f'/{dr}/view/{oid}'
    if n_clicks_search != 0 or n_submit_coord_or_name != 0 or n_submit_radius != 0:
        coord_or_name = urllib.parse.quote(coord_or_name)
        return f'/{dr}/search/{coord_or_name}/{radius_arcsec}'
    return current_pathaname


@app.callback(
    Output('page-content', 'children'),
    [Input('url', 'pathname')],
)
def app_select_by_url(pathname):
    if re.search(r'^/+(?:dr\d/+)?$', pathname):
        return [
            html.Div(
                [
                    'Example: ',
                    html.A(f'HZ Her, zg passband, {default_dr.upper()}', href=f'/{default_dr}/view/680113300005170'),
                ]
            ),
            html.Footer(
                [
                    'See source code ',
                    html.A('on GitHub', href='//github.com/snad-space/ztf-viewer'),
                ]
            )
        ]
    if match := re.search(r'^/+view/+(\d+)', pathname):
        return get_viewer_layout(f'/{default_dr}/view/{match.group(1)}')
    if re.search(r'^/+dr\d/+view/+(\d+)', pathname):
        return get_viewer_layout(pathname)
    if search_match := re.search(r"""^
                                     (?:/+(?P<dr>dr\d))?
                                     /+search
                                     /+(?P<coord_or_name>[^/]+)
                                     /+(?P<radius_arcsec>[^/]+)
                                     /*
                                     $""",
                                 pathname,
                                 flags=re.VERBOSE):
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
        dr = search_match.group('dr')
        return get_search_layout(coordinates, radius_arcsec, dr)
    return html.H1('404')


def server():
    """Entrypoint for Gunicorn"""
    return app.server


if __name__ == '__main__':
    app.run_server(debug=True)

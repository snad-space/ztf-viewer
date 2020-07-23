#!/usr/bin/env python3

import logging
import pathlib
import re
import urllib.parse

import dash_core_components as dcc
import dash_html_components as html
from dash.dependencies import Input, Output, State
from dash.exceptions import PreventUpdate

from anomalies import get_layout as get_anomalies_layout
from app import app
from login import get_layout as get_login_layout
from search import get_layout as get_search_layout
from tags import get_layout as get_tags_layout
from util import available_drs, joiner, sky_coord_from_str, YEAR, DEFAULT_DR
from viewer import get_layout as get_viewer_layout


logging.basicConfig(level=logging.INFO)


app.layout = html.Div([
    dcc.Location(id='url', refresh=True),
    html.Div(
        [
            html.H1(
                [
                    html.A(
                        [
                            html.Img(src='/static/img/logo.svg', alt='logo', id='header-logo'),
                            'SNAD ZTF',
                        ],
                        href='/',
                    ),
                    ' ',
                    html.Div('DR4', id='dr-title', style={'display': 'inline-block'}),
                    ' object viewer',
                ],
            ),
            'OID ',
            dcc.Input(
                id='input-oid',
                placeholder='E.g. 680113300005170',
                type='text',
                minLength=15,
                maxLength=16,
                n_submit=0,
            ),
            html.Div(
                DEFAULT_DR,
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
            'Coordinates ',
            dcc.Input(
                id='input-coord-or-name',
                placeholder='00h00m00s +00d00m00s',
                type='text',
                minLength=1,
                maxLength=50,
                n_submit=0,
            ),
            ' radius (arcsec) ',
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
    html.Footer(
        [
            f'© {YEAR} ',
            html.A('SИAD', href='//snad.space'),
            '. Developed by Konstantin Malanchev, based on ',
            html.A('the ZTF Caltech data.', href='//ztf.caltech.edu'),
            ' See the source code ',
            html.A('on GitHub', href='//github.com/snad-space/ztf-viewer'),
        ],
        style={'margin-top': '5em',}
    ),
])


@app.callback(
    Output('data-release', 'children'),
    [Input('url', 'pathname')],
)
def dr_from_url(url):
    try:
        parts = pathlib.Path(url).parts
    except TypeError:
        return DEFAULT_DR
    if len(parts) < 2:
        return DEFAULT_DR
    if parts[1].lower().startswith('dr'):
        return parts[1]
    return DEFAULT_DR


def dr_switch(current_dr, current_url, switch_dr):
    if switch_dr == current_dr:
        return current_dr.upper()
    if current_dr in current_url:
        switch_url = current_url.replace(current_dr, switch_dr)
    else:
        switch_url = f'/{switch_dr}{current_url}'
    return html.A(switch_dr.upper(), href=switch_url, style={'text-decoration-style': 'dashed'})


@app.callback(
    Output('dr-title', 'children'),
    [Input('data-release', 'children')],
)
def set_dr_title(dr):
    return dr.upper()


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
    if not isinstance(pathname, str):
        raise PreventUpdate
    if m := re.search(r'^/+(?:(dr\d)/+)?$', pathname):
        dr = m.group(1) or DEFAULT_DR
        other_drs = [other_dr for other_dr in available_drs if other_dr != dr]
        return [
            html.Div(
                [
                    'For example see the page for ',
                    html.A(f'HZ Her', href=f'/{dr}/view/680113300005170'),
                ]
            ),
            html.H2('Welcome to SNAD ZTF object viewer!'),
            html.Big(
                [
                    'This is a tool developed by the ',
                    html.A('SИAD team', href='//snad.space'),
                    ' in order to enable quick expert investigation of objects within the public ',
                    html.A('Zwicky Transient Facility (ZTF)', href='//ztf.caltech.edu'),
                    ' data releases.',
                    html.Br(), html.Br(),
                    'It was developed as part of the ',
                    html.A('3rd SИAD Workshop', href='//snad.space/2020/'),
                    ', held remotely in July, 2020.',
                    html.Br(), html.Br(),
                    'The viewer allows visualization of raw and folded light curves and metadata, as well as cross-match information with the ',
                    html.A('the General Catalog of Variable Stars', href='http://www.sai.msu.ru/gcvs/intro.htm'),
                    ', ',
                    html.A('the International Variable Stars Index', href='//www.aavso.org/vsx/index.php?view=about.top'),
                    ', ',
                    html.A('the ATLAS Catalog of Variable Stars', href='//archive.stsci.edu/prepds/atlas-var/'),
                    ', ',
                    html.A('the ZTF Catalog of Periodic Variable Stars', href='//zenodo.org/record/3886372'),
                    ', ',
                    html.A('the Transient Name Server', href='//www.wis-tns.org'),
                    ', ',
                    html.A('the Open Astronomy Catalogs', href='//astrocats.space/'),
                    ', ',
                    html.A('the OGLE III Catalog of Variable Stars', href='http://ogledb.astrouw.edu.pl/~ogle/CVS/'),
                    ', ',
                    html.A('the Simbad Astronomical Data Base', href='//simbad.u-strasbg.fr/simbad/'),
                    ', ',
                    html.A('Gaia DR2 distances (Bailer-Jones+, 2018)', href='//vizier.u-strasbg.fr/viz-bin/VizieR?-source=I/347'),
                    ', ',
                    html.A('Vizier', href='//vizier.u-strasbg.fr/viz-bin/VizieR'),
                    '.',
                    html.Br(),
                ],
            ),
            html.Br(),
            html.Div(
                [
                    'The viewer is also available for ',
                ]
                + list(joiner(', ', (
                    html.A(f'ZTF {dr.upper()}', href=f'/{dr}/')
                    for dr in other_drs
                ))),
            ),
        ]
    if match := re.search(r'^/+view/+(\d+)', pathname):
        return get_viewer_layout(f'/{DEFAULT_DR}/view/{match.group(1)}')
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

        coord_or_name = urllib.parse.unquote(search_match['coord_or_name'])
        try:
            coordinates = sky_coord_from_str(coord_or_name)
        except ValueError:
            return html.Div(
                [
                    html.H1('404'),
                    html.P(f'Cannot parse coordinate or find an object name {coord_or_name}'),
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
    if re.search(r'^/+login/*$', pathname):
        return get_login_layout(pathname)
    if re.search('^/+anomalies/*$', pathname):
        return get_anomalies_layout(pathname)
    if re.search('^/+tags/*$', pathname):
        return get_tags_layout(pathname)
    return html.H1('404')


def server():
    """Entrypoint for Gunicorn"""
    return app.server


if __name__ == '__main__':
    app.run_server(debug=True)

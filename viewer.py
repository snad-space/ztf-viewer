import logging
from functools import lru_cache
from urllib.parse import quote as url_quote

import dash_core_components as dcc
import dash_dangerously_set_inner_html as ddsih
import dash_defer_js_import as dji
import dash_html_components as html
import plotly.express as px
from dash.dependencies import Input, Output, State
from dash_table import DataTable

from app import app
from cross import find_simbad
from db import get_light_curve, get_meta
from util import dict_to_bullet, coord_str_to_pair, astropy_table_to_records, html_from_astropy_table


LIGHT_CURVE_TABLE_COLUMNS = ('mjd', 'mag', 'magerr', 'clrcoeff')
SIMBAD_TABLE_COLUMNS = {
    'url': 'MAIN_ID',
    'separation': 'Separation, arcsec',
    'OTYPE': 'Main type',
    'OTYPES': 'Other types',
    'V__vartyp': 'Variable type',
    'V__period': 'Period',
    'Distance_distance': 'Distance',
    'Distance_unit': 'Distance unit'
}
COLORS = {'zr': '#CC3344', 'zg': '#117733'}


def oid_from_pathname(pathname):
    pathname = pathname.rstrip('/')
    oid = pathname.rsplit('/', maxsplit=1)[-1]
    return int(oid)


def get_table(df):
    return df[list(LIGHT_CURVE_TABLE_COLUMNS)].to_dict('records')


def set_div_for_aladin(oid):
    coord = get_meta(oid)['coord']
    ra, dec = coord_str_to_pair(coord)
    style = {'display': 'none'}
    return html.Div(
        [
            html.Div(id='aladin-oid', children=f'{oid}', style=style),
            html.Div(id='aladin-ra', children=f'{ra}', style=style),
            html.Div(id='aladin-dec', children=f'{dec}', style=style),
            html.Div(id='aladin-coord', children=f'{coord}', style=style),
        ],
        id='for-aladin',
    )


@lru_cache(maxsize=128)
def get_layout(pathname):
    oid = oid_from_pathname(pathname)
    df = get_light_curve(oid)
    if df is None:
        return html.H1('404')
    coord = get_meta(oid)['coord']
    layout = html.Div([
        html.Div(f'{oid}', id='oid', style={'display': 'none'}),
        html.H2(id='title'),
        dcc.Graph(
            id='graph',
            style={'width': '75%'},
        ),
        html.Div(
            [
                html.H2('Metadata'),
                dcc.Markdown(id='metadata'),
            ],
            style={'width': '50%'},
        ),
        html.Div(
            [
                html.H2('Simbad'),
                dcc.Input(
                    value='300',
                    id='simbad-radius',
                    placeholder='Search radius, arcsec',
                    type='number',
                ),
                ' search radius, arcsec',
                html.Div(id='simbad-table'),
            ],
        ),
        html.Div(
            [
                html.H2(html.A('Aladin', href=f'//aladin.u-strasbg.fr/AladinLite/?target={coord}')),
                set_div_for_aladin(oid),
                html.Div(
                    id='aladin-lite-div',
                    style={'width': '600px', 'height': '400px', },
                ),
            ],
        ),
        html.Script(src="/static/js/aladin_helper.js"),
        dji.Import(src="/static/js/aladin_helper.js"),
        html.H2(html.A('Download light curve CSV', href=f'/csv/{oid}')),
        html.Div(
            [
                html.H2('Light curve'),
                DataTable(
                    id='light-curve-table',
                    columns=[{'name': column, 'id': column} for column in LIGHT_CURVE_TABLE_COLUMNS],
                    data=get_table(df),
                ),
            ],
            style={'width': '75%'},
        ),
    ])
    return layout


@app.callback(
    Output('title', 'children'),
    [Input('oid', 'children')],
)
def set_title(oid):
    return f'{oid}'


@app.callback(
    Output('metadata', 'children'),
    [Input('oid', 'children')],
)
def get_meta_markdown(oid):
    d = get_meta(oid)
    text = dict_to_bullet(d)
    return text


@app.callback(
    Output('graph', 'figure'),
    [Input('oid', 'children')],
)
def set_figure(oid):
    df = get_light_curve(oid)
    mag_min = (df['mag'] - df['magerr']).min()
    mag_max = (df['mag'] + df['magerr']).max()
    mag_ampl = mag_max - mag_min
    range_y = [mag_max + 0.1 * mag_ampl, mag_min - 0.1*mag_ampl]
    color = COLORS[get_meta(oid)['filter']]
    figure = px.scatter(
        df,
        x='mjd_58000',
        y='mag',
        error_y='magerr',
        range_y=range_y,
        labels={'mjd_58000': 'mjd − 58000'},
        color_discrete_sequence=[color],
    )
    return figure


@app.callback(
    Output('simbad-table', 'children'),
    [Input('simbad-radius', 'value')],
    state=[State('oid', 'children')]
)
def set_simbad_table(radius, oid):
    radius = float(radius)
    coord = get_meta(oid)['coord']
    ra, dec = coord_str_to_pair(coord)
    table = find_simbad(ra, dec, radius)
    if table is None:
        return html.P(f'No Simbad objects within {radius} arcsec from {ra:.5f}, {dec:.5f}')
    table = table.copy()
    table['url'] = [f'<a href="//simbad.u-strasbg.fr/simbad/sim-id?Ident={url_quote(x.decode())}">{x.decode()}</a>' for x in table['MAIN_ID']]
    div = html.Div(
        [
            ddsih.DangerouslySetInnerHTML(html_from_astropy_table(table, SIMBAD_TABLE_COLUMNS)),
        ],
    )
    return div

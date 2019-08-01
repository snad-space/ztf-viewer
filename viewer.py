from functools import lru_cache

import dash_core_components as dcc
import dash_defer_js_import as dji
import dash_html_components as html
import plotly.express as px
from dash_table import DataTable

from db import get_light_curve, get_meta
from util import dict_to_bullet


TABLE_COLUMNS = ('mjd', 'mag', 'magerr', 'clrcoeff')
COLORS = {'zr': '#CC3344', 'zg': '#117733'}


def oid_from_pathname(pathname):
    pathname = pathname.rstrip('/')
    oid = pathname.rsplit('/', maxsplit=1)[-1]
    return int(oid)


def get_title(oid):
    return f'{oid}'


def get_figure(oid, df):
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


def get_table(df):
    return df[list(TABLE_COLUMNS)].to_dict('records')


def get_meta_markdown(oid):
    d = get_meta(oid)
    text = dict_to_bullet(d)
    return dcc.Markdown(text)


def set_div_for_aladin(oid):
    coord = get_meta(oid)['coord']
    ra, dec = coord.split(', ')
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
        html.H2(get_title(oid)),
        dcc.Graph(
            id='graph',
            style={'width': '75%'},
            figure=get_figure(oid, df),
        ),
        html.Div(
            [
                html.H2('Metadata'),
                get_meta_markdown(oid),
            ],
            style={'width': '50%'},
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
                    id='table',
                    columns=[{'name': column, 'id': column} for column in TABLE_COLUMNS],
                    data=get_table(df),
                ),
            ],
            style={'width': '75%'},
        ),
    ])
    return layout

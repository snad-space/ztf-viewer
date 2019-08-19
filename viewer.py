from functools import lru_cache, partial

import dash_core_components as dcc
import dash_dangerously_set_inner_html as ddsih
import dash_defer_js_import as dji
import dash_html_components as html
import pandas as pd
import plotly.express as px
from dash.dependencies import Input, Output, State
from dash_table import DataTable

from app import app
from cross import get_catalog_query, find_vizier, find_ztf_oid, find_ztf_circle
from util import html_from_astropy_table


LIGHT_CURVE_TABLE_COLUMNS = ('mjd', 'mag', 'magerr', 'clrcoeff')


METADATA_FIELDS = ('nobs', 'ngoodobs', 'filter', 'coord_string', 'duration', 'fieldid', 'rcid')


COLORS = {'zr': '#CC3344', 'zg': '#117733'}


LIST_MAXSHOW = 4


def oid_from_pathname(pathname):
    pathname = pathname.rstrip('/')
    oid = pathname.rsplit('/', maxsplit=1)[-1]
    return int(oid)


def set_div_for_aladin(oid):
    ra, dec = find_ztf_oid.get_coord(oid)
    coord = find_ztf_oid.get_coord_string(oid)
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
    if find_ztf_oid.find(oid) is None:
        return html.H1('404')
    coord = find_ztf_oid.get_coord_string(oid)
    layout = html.Div([
        html.Div(f'{oid}', id='oid', style={'display': 'none'}),
        html.H2(id='title'),
        dcc.Graph(
            id='graph',
            style={'width': '75%'},
        ),
        html.Div(
            [
                html.H2('Neighbours'),
                html.Div(
                    [
                        html.H4('Different field, same pathband'),
                        dcc.Input(
                            value='1',
                            id='different_field_radius',
                            placeholder='Search radius, arcsec',
                            type='number',
                            step='0.1',
                            min='0.1',
                            max='60',
                        ),
                        html.Div(id='different_field_neighbours'),
                    ],
                ),
                html.Div(
                    [
                        html.H4('Different pathband, same field'),
                        dcc.Input(
                            value='1',
                            id='different_filter_radius',
                            placeholder='Search radius, arcsec',
                            type='number',
                            step='0.1',
                            min='0.1',
                            max='60',
                        ),
                        html.Div(id='different_filter_neighbours'),
                    ],
                ),
            ],
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
                html.H2('GCVS'),
                dcc.Input(
                    value='10',
                    id='gcvs-radius',
                    placeholder='Search radius, arcsec',
                    type='number',
                ),
                ' search radius, arcsec',
                html.Div(id='gcvs-table'),
            ],
        ),
        html.Div(
            [
                html.H2('AAVSO VSX'),
                dcc.Input(
                    value='10',
                    id='vsx-radius',
                    placeholder='Search radius, arcsec',
                    type='number',
                ),
                ' search radius, arcsec',
                html.Div(id='vsx-table'),
            ],
        ),
        html.Div(
            [
                html.H2('OGLE-III'),
                dcc.Input(
                    value='10',
                    id='ogle-radius',
                    placeholder='Search radius, arcsec',
                    type='number',
                    min='0.1',
                    max='323999'
                ),
                ' search radius, arcsec',
                html.Div(id='ogle-table'),
            ],
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
                html.H2('Vizier'),
                dcc.Input(
                    value='1',
                    id='vizier-radius',
                    placeholder='Search radius, arcsec',
                    type='number',
                    step='0.1',
                ),
                ' search radius, arcsec',
                html.Div(id='vizier-list'),
            ]
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
    meta = find_ztf_oid.get_meta(oid).copy()
    meta['coord_string'] = find_ztf_oid.get_coord_string(oid)
    text = '\n'.join(f'* **{k}**: {meta[k]}' for k in METADATA_FIELDS)
    return text


@app.callback(
    Output('graph', 'figure'),
    [Input('oid', 'children')],
)
def set_figure(oid):
    lc = find_ztf_oid.get_lc(oid).copy()
    color = COLORS[find_ztf_oid.get_meta(oid)['filter']]
    for obs in lc:
        obs['mjd_58000'] = obs['mjd'] - 58000
    mag_min = min(obs['mag'] - obs['magerr'] for obs in lc)
    mag_max = max(obs['mag'] + obs['magerr'] for obs in lc)
    mag_ampl = mag_max - mag_min
    range_y = [mag_max + 0.1 * mag_ampl, mag_min - 0.1*mag_ampl]
    figure = px.scatter(
        pd.DataFrame.from_records(lc),
        x='mjd_58000',
        y='mag',
        error_y='magerr',
        range_y=range_y,
        labels={'mjd_58000': 'mjd − 58000'},
        color_discrete_sequence=[color],
    )
    return figure


def find_neighbours(radius, oid, different):
    if radius is None:
        return html.P('No radius is specified')
    ra, dec = find_ztf_oid.get_coord(oid)
    kwargs = dict(ra=ra, dec=dec, radius_arcsec=radius)
    fltr = find_ztf_oid.get_meta(oid)['filter']
    fieldid = find_ztf_oid.get_meta(oid)['fieldid']
    if different == 'filter':
        kwargs['not_filters'] = (fltr,)
        kwargs['fieldids'] = (fieldid,)
    elif different == 'fieldid':
        kwargs['filters'] = (fltr,)
        kwargs['not_fieldids'] = (fieldid,)
    else:
        raise ValueError(f'Wrong "different" value {different}')
    j = find_ztf_circle.find(**kwargs)
    text = dcc.Markdown(', '.join(f'[{oid}](./{oid})' for oid in j))
    return text


app.callback(
    Output('different_field_neighbours', 'children'),
    [Input('different_field_radius', 'value')],
    state=[State('oid', 'children')]
)(partial(find_neighbours, different='fieldid'))


app.callback(
    Output('different_filter_neighbours', 'children'),
    [Input('different_filter_radius', 'value')],
    state=[State('oid', 'children')]
)(partial(find_neighbours, different='filter'))


def set_table(radius, oid, catalog):
    ra, dec = find_ztf_oid.get_coord(oid)
    if radius is None:
        return html.P('No radius is specified')
    radius = float(radius)
    query = get_catalog_query(catalog)
    table = query.find(ra, dec, radius)
    if table is None:
        return html.P(f'No {catalog} objects within {radius} arcsec from {ra:.5f}, {dec:.5f}')
    table = table.copy()
    div = html.Div(
        [
            ddsih.DangerouslySetInnerHTML(html_from_astropy_table(table, query.columns)),
        ],
    )
    return div


app.callback(
    Output('gcvs-table', 'children'),
    [Input('gcvs-radius', 'value')],
    state=[State('oid', 'children')]
)(partial(set_table, catalog='GCVS'))


app.callback(
    Output('vsx-table', 'children'),
    [Input('vsx-radius', 'value')],
    state=[State('oid', 'children')]
)(partial(set_table, catalog='VSX'))


app.callback(
    Output('ogle-table', 'children'),
    [Input('ogle-radius', 'value')],
    state=[State('oid', 'children')]
)(partial(set_table, catalog='OGLE'))


app.callback(
    Output('simbad-table', 'children'),
    [Input('simbad-radius', 'value')],
    state=[State('oid', 'children')]
)(partial(set_table, catalog='Simbad'))


@app.callback(
    Output('vizier-list', 'children'),
    [Input('vizier-radius', 'value')],
    state=[State('oid', 'children')]
)
def set_vizier_list(radius, oid):
    ra, dec = find_ztf_oid.get_coord(oid)
    if radius is None:
        return html.P('No radius is specified')
    radius = float(radius)
    table_list = find_vizier.find(ra, dec, radius)
    if len(table_list) == 0:
        return html.P(f'No vizier catalogs found within {radius} arcsec from {ra:.5f}, {dec:.5f}')
    records = []
    lengths = []
    for catalog, table in zip(table_list.keys(), table_list.values()):
        n = len(table)
        n_objects = str(n) if n < find_vizier.row_limit else f'≥{n}'
        n_objects = f' ({n_objects} objects)' if n > LIST_MAXSHOW else ''
        r = table['_r']
        if n > LIST_MAXSHOW:
            r = r[:LIST_MAXSHOW - 1]
        sep = ', '.join(f'{x}″' for x in r)
        if n > LIST_MAXSHOW:
            sep += ', …'
        url = find_vizier.get_catalog_url(catalog, ra, dec, radius)
        records.append(f'[{catalog}]({url}){n_objects}: {sep}')
        lengths.append(len(catalog) + len(n_objects) + 2 + len(sep))
    ul_column_width = max(lengths)
    div = html.Div(
        [
            html.Br(),
            html.P(html.A(f'See all {len(table_list)} catalogs on Vizier',
                          href=find_vizier.get_search_url(ra, dec, radius))),
            html.Ul([html.Li(dcc.Markdown(record)) for record in records],
                    style={'columns': f'{ul_column_width}ch'}),
        ]
    )
    return div


@app.callback(
    Output('light-curve-table', 'data'),
    [Input('oid', 'children')]
)
def set_lc_table(oid):
    return find_ztf_oid.get_lc(oid).copy()

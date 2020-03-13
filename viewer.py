from functools import lru_cache, partial
import pathlib

import dash_core_components as dcc
import dash_dangerously_set_inner_html as ddsih
import dash_defer_js_import as dji
import dash_html_components as html
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash.dependencies import Input, Output, State
from dash_table import DataTable

from app import app
from cross import get_catalog_query, find_vizier, find_ztf_oid, find_ztf_circle, vizier_catalog_details, light_curve_features
from util import html_from_astropy_table, to_str, get_db_api_version_from_dr, get_dr_from_db_api_version

LIGHT_CURVE_TABLE_COLUMNS = ('mjd', 'mag', 'magerr', 'clrcoeff')

METADATA_FIELDS = ('nobs', 'ngoodobs', 'filter', 'coord_string', 'duration', 'fieldid', 'rcid')

COLORS = {'zr': '#CC3344', 'zg': '#117733'}
MARKER_SIZE = 10

LIST_MAXSHOW = 4


def version_oid_from_pathname(pathname):
    path = pathlib.Path(pathname)
    *_, dr, _, oid = path.parts
    version = get_db_api_version_from_dr(dr)
    return version, int(oid)


def set_div_for_aladin(oid, version):
    ra, dec = find_ztf_oid.get_coord(oid, version)
    coord = find_ztf_oid.get_coord_string(oid, version)
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
    version, oid = version_oid_from_pathname(pathname)
    dr = get_dr_from_db_api_version(version)
    if find_ztf_oid.find(oid, version) is None:
        return html.H1('404')
    ra, dec = find_ztf_oid.get_coord(oid, version)
    coord = find_ztf_oid.get_coord_string(oid, version)
    layout = html.Div([
        html.Div(f'{oid}', id='oid', style={'display': 'none'}),
        html.Div(f'{version}', id='api-version', style={'display': 'none'}),
        html.H2(id='title'),
        dcc.Graph(
            id='graph',
            style={'width': '90%'},
        ),
        html.Div(
            [
                html.H2('Neighbours'),
                html.Div(
                    [
                        html.H4('Different passband, same field'),
                        dcc.Input(
                            value='1',
                            id='different_filter_radius',
                            placeholder='Search radius, arcsec',
                            type='number',
                            step='0.1',
                            min='0',
                            max='60',
                        ),
                        ' search radius, arcsec',
                        html.Div(id='different_filter_neighbours'),
                    ],
                ),
                html.Div(
                    [
                        html.H4('Different field'),
                        dcc.Input(
                            value='1',
                            id='different_field_radius',
                            placeholder='Search radius, arcsec',
                            type='number',
                            step='0.1',
                            min='0',
                            max='60',
                        ),
                        ' search radius, arcsec',
                        html.Div(id='different_field_neighbours'),
                    ],
                ),
            ],
        ),
        html.Div(
            [
                html.H2('Metadata'),
                html.Div(id='metadata'),
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
                ' search radius, arcsec ',
                html.Button(
                    'Show',
                    id='vizier-button',
                    n_clicks=0,
                ),
                html.Br(),
                html.Big(html.A(
                    'See all results on Vizier website',
                    id='search-on-vizier',
                    href=find_vizier.get_search_url(ra, dec, 0))
                ),
                html.Div(id='vizier-list'),
            ]
        ),
        html.Div(
            [
                html.H2(html.A('Aladin', href=f'//aladin.u-strasbg.fr/AladinLite/?target={coord}')),
                set_div_for_aladin(oid, version),
                html.Div(
                    id='aladin-lite-div',
                    style={'width': '600px', 'height': '400px', },
                ),
            ],
        ),
        html.Script(src="/static/js/aladin_helper.js"),
        dji.Import(src="/static/js/aladin_helper.js"),
        html.Div(
            [
                html.H2('Features'),
                html.Div(id='features-list'),
            ]
        ),
        html.H2(
            [
                'Download light curve: ',
                html.A('CSV', href=f'/{dr}/csv/{oid}'),
                ', ',
                html.A('JSON', href=find_ztf_oid.json_url(oid, version)),
            ]
        ),
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
    [
        Input('oid', 'children'),
        Input('api-version', 'children')
    ],
)
def get_metadata(oid, version):
    meta = find_ztf_oid.get_meta(oid, version).copy()
    meta['coord_string'] = find_ztf_oid.get_coord_string(oid, version)
    items = [f'**{k}**: {to_str(meta[k])}' for k in METADATA_FIELDS]
    column_width = max(map(len, items)) - 2
    div = html.Div(
        html.Ul([html.Li(dcc.Markdown(text)) for text in items], style={'list-style-type': 'none'}),
        style={'columns': f'{column_width}ch'},
    )
    return div


@app.callback(
    Output('graph', 'figure'),
    [
        Input('oid', 'children'),
        Input('api-version', 'children'),
        Input('different_filter_neighbours', 'children'),
        Input('different_field_neighbours', 'children'),
    ],
)
def set_figure(cur_oid, version, different_filter, different_field):
    if not isinstance(different_filter, list):
        different_filter = []
    if not isinstance(different_field, list):
        different_field = []
    dif_oid = [div['props']['id'].rsplit('-', maxsplit=1)[-1]
               for div in different_filter + different_field if isinstance(div, dict)]
    oids = [cur_oid] + dif_oid
    lcs = []
    for oid in oids:
        if oid == cur_oid:
            size = 3
        else:
            size = 1
        lc = find_ztf_oid.get_lc(oid, version).copy()
        lcs.extend(lc)
        fltr = find_ztf_oid.get_meta(oid, version)['filter']
        for obs in lc:
            obs['mjd_58000'] = obs['mjd'] - 58000
            obs['oid'] = oid
            obs['filter'] = fltr
            obs['mark_size'] = size
    mag_min = min(obs['mag'] - obs['magerr'] for obs in lcs)
    mag_max = max(obs['mag'] + obs['magerr'] for obs in lcs)
    mag_ampl = mag_max - mag_min
    range_y = [mag_max + 0.1 * mag_ampl, mag_min - 0.1 * mag_ampl]
    figure = px.scatter(
        pd.DataFrame.from_records(lcs),
        x='mjd_58000',
        y='mag',
        error_y='magerr',
        color='filter',
        range_y=range_y,
        labels={'mjd_58000': 'mjd − 58000'},
        color_discrete_map=COLORS,
        symbol='oid',
        size='mark_size',
        size_max=MARKER_SIZE,
    )
    fw = go.FigureWidget(figure)
    #fw.layout.hovermode = 'closest'
    #logging.warning(f'{fw.data}')
    #for scatter in fw.data:
    #    scatter.on_click(lambda *args, **kwargs: logging.warning('#'*80 + f'\n{args}\n{kwargs}'))
    return fw


def find_neighbours(radius, center_oid, version, different):
    if radius is None:
        return html.P('No radius is specified')
    if float(radius) <= 0:
        return html.P('Radius should be positive')
    ra, dec = find_ztf_oid.get_coord(center_oid, version)
    kwargs = dict(ra=ra, dec=dec, radius_arcsec=radius, version=version)
    fltr = find_ztf_oid.get_meta(center_oid, version)['filter']
    fieldid = find_ztf_oid.get_meta(center_oid, version)['fieldid']
    j = find_ztf_circle.find(**kwargs)
    if different == 'filter':
        j = {oid: value for oid, value in j.items()
             if value['meta']['filter'] != fltr and value['meta']['fieldid'] == fieldid}
    elif different == 'fieldid':
        j = {oid: value for oid, value in j.items() if value['meta']['fieldid'] != fieldid}
    else:
        raise ValueError(f'Wrong "different" value {different}')
    children = []
    for i, (oid, obj) in enumerate(sorted(j.items(), key=lambda kv: kv[1]['separation'])):
        div = html.Div(
            [
                html.A(f'{oid}', href=f'./{oid}'),
                f' ({obj["separation"]:.3f}″)'
            ],
            id=f'different-{different}-{oid}',
            style={'display': 'inline'},
        )
        if i != 0:
            div.children.insert(0, ', ')
        children.append(div)
    return children


app.callback(
    Output('different_field_neighbours', 'children'),
    [Input('different_field_radius', 'value')],
    state=[
        State('oid', 'children'),
        State('api-version', 'children'),
    ]
)(partial(find_neighbours, different='fieldid'))

app.callback(
    Output('different_filter_neighbours', 'children'),
    [Input('different_filter_radius', 'value')],
    state=[
        State('oid', 'children'),
        State('api-version', 'children'),
    ]
)(partial(find_neighbours, different='filter'))


def set_table(radius, oid, version, catalog):
    ra, dec = find_ztf_oid.get_coord(oid, version)
    if radius is None:
        return html.P('No radius is specified')
    radius = float(radius)
    if radius <= 0:
        return html.P('Radius should be positive')
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
    state=[
        State('oid', 'children'),
        State('api-version', 'children'),
    ]
)(partial(set_table, catalog='GCVS'))

app.callback(
    Output('vsx-table', 'children'),
    [Input('vsx-radius', 'value')],
    state=[
        State('oid', 'children'),
        State('api-version', 'children'),
    ]
)(partial(set_table, catalog='VSX'))

app.callback(
    Output('ogle-table', 'children'),
    [Input('ogle-radius', 'value')],
    state=[
        State('oid', 'children'),
        State('api-version', 'children'),
    ]
)(partial(set_table, catalog='OGLE'))

app.callback(
    Output('simbad-table', 'children'),
    [Input('simbad-radius', 'value')],
    state=[
        State('oid', 'children'),
        State('api-version', 'children'),
    ]
)(partial(set_table, catalog='Simbad'))


@app.callback(
    Output('search-on-vizier', 'href'),
    [Input('vizier-radius', 'value')],
    state=[
        State('oid', 'children'),
        State('api-version', 'children'),
    ],
)
def set_vizier_url(radius, oid, version):
    ra, dec = find_ztf_oid.get_coord(oid, version)
    if radius is None:
        radius = 0
    return find_vizier.get_search_url(ra, dec, radius)


@app.callback(
    Output('vizier-list', 'children'),
    [Input('vizier-button', 'n_clicks')],
    state=[
        State('vizier-radius', 'value'),
        State('oid', 'children'),
        State('api-version', 'children'),
    ],
)
def set_vizier_list(n_clicks, radius, oid, version):
    if n_clicks == 0:
        return ''

    if radius is None:
        return html.P('No radius is specified')

    radius = float(radius)
    ra, dec = find_ztf_oid.get_coord(oid, version)

    table_list = find_vizier.find(ra, dec, radius)
    if len(table_list) == 0:
        return html.P(f'No vizier catalogs found within {radius} arcsec from {ra:.5f}, {dec:.5f}')

    records = []
    lengths = []
    for catalog, table in zip(table_list.keys(), table_list.values()):
        description = vizier_catalog_details.description(catalog) or catalog
        n = len(table)
        n_objects = str(n) if n < find_vizier.row_limit else f'≥{n}'
        n_objects = f' ({n_objects} objects)' if n > LIST_MAXSHOW else ''
        r = sorted(table['_r'])
        if n > LIST_MAXSHOW:
            r = r[:LIST_MAXSHOW - 1]
        sep = ', '.join(f'{x}″' for x in r)
        if n > LIST_MAXSHOW:
            sep += ', …'
        url = find_vizier.get_catalog_url(catalog, ra, dec, radius)
        records.append(f'[{description}]({url}){n_objects}: {sep}')
        lengths.append(len(description) + len(n_objects) + 2 + len(sep))

    ul_column_width = max(lengths) + 2  # for bullet symbol
    div = html.Div(
        [
            html.Ul([html.Li(dcc.Markdown(record)) for record in records],
                    style={'columns': f'{ul_column_width}ch', 'list-style-type': 'none'}),
        ]
    )
    return div


@app.callback(
    Output('features-list', 'children'),
    [
        Input('oid', 'children'),
        Input('api-version', 'children'),
    ]
)
def set_features_list(oid, version):
    features = light_curve_features(oid, version)
    if features is None:
        return 'Not available'
    items = [f'**{k}**: {v:.4g}' for k, v in sorted(features.items(), key=lambda item: item[0])]
    column_width = max(map(len, items)) - 2
    div = html.Div(
        html.Ul([html.Li(dcc.Markdown(text)) for text in items], style={'list-style-type': 'none'}),
        style={'columns': f'{column_width}ch'},
    )
    return div


@app.callback(
    Output('light-curve-table', 'data'),
    [
        Input('oid', 'children'),
        Input('api-version', 'children'),
    ]
)
def set_lc_table(oid, version):
    return find_ztf_oid.get_lc(oid, version).copy()

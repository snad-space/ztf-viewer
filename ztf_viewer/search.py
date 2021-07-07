from functools import lru_cache

import dash_html_components as html
import dash_dangerously_set_inner_html as ddsih
from astropy.table import Table

from ztf_viewer.cross import find_ztf_circle
from ztf_viewer.util import html_from_astropy_table, NotFound


COLUMNS = {
    'oid': 'OID',
    'separation': 'separation, arcsec',
    'filter': 'filter',
    'ngoodobs': 'Number of "good" observations',
    'duration': 'Duration, days',
}


def get_layout(coordinates, radius_arcsec, dr):
    ra = coordinates.ra.to_value('deg')
    dec = coordinates.dec.to_value('deg')
    cone_str = f'({ra:.5f} deg, {dec:.5f} deg), r = {radius_arcsec:.1f}″'
    try:
        j = find_ztf_circle.find(ra, dec, radius_arcsec, dr)
    except NotFound:
        return html.Div([
            html.H1('404'),
            f'Nothing inside cone {cone_str}',
        ])
    table = Table([dict(oid=f'<a href="/{dr}/view/{oid}">{oid}</a>', separation=obj['separation'], **obj['meta'])
                   for oid, obj in sorted(j.items(), key=lambda x: x[1]['separation'])])
    layout = html.Div(
        [
            html.H1(f'Objects inside cone {cone_str}'),
            ddsih.DangerouslySetInnerHTML(html_from_astropy_table(table, COLUMNS)),
        ],
    )
    return layout

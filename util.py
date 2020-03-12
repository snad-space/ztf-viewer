import math
import re
from typing import Optional

import astropy.table
import numpy as np
from astropy import units
from jinja2 import Template


default_db_ztf_api_version = 'v1'


def get_db_api_version_from_dr(dr: Optional[str]) -> str:
    if dr is None:
        return default_db_ztf_api_version
    if dr.lower() == 'dr1':
        return 'v1'
    if dr.lower() == 'dr2':
        return 'v2'
    raise ValueError(f'dr {dr} is unsupported')


def get_dr_from_db_api_version(version: str) -> str:
    if version == 'v1':
        return 'dr1'
    if version == 'v2':
        return 'dr2'
    raise ValueError(f'version {version} is unsupported')


default_dr = get_dr_from_db_api_version(default_db_ztf_api_version)


def db_coord_to_degrees(coord):
    match = re.search(r'^\((\S+)\s*,\s*(\S+)\)$', coord)
    ra = math.degrees(float(match.group(1)))
    dec = math.degrees(float(match.group(2)))
    return ra, dec


def hms_to_deg(hms: str):
    h, m, s = (float(x) for x in hms.split())
    angle = h * units.hourangle + m * units.arcmin + s * units.arcsec
    deg = angle.to_value(units.deg)
    return deg


def html_from_astropy_table(table: astropy.table.Table, columns: dict):
    template = Template('''
        <table id="simbad-table">
        <tr>
        {% for column in columns %}
            <td>{{columns[column]}}</td>
        {% endfor %}
        </tr>
        {% for row in table %}
            <tr>
            {% for cell in row %}
                <td>{{cell}}</td>
            {% endfor %}
            </tr>
        {% endfor %}
        </table>
    ''')
    table = table[list(columns.keys())].copy()
    for column in table.colnames:
        table[column] = [to_str(x) for x in table[column]]
    html = template.render(table=table, columns=columns)
    return html


def to_str(s):
    if isinstance(s, bytes):
        return s.decode()
    if isinstance(s, str):
        return s
    if isinstance(s, np.integer) or isinstance(s, int):
        return str(s)
    if isinstance(s, np.floating) or isinstance(s, float):
        if np.isnan(s):
            return ''
        return f'{s:.3f}'
    if np.ma.is_masked(s):
        return ''
    raise ValueError(f'Argument should be str, bytes or int, not {type(s)}')


def anchor_form(url, data, title):
    inputs = '\n'.join(f'<input type="hidden" name="{key}" value="{value}">' for key, value in data.items())
    return f'''
        <form method="post" action="{url}" class="inline">
            {inputs}
            <button type="submit" class="link-button">
                {title}
            </button>
        </form>
    '''

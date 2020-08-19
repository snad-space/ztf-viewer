import logging
import math
import re
from functools import wraps

import astropy.table
import datetime
import numpy as np
from astropy import units
from astropy.time import Time
from jinja2 import Template


INF = float('inf')

FILTER_COLORS = {'zr': '#CC3344', 'zg': '#117733', 'zi': '#1c1309'}


default_dr = 'dr3'


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
    if isinstance(s, units.Quantity):
        if s.unit.is_equivalent('cm'):
            for unit in (units.pc, units.kpc, units.Mpc, units.Gpc):
                if 1e-1 < (distance := s.to(unit)).value < 3e3:
                    return f'{distance:.2f}'
            else:
                logging.warning(f'Value {s} is too large or too small')
                return str(s)
    if np.ma.is_masked(s):
        return ''
    raise ValueError(f'Argument should be str, bytes, int, float or unit.Quantity (distance), not {type(s)}')


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


def min_max_mjd_short(dr):
    if dr == 'dr2':
        return 58194.0, 58299.0
    if dr == 'dr3':
        return 58194.0, 58483.0
    return -INF, INF


def mjd_to_datetime(mjd):
    t = Time(mjd, format='mjd')
    dt = t.to_datetime(datetime.timezone.utc)
    return dt


def raise_if(condition, exception):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if condition:
                raise exception
            return f(*args, **kwargs)
        return wrapper
    return decorator


class NotFound(RuntimeError):
    pass


class CatalogUnavailable(RuntimeError):
    pass


def joiner(value, iterator):
    iterator = iter(iterator)
    yield next(iterator)
    for item in iterator:
        yield value
        yield item

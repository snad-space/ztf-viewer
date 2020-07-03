import math
import os
import re
from dataclasses import dataclass
from urllib.parse import urljoin

import astropy.table
import numpy as np
import requests
from astropy import units
from astropy.coordinates import SkyCoord, EarthLocation
from astropy.time import Time
from jinja2 import Template


PALOMAR = EarthLocation.of_site('palomar')


default_dr = 'dr2'


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


@dataclass
class DateWithFrac:
    year: int
    month: int
    day: int
    fraction: float

    @classmethod
    def from_mjd(cls, mjd, coord=None, location=PALOMAR):
        t = Time(mjd, format='mjd', location=location)
        if coord is not None:
            t = t - t.light_travel_time(SkyCoord(**coord, unit=units.deg))
        dt = t.to_datetime()
        return cls(
            year=dt.year,
            month=dt.month,
            day=dt.day,
            fraction=t.mjd % 1,
        )

    @property
    def monthday(self):
        return f'{self.month:02d}{self.day:02d}'

    def frac_digits(self, digits):
        rou = round(self.fraction, digits)
        return int(rou * 10**digits)

    @property
    def products_root(self):
        return f'/products/sci/{self.year}/{self.monthday}/'

    @property
    def products_path(self):
        return f'{self.products_root}{self.frac_digits(6)}/'

    def sciimg_path(self, *, fieldid, filter, rcid):
        ccdid = rcid // 4 + 1
        qid = rcid % 4 + 1
        filename = f'ztf_{self.year}{self.monthday}{self.frac_digits(6)}_{fieldid:06d}_{filter}_c{ccdid:02d}_o_q{qid}_sciimg.fits'
        return os.path.join(self.products_path, filename)


def correct_date(date_with_frac):
    url = urljoin('http://proxy', date_with_frac.products_root)
    body = requests.get(url).text
    fracs = re.findall(r'<a href="(\d{6})/">\1/</a>', body)
    fracs = sorted(int(f) for f in fracs)
    i = np.searchsorted(fracs, date_with_frac.frac_digits(6))
    print(date_with_frac.fraction)
    date_with_frac.fraction = fracs[i - 1] / 1e6
    print(date_with_frac.fraction)

import os
import re
from dataclasses import dataclass
from urllib.parse import urljoin

import numpy as np
import requests
from astropy import units
from astropy.coordinates import SkyCoord, EarthLocation
from astropy.time import Time

from cache import cache
from config import PRODUCTS_URL


PALOMAR = EarthLocation(lon=-116.863, lat=33.356, height=1706)  # EarthLocation.of_site('Palomar')


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
        return f'{self.products_root}{self.frac_digits(6):06d}/'

    def sciimg_path(self, *, fieldid, filter, rcid):
        ccdid = rcid // 4 + 1
        qid = rcid % 4 + 1
        filename = f'ztf_{self.year}{self.monthday}{self.frac_digits(6):06d}_{fieldid:06d}_{filter}_c{ccdid:02d}_o_q{qid}_sciimg.fits'
        return os.path.join(self.products_path, filename)


@cache()
def _fracs(products_root):
    url = urljoin(PRODUCTS_URL, products_root)
    body = requests.get(url).text
    fracs = re.findall(r'<a href="(\d{6})/">\1/</a>', body)
    return sorted(int(f) for f in fracs)


def correct_date(date_with_frac):
    fracs = _fracs(date_with_frac.products_root)
    i = np.searchsorted(fracs, date_with_frac.frac_digits(6))
    date_with_frac.fraction = fracs[i - 1] / 1e6

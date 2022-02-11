import email.utils
import importlib.resources
from datetime import datetime, timedelta
from io import BytesIO

import numpy as np
import requests
from astropy.coordinates import Angle, SkyCoord
from astropy.io import ascii

from ztf_viewer.catalogs.snad import data
from ztf_viewer.exceptions import NotFound


class _SnadCatalog:
    url = 'https://snad.space/catalog/snad_catalog.csv'

    def __init__(self, interval_seconds=600):
        self.check_interval = timedelta(seconds=interval_seconds)

        with importlib.resources.open_binary(data, 'snad_catalog.csv') as fh:
            self.table = self._create_table(fh)

        self.updated_at = datetime(1900, 1, 1, 1, 1)

    @staticmethod
    def _create_table(src):
        table = ascii.read(src, format='csv')
        table['coord'] = SkyCoord(ra=table['R.A.'], dec=table['Dec.'], unit='deg')
        table.add_index('Name')
        return table

    @staticmethod
    def _last_modified(resp):
        s = resp.headers['last-modified']
        parsed = email.utils.parsedate(s)
        dt = datetime(*parsed[:7])
        return dt

    def _update(self):
        now = datetime.now()
        if now - self.updated_at < self.check_interval:
            return
        try:
            with requests.get(self.url, stream=True) as resp:
                if resp.status_code != 200:
                    return
                if self.updated_at > self._last_modified(resp):
                    return
                self.updated_at = now
                bio = BytesIO(resp.content)
        except requests.exceptions.ConnectionError:
            return
        self.table = self._create_table(bio)

    def __call__(self):
        self._update()
        return self.table.copy()

    def search_region(self, ra, dec, radius_arcsec):
        coord = SkyCoord(ra=ra, dec=dec, unit='deg')
        radius = Angle(radius_arcsec, unit='arcsec')
        idx, sep, _ = coord.match_to_catalog_sky(self.table['coord'])
        if sep > radius:
            raise NotFound
        return self.table['Name'][idx]


snad_catalog = _SnadCatalog()


class SnadCatalogSource:
    def __init__(self, name):
        if isinstance(name, int) or not name.upper().startswith('SNAD'):
            name = f'SNAD{name}'
        name = name.upper()
        catalog = snad_catalog()
        self.row = catalog.loc[name]

    @property
    def coord(self):
        return self.row['coord']

    @property
    def ztf_oid(self):
        return int(self.row['OID'])

import email.utils
import importlib.resources
from datetime import datetime, timedelta
from io import BytesIO

import pandas as pd
import requests
from astropy.coordinates import SkyCoord

from ztf_viewer.catalogs.snad import data


class _SnadCatalog:
    url = 'https://snad.space/catalog/snad_catalog.csv'

    def __init__(self, interval_seconds=600):
        with importlib.resources.open_binary(data, 'snad_catalog.csv') as fh:
            self.df = pd.read_csv(fh, index_col='Name')
        self.updated_at = datetime(1900, 1, 1, 1, 1)
        self.check_interval = timedelta(seconds=interval_seconds)

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
        self.df = pd.read_csv(bio, index_col='Name')

    def __call__(self):
        self._update()
        return self.df.copy(deep=True)


get_snad_catalog = _SnadCatalog()


class SnadCatalogSource:
    def __init__(self, name):
        if isinstance(name, int) or not name.upper().startswith('SNAD'):
            name = f'SNAD{name}'
        name = name.upper()
        catalog = get_snad_catalog()
        self.row = catalog.loc[name]

    @property
    def coord(self):
        return SkyCoord(ra=self.row['R.A.'], dec=self.row['Dec.'], unit='deg')

    @property
    def ztf_oid(self):
        return int(self.row['OID'])

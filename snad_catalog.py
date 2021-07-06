import email.utils
from datetime import datetime, timedelta
from io import BytesIO

import pandas as pd
import requests
from astropy.coordinates import SkyCoord


class _SnadCatalog:
    url = 'https://snad.space/catalog/snad_catalog.csv'

    def __init__(self, interval_seconds=600):
        self.df = None
        self.updated_at = datetime(1900, 1, 1, 1, 1)
        self.check_interval = timedelta(seconds=interval_seconds)

    def _get(self):
        resp = requests.get(self.url, stream=True)
        resp.raise_for_status()
        return resp

    @staticmethod
    def _last_modified(resp):
        s = resp.headers['last-modified']
        parsed = email.utils.parsedate(s)
        dt = datetime(*parsed[:7])
        return dt

    def _update(self):
        now = datetime.now()
        if self.df is not None and now - self.updated_at < self.check_interval:
            return
        with self._get() as resp:
            if self.updated_at > self._last_modified(resp):
                return
            self.updated_at = now
            bio = BytesIO(resp.content)
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

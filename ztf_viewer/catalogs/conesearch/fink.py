from urllib.parse import urljoin

import pandas as pd
from astropy.table import Table

from ztf_viewer.catalogs.conesearch._base import _BaseCatalogApiQuery


class FinkQuery(_BaseCatalogApiQuery):
    id_column = 'i:objectId'
    type_column = 'v:classification'
    _table_ra = 'i:ra'
    _ra_unit = 'deg'
    _table_dec = 'i:dec'
    columns = {
        '__link': 'Name',
        'separation': 'Separation, arcsec',
        'v:classification': 'Class',
    }

    _base_url = 'https://fink-portal.org/'
    _api_url = urljoin(_base_url, '/api/v1/explorer')

    def _api_query_region(self, ra, dec, radius_arcsec):
        params = {'ra': ra, 'dec': dec, 'radius': radius_arcsec}
        response = self._api_session.get(self._api_url, params=params)
        self._raise_if_not_ok(response)
        table = Table.from_pandas(pd.read_json(response.content))
        return table

    def get_url(self, id, row=None):
        return urljoin(self._base_url, id)

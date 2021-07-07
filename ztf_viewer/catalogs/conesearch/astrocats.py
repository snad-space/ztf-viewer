import urllib.parse
from io import BytesIO

import astropy.io.ascii

from ztf_viewer.catalogs.conesearch._base import _BaseCatalogApiQuery


class AstrocatsQuery(_BaseCatalogApiQuery):
    id_column = 'event'
    type_column = 'claimedtype'
    redshift_column = 'redshift'
    _table_ra = 'ra'
    _ra_unit = 'hour'
    _table_dec = 'dec'
    columns = {
        '__link': 'Event name',
        'separation': 'Separation, arcsec',
        'claimedtype': 'Claimed type',
        'stellarclass': 'Stellar class',
        'spectraltype': 'Spectral type',
        'redshift': 'Redshift',
        'host': 'Host',
        'references': 'References',
    }
    _base_api_url = 'https://api.astrocats.space/all'
    _base_astrocats_urls = {
        'SNE': 'https://sne.space/sne/',
        'TDE': 'https://tde.space/tde/',
        'KNE': 'https://kilonova.space/kne/',
        'HVS': 'https://faststars.space/hvs/',
    }

    def _api_query_region(self, ra, dec, radius_arcsec):
        query = {'ra': ra, 'dec': dec, 'radius': radius_arcsec, 'format': 'csv', 'item': 0}
        response = self._api_session.get(self._get_api_url(query))
        self._raise_if_not_ok(response)
        table = astropy.io.ascii.read(BytesIO(response.content), format='csv', guess=False)
        table['references'] = [', '.join(f'<a href=//adsabs.harvard.edu/abs/{r}>{r}</a>'
                                         for r in row['references'].split(','))
                               for row in table]
        return table

    def get_link(self, id, name):
        urls = {}
        for cat, base_url in self._base_astrocats_urls.items():
            url = urllib.parse.urljoin(base_url, urllib.parse.quote(id))
            urls[cat] = url
        link_list = ', '.join(f'<a href="{url}">{cat}</a>' for cat, url in urls.items())
        return f'{name}<br>{link_list}'

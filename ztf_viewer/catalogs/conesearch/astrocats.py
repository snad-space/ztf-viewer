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
    __root_api_url = 'https://api.astrocats.space'
    _base_api_url = f'{__root_api_url}/all'

    def _get_sources(self, id):
        response = self._api_session.get(f'{self.__root_api_url}/{id}/sources')
        self._raise_if_not_ok(response)
        data = response.json()
        return data[id]['sources']

    @staticmethod
    def _format_source(source):
        if 'url' in source and 'bibcode' in source:
            return f'<a href={source["url"]}>{source["name"]}</a> (<a href=//adsabs.harvard.edu/abs/{source["bibcode"]}>{source["bibcode"]}</a>)'
        if 'url' in source:
            return f'<a href={source["url"]}>{source["name"]}</a>'
        if 'bibcode' in source:
            if source['bibcode'] == source['name']:
                return f'<a href=//adsabs.harvard.edu/abs/{source["bibcode"]}>{source["bibcode"]}</a>'
            return f'{source["name"]} (<a href=//adsabs.harvard.edu/abs/{source["bibcode"]}>{source["bibcode"]}</a>)'
        return source["name"]

    def _api_query_region(self, ra, dec, radius_arcsec):
        query = {'ra': ra, 'dec': dec, 'radius': radius_arcsec, 'format': 'csv', 'item': 0}
        response = self._api_session.get(self._get_api_url(query))
        self._raise_if_not_ok(response)
        table = astropy.io.ascii.read(BytesIO(response.content), format='csv', guess=False)
        table['references'] = [', '.join(map(self._format_source, sources))
                               for sources in map(self._get_sources, table['event'])]
        return table

    def get_link(self, id, name, row=None):
        return name

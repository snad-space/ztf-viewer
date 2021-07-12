import json
import logging
import urllib.parse

import pandas as pd
from astropy.table import Table

from ztf_viewer.catalogs.conesearch._base import _BaseCatalogApiQuery
from ztf_viewer.config import TNS_API_KEY, TNS_API_URL, TNS_BOT_ID, TNS_BOT_NAME
from ztf_viewer.exceptions import CatalogUnavailable


class TnsQuery(_BaseCatalogApiQuery):
    id_column = 'objname'
    type_column = 'object_type'
    _name_column = 'fullname'
    _table_ra = 'radeg'
    _ra_unit = 'deg'
    _table_dec = 'decdeg'
    columns = {
        '__link': 'Name',
        'separation': 'Separation, arcsec',
        'discoverydate': 'Discovery date',
        'discoverymag': 'Discovery mag',
        'object_type': 'Type',
        'redshift': 'Redshift',
        'hostname': 'Host',
        'host_redshift': 'Host redshift',
        'internal_names': 'Internal names',
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # https://www.wis-tns.org/content/tns-newsfeed#comment-wrapper-23710
        self._api_session.headers['User-Agent'] = f'tns_marker{{"tns_id":{TNS_BOT_ID}, "type": "bot", "name":"{TNS_BOT_NAME}"}}'
        self._search_api_url = urllib.parse.urljoin(TNS_API_URL, '/api/get/search')
        self._object_api_url = urllib.parse.urljoin(TNS_API_URL, '/api/get/object')

    @staticmethod
    def _prepare_request_data(data=None):
        if TNS_API_KEY is None:
            raise CatalogUnavailable('TNS_API_KEY is not specified')
        prep = dict(api_key=(None, TNS_API_KEY))
        if data is not None:
            prep['data'] = (None, json.dumps(data))
        return prep

    def _reply(self, response):
        self._raise_if_not_ok(response)
        j = response.json()
        if j['id_code'] != 200:
            logging.warning(j['id_message'])
            raise CatalogUnavailable(j['id_message'])
        return j['data']['reply']

    def _get_search(self, ra, dec, radius_arcsec):
        data = dict(ra=ra, dec=dec, radius=radius_arcsec, units='arcsec')
        response = self._api_session.post(self._search_api_url, files=self._prepare_request_data(data))
        reply = self._reply(response)
        return [obj['objname'] for obj in reply]

    def _get_object(self, objname):
        data = dict(objname=objname, photometry=0, spectra=0)
        response = self._api_session.post(self._object_api_url, files=self._prepare_request_data(data))

        reply = self._reply(response)
        if not reply['public']:
            return None

        if isinstance(reply['object_type'], dict):
            reply['object_type'] = reply['object_type']['name']

        def flat(x):
            if isinstance(x, list) or isinstance(x, dict):
                return str(x)
            return x
        reply = {k: flat(v) for k, v in reply.items()}

        return reply

    def _api_query_region(self, ra, dec, radius_arcsec):
        objnames = self._get_search(ra, dec, radius_arcsec)
        objs = [obj for name in objnames if (obj := self._get_object(name))]
        table = Table.from_pandas(pd.DataFrame.from_records(objs))
        table['fullname'] = [f'{row["name_prefix"] or ""}{row["objname"]}' for row in table]
        return table

    def get_url(self, id):
        return f'//www.wis-tns.org/object/{id}'

    def add_redshift_column(self, table):
        table['__redshift'] = [row['redshift'] if row['redshift'] else row['host_redshift'] for row in table]

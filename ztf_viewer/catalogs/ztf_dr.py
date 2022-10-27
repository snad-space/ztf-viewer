import logging
from urllib.parse import urljoin, urlsplit, urlencode, urlunsplit

import requests
from astropy.coordinates import SkyCoord

from ztf_viewer.cache import cache
from ztf_viewer.config import LC_API_URL
from ztf_viewer.exceptions import NotFound, CatalogUnavailable
from ztf_viewer.util import INF


class _BaseFindZTF:
    _base_api_url = urljoin(LC_API_URL, '/api/v3/')

    def __init__(self):
        self._api_session = requests.Session()

    def _api_url(self, dr):
        return urljoin(self._base_api_url, f'data/{dr}/')

    def find(self, *args, **kwargs):
        raise NotImplemented


class FindZTFOID(_BaseFindZTF):
    def __init__(self):
        super().__init__()

    def _oid_api_url(self, dr):
        return urljoin(self._api_url(dr), 'oid/full/json')

    def json_url(self, oid, dr):
        parts = list(urlsplit(self._oid_api_url(dr)))
        parts[3] = urlencode(self._query_dict(oid))
        return urlunsplit(parts)

    @staticmethod
    def _query_dict(oid):
        return dict(oid=oid)

    @cache()
    def find(self, oid, dr):
        resp = self._api_session.get(self._oid_api_url(dr), params=self._query_dict(oid), timeout=60)
        if resp.status_code != 200:
            message = f'{resp.url} returned {resp.status_code}: {resp.text}'
            logging.info(message)
            raise NotFound(message)
        return resp.json()[str(oid)]

    def get_coord(self, oid, dr):
        meta = self.get_meta(oid, dr)
        if meta is None:
            raise NotFound
        coord = meta['coord']
        return coord['ra'], coord['dec']

    def get_sky_coord(self, oid, dr):
        ra, dec = self.get_coord(oid, dr)
        return SkyCoord(ra=ra, dec=dec, unit='deg')

    def get_coord_string(self, oid, dr, frame=None):
        try:
            ra, dec = self.get_coord(oid, dr)
        except TypeError as e:
            raise NotFound from e
        if frame is None:
            return f'{ra:.5f} {dec:.5f}'
        sky_coord = SkyCoord(ra=ra, dec=dec, unit='deg')
        frame_coord = sky_coord.transform_to(frame)
        return frame_coord.to_string()

    def get_meta(self, oid, dr):
        j = self.find(oid, dr)
        return j['meta']

    def get_lc(self, oid, dr, min_mjd=None, max_mjd=None):
        if min_mjd is None:
            min_mjd = -INF
        if max_mjd is None:
            max_mjd = INF
        j = self.find(oid, dr)
        lc = [obs.copy() for obs in j['lc'] if min_mjd <= obs['mjd'] <= max_mjd]
        return lc


find_ztf_oid = FindZTFOID()


class FindZTFCircle(_BaseFindZTF):
    def __init__(self):
        super().__init__()

    def _circle_api_url(self, dr):
        return urljoin(self._api_url(dr), 'circle/full/json')

    @cache()
    def find(self, ra, dec, radius_arcsec, dr):
        resp = self._api_session.get(
            self._circle_api_url(dr),
            params=dict(ra=ra, dec=dec, radius_arcsec=radius_arcsec),
            timeout=60,
        )
        if resp.status_code != 200:
            raise CatalogUnavailable
        j = resp.json()
        if not j:
            raise NotFound
        coord = SkyCoord(ra, dec, unit='deg', frame='icrs')
        cat_coord = SkyCoord(ra=[obj['meta']['coord']['ra'] for obj in j.values()],
                             dec=[obj['meta']['coord']['dec'] for obj in j.values()],
                             unit='deg',
                             frame='icrs')
        sep = coord.separation(cat_coord).to_value('arcsec')
        for obj, r in zip(j.values(), sep):
            obj['separation'] = r
        return j


find_ztf_circle = FindZTFCircle()

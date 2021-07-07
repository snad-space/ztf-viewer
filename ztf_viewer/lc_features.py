import requests

from ztf_viewer.cache import cache
from ztf_viewer.catalogs.ztf import find_ztf_oid
from ztf_viewer.util import NotFound


class LightCurveFeatures:
    _base_api_url = 'http://features.lc.snad.space'

    def __init__(self):
        self._api_session = requests.Session()
        self._find_ztf_oid = find_ztf_oid

    @cache()
    def __call__(self, oid, dr, min_mjd=None, max_mjd=None):
        lc = find_ztf_oid.get_lc(oid, dr, min_mjd=min_mjd, max_mjd=max_mjd)
        light_curve = [dict(t=obs['mjd'], m=obs['mag'], err=obs['magerr']) for obs in lc]
        j = dict(light_curve=light_curve)
        resp = self._api_session.post(self._base_api_url, json=j)
        if resp.status_code != 200:
            raise NotFound
        return resp.json()


light_curve_features = LightCurveFeatures()

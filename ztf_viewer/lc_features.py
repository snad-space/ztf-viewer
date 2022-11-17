from typing import List

import requests

from ztf_viewer.cache import cache
from ztf_viewer.catalogs.ztf_dr import find_ztf_oid
from ztf_viewer.config import FEATURES_API_URL
from ztf_viewer.exceptions import NotFound


class LightCurveFeatures:
    _base_api_url = FEATURES_API_URL

    def __init__(self):
        self._api_session = requests.Session()
        self._find_ztf_oid = find_ztf_oid

    @cache()
    def versions(self) -> List[str]:
        url = f"{self._base_api_url}/versions"
        resp = self._api_session.get(url)
        if resp.status_code != 200:
            raise NotFound
        return resp.json()

    def url(self, version: str = "latest") -> str:
        return f"{self._base_api_url}/api/{version}/"

    @cache()
    def __call__(self, oid, dr, version, min_mjd=None, max_mjd=None):
        lc = find_ztf_oid.get_lc(oid, dr, min_mjd=min_mjd, max_mjd=max_mjd)
        light_curve = [dict(t=obs["mjd"], m=obs["mag"], err=obs["magerr"]) for obs in lc]
        j = dict(light_curve=light_curve)
        resp = self._api_session.post(self.url(version), json=j)
        if resp.status_code != 200:
            raise NotFound
        return resp.json()


light_curve_features = LightCurveFeatures()

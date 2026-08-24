
from ztf_viewer.cache import cache
from ztf_viewer.catalogs.ztf_dr import find_ztf_oid
from ztf_viewer.config import FEATURES_API_URL, TIMEOUT_FEATURES
from ztf_viewer.exceptions import NotFound
from ztf_viewer.http import get_client


class LightCurveFeatures:
    _base_api_url = FEATURES_API_URL

    def __init__(self):
        self._find_ztf_oid = find_ztf_oid

    @cache()
    async def versions(self) -> list[str]:
        url = f"{self._base_api_url}/versions"
        client = get_client()
        resp = await client.get(url, timeout=TIMEOUT_FEATURES)
        if resp.status_code != 200:
            raise NotFound
        return resp.json()

    def url(self, version: str = "latest") -> str:
        return f"{self._base_api_url}/api/{version}/"

    @cache()
    async def __call__(self, oid, dr, version, min_mjd=None, max_mjd=None):
        lc = await find_ztf_oid.get_lc(oid, dr, min_mjd=min_mjd, max_mjd=max_mjd)
        light_curve = [dict(t=obs["mjd"], m=obs["mag"], err=obs["magerr"]) for obs in lc]
        j = dict(light_curve=light_curve)
        client = get_client()
        resp = await client.post(self.url(version), json=j, timeout=TIMEOUT_FEATURES)
        if resp.status_code != 200:
            raise NotFound
        return resp.json()


light_curve_features = LightCurveFeatures()

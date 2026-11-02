import logging
from io import BytesIO
from typing import ClassVar

import httpx
import pandas as pd
from astropy.coordinates import EarthLocation, SkyCoord
from astropy.time import Time

from ztf_viewer.cache import cache
from ztf_viewer.catalogs.conesearch._base import _BaseCatalogApiQuery, _BaseLightCurveQuery
from ztf_viewer.config import TIMEOUT_CONESEARCH_API
from ztf_viewer.exceptions import CatalogUnavailable, NotFound
from ztf_viewer.http import get_client

logger = logging.getLogger(__name__)

# Alert light curves carry their fluxes: plot_data would otherwise derive them from magnitudes
LIGHT_CURVE_COLUMNS = [
    "oid",
    "mjd",
    "mag",
    "magerr",
    "flux_Jy",
    "fluxerr_Jy",
    "diffflux_Jy",
    "difffluxerr_Jy",
    "filter",
]


class _BaseFinkQuery(_BaseCatalogApiQuery, _BaseLightCurveQuery):
    """Fink alert light curves, one subclass per survey.

    A subclass converts the API response to a light curve with a raw `time` column, in its
    `_time_format` and `_time_scale`, observed at `_site`; this class turns it into HMJD UTC,
    as ZTF DR light curves are.
    """

    _light_curve_url: ClassVar[str]
    _light_curve_id_param: ClassVar[str]
    _light_curve_columns: ClassVar[tuple]
    _light_curve_extra_columns: ClassVar[list] = []
    _time_format: ClassVar[str]
    _time_scale: ClassVar[str]
    _site: ClassVar[EarthLocation]

    @staticmethod
    def _to_light_curve(df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError

    @cache()
    async def light_curve(self, id, row=None):
        await self._raise_if_unavailable_async()
        json_dict = {
            self._light_curve_id_param: str(id),
            "columns": ",".join(self._light_curve_columns),
            "output-format": "json",
        }
        try:
            response = await get_client().post(self._light_curve_url, json=json_dict, timeout=TIMEOUT_CONESEARCH_API)
        except httpx.HTTPError as e:
            logger.info(str(e))
            raise CatalogUnavailable(catalog=self)
        self._raise_if_not_ok(response)
        df = pd.read_json(BytesIO(response.content), dtype={self.id_column: str})
        if len(df) == 0:
            raise NotFound
        lc = self._to_light_curve(df)
        coord = SkyCoord(ra=lc["ra"], dec=lc["dec"], unit="deg")
        time = Time(lc["time"].to_numpy(), format=self._time_format, scale=self._time_scale).utc
        lc["mjd"] = (time + time.light_travel_time(coord, "heliocentric", location=self._site)).mjd
        return lc[LIGHT_CURVE_COLUMNS + self._light_curve_extra_columns].to_dict(orient="records")

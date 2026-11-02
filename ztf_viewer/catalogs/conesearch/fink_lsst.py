import logging
from io import BytesIO
from typing import ClassVar
from urllib.parse import urljoin

import httpx
import numpy as np
import pandas as pd
from astropy.coordinates import EarthLocation, SkyCoord
from astropy.table import Table
from astropy.time import Time

from ztf_viewer.cache import cache
from ztf_viewer.catalogs.conesearch._base import _BaseCatalogApiQuery, _BaseLightCurveQuery
from ztf_viewer.catalogs.conesearch.fink import LIGHT_CURVE_COLUMNS
from ztf_viewer.config import TIMEOUT_CONESEARCH_API
from ztf_viewer.exceptions import CatalogUnavailable, NotFound
from ztf_viewer.http import get_client
from ztf_viewer.util import ABZPMAG_JY, LGE_25

logger = logging.getLogger(__name__)

CERRO_PACHON = EarthLocation(lon=-70.749417, lat=-30.244639, height=2663.0)  # EarthLocation.of_site('Rubin')

NJY = 1e-9


def sources_to_light_curve(df: pd.DataFrame) -> pd.DataFrame:
    """Light curve of LSST diaSources: psfFlux is the difference flux, scienceFlux the apparent one.

    scienceFlux is forced PSF photometry on the visit image. Magnitudes are infinite where it is
    not positive.
    """
    flux = df["r:scienceFlux"].to_numpy(dtype=float) * NJY
    fluxerr = df["r:scienceFluxErr"].to_numpy(dtype=float) * NJY
    with np.errstate(divide="ignore", invalid="ignore"):
        mag = np.where(flux > 0, ABZPMAG_JY - 2.5 * np.log10(flux), np.inf)
        magerr = np.where(flux > 0, LGE_25 * fluxerr / flux, np.inf)
    return pd.DataFrame(
        {
            # diaObjectId doesn't fit into a JavaScript number
            "oid": df["r:diaObjectId"].astype(str).to_numpy(),
            "mjd_tai": df["r:midpointMjdTai"].to_numpy(dtype=float),
            "mag": mag,
            "magerr": magerr,
            "flux_Jy": flux,
            "fluxerr_Jy": fluxerr,
            "diffflux_Jy": df["r:psfFlux"].to_numpy(dtype=float) * NJY,
            "difffluxerr_Jy": df["r:psfFluxErr"].to_numpy(dtype=float) * NJY,
            "filter": ("Fink/LSST " + df["r:band"].astype(str)).to_numpy(),
            "ra": df["r:ra"].to_numpy(dtype=float),
            "dec": df["r:dec"].to_numpy(dtype=float),
        }
    )


class FinkLsstQuery(_BaseCatalogApiQuery, _BaseLightCurveQuery):
    id_column = "r:diaObjectId"
    _table_ra = "r:ra"
    _ra_unit = "deg"
    _table_dec = "r:dec"
    columns: ClassVar[dict] = {
        "__link": "diaObjectId",
        "separation": "Separation, arcsec",
    }

    _base_url = "https://api.lsst.fink-portal.org"
    _portal_url = "https://lsst.fink-portal.org"
    _api_url = urljoin(_base_url, "/api/v1/conesearch")
    _api_url_sources = urljoin(_base_url, "/api/v1/sources")

    _light_curve_columns: ClassVar[tuple] = (
        "r:diaObjectId",
        "r:midpointMjdTai",
        "r:ra",
        "r:dec",
        "r:band",
        "r:psfFlux",
        "r:psfFluxErr",
        "r:scienceFlux",
        "r:scienceFluxErr",
    )

    async def _api_query_region(self, ra, dec, radius_arcsec):
        json_dict = {
            "ra": ra,
            "dec": dec,
            "radius": radius_arcsec,
            "columns": f"{self.id_column},{self._table_ra},{self._table_dec}",
            "output-format": "json",
        }
        response = await get_client().post(self._api_url, json=json_dict, timeout=TIMEOUT_CONESEARCH_API)
        self._raise_if_not_ok(response)
        df = pd.read_json(BytesIO(response.content), dtype={self.id_column: str})
        if len(df) == 0:
            raise NotFound
        return Table.from_pandas(df.drop_duplicates(self.id_column))

    @cache()
    async def light_curve(self, id, row=None):
        await self._raise_if_unavailable_async()
        json_dict = {
            "diaObjectId": str(id),
            "columns": ",".join(self._light_curve_columns),
            "output-format": "json",
        }
        try:
            response = await get_client().post(self._api_url_sources, json=json_dict, timeout=TIMEOUT_CONESEARCH_API)
        except httpx.HTTPError as e:
            logger.info(str(e))
            raise CatalogUnavailable(catalog=self)
        self._raise_if_not_ok(response)
        df = pd.read_json(BytesIO(response.content), dtype={self.id_column: str})
        if len(df) == 0:
            raise NotFound
        lc = sources_to_light_curve(df)
        # ZTF DR light curves are in HMJD UTC
        coord = SkyCoord(ra=lc["ra"], dec=lc["dec"], unit="deg")
        time = Time(Time(lc["mjd_tai"].to_numpy(), format="mjd", scale="tai"), scale="utc")
        lc["mjd"] = (time + time.light_travel_time(coord, "heliocentric", location=CERRO_PACHON)).mjd
        return lc[LIGHT_CURVE_COLUMNS].to_dict(orient="records")

    def get_url(self, id, row=None):
        return urljoin(self._portal_url, str(id))

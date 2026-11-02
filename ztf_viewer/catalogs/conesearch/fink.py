import logging
from io import BytesIO
from typing import ClassVar
from urllib.parse import urljoin

import httpx
import numpy as np
import pandas as pd
from astropy.coordinates import SkyCoord
from astropy.table import Table
from astropy.time import Time

from ztf_viewer.cache import cache
from ztf_viewer.catalogs.conesearch._base import _BaseCatalogApiQuery, _BaseLightCurveQuery
from ztf_viewer.config import TIMEOUT_CONESEARCH_API
from ztf_viewer.exceptions import CatalogUnavailable, NotFound
from ztf_viewer.http import get_client
from ztf_viewer.util import ABZPMAG_JY, LGE_25, LN10_04, PALOMAR, ZTF_FILTERS

logger = logging.getLogger(__name__)

# A reference source further than this is not the one the alert is on: ZTF's distnr is in
# pixels, PS1's distpsnr1 in arcsec, ~1 arcsec/pixel makes them interchangeable here
MAX_REF_DISTANCE = 1.0

# Alert fid follows the ZTF_FILTERS order
ZTF_BANDS = {fid: fltr.removeprefix("z") for fid, fltr in enumerate(ZTF_FILTERS, start=1)}
PS1_MAG_COLUMNS = {1: "i:sgmag1", 2: "i:srmag1", 3: "i:simag1"}

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


def alerts_to_light_curve(df: pd.DataFrame) -> pd.DataFrame:
    """Light curve of ZTF alerts: native difference flux, and apparent flux simulated from it.

    Apparent flux is the difference flux plus the reference flux under the alert: ZTF's
    reference-image source when the alert sits on one, the same-band PS1 source otherwise, and
    zero if neither is there. Magnitudes are infinite where that flux is not positive.
    """
    fid = df["i:fid"].to_numpy()
    magnr = df["i:magnr"].to_numpy(dtype=float, na_value=np.nan)
    sigmagnr = df["i:sigmagnr"].to_numpy(dtype=float, na_value=np.nan)
    distnr = df["i:distnr"].to_numpy(dtype=float, na_value=np.nan)
    distpsnr1 = df["i:distpsnr1"].to_numpy(dtype=float, na_value=np.nan)
    ps1_mag = np.full(len(df), np.nan)
    for f, column in PS1_MAG_COLUMNS.items():
        ps1_mag = np.where(fid == f, df[column].to_numpy(dtype=float, na_value=np.nan), ps1_mag)

    # Missing values come as -999, so a non-negative check also rules them out
    is_ztf_ref = (distnr >= 0) & (distnr < MAX_REF_DISTANCE) & (magnr > 0) & (sigmagnr >= 0)
    is_ps1_ref = ~is_ztf_ref & (distpsnr1 >= 0) & (distpsnr1 < MAX_REF_DISTANCE) & (ps1_mag > 0)
    ref_mag = np.where(is_ztf_ref, magnr, np.where(is_ps1_ref, ps1_mag, np.inf))
    ref_magerr = np.where(is_ztf_ref, sigmagnr, 0.0)

    sign = np.where(df["i:isdiffpos"].isin(["t", "1"]).to_numpy(), 1.0, -1.0)
    diffflux = sign * 10 ** (-0.4 * (df["i:magpsf"].to_numpy(dtype=float) - ABZPMAG_JY))
    difffluxerr = LN10_04 * np.abs(diffflux) * df["i:sigmapsf"].to_numpy(dtype=float)
    ref_flux = 10 ** (-0.4 * (ref_mag - ABZPMAG_JY))
    flux = ref_flux + diffflux
    fluxerr = np.hypot(LN10_04 * ref_flux * ref_magerr, difffluxerr)

    with np.errstate(divide="ignore", invalid="ignore"):
        mag = np.where(flux > 0, ABZPMAG_JY - 2.5 * np.log10(flux), np.inf)
        magerr = np.where(flux > 0, LGE_25 * fluxerr / flux, np.inf)
    return pd.DataFrame(
        {
            "oid": df["i:objectId"],
            "jd": df["i:jd"],
            "mag": mag,
            "magerr": magerr,
            "flux_Jy": flux,
            "fluxerr_Jy": fluxerr,
            "diffflux_Jy": diffflux,
            "difffluxerr_Jy": difffluxerr,
            "filter": [f"Fink/ZTF {ZTF_BANDS.get(f, f)}" for f in fid],
            "ref_catalog": np.where(is_ztf_ref, "ZTF", np.where(is_ps1_ref, "PS1", "none")),
            "ra": df["i:ra"],
            "dec": df["i:dec"],
        }
    )


class FinkQuery(_BaseCatalogApiQuery, _BaseLightCurveQuery):
    id_column = "i:objectId"
    _table_ra = "i:ra"
    _ra_unit = "deg"
    _table_dec = "i:dec"
    columns: ClassVar[dict] = {
        "__link": "Name",
        "separation": "Separation, arcsec",
        "d:classification": "Class",
        "d:mulens": "Prob to be a μLens",
        "d:rf_kn_vs_nonkn": "Prob of KN vs all",
        "d:rf_snia_vs_nonia": "Prob of SN Ia vs all",
        "d:snn_sn_vs_all": "Prob of SN vs all",
        "d:snn_snia_vs_nonia": "Prob of SN Ia vs CC SN",
    }

    _classifiers: ClassVar[dict] = {
        "μLens prob": "d:mulens",
        "RF KN vs all": "d:rf_kn_vs_nonkn",
        # 'RF SN Ia vs all': 'd:rf_snia_vs_nonia',             <- disabled because we decided to not show it
        "SuperNNova SN vs all": "d:snn_sn_vs_all",
        # 'SuperNNova SN Ia vs CC SN': 'd:snn_snia_vs_nonia',  <- disabled because we decided to not show it
    }
    _class_names: ClassVar[dict] = {
        "μLens prob": "μLens",
        "RF KN vs all": "KN",
        "SuperNNova SN vs all": "SN",
    }
    _prob_class_columns: ClassVar[dict] = {k: f"{v}_classifications" for k, v in _classifiers.items()}

    _base_url = "https://api.ztf.fink-portal.org"
    _portal_url = "https://ztf.fink-portal.org"
    _api_url = urljoin(_base_url, "/api/v1/conesearch")
    _api_url_objects = urljoin(_base_url, "/api/v1/objects")

    _light_curve_columns: ClassVar[tuple] = (
        "i:objectId",
        "i:jd",
        "i:ra",
        "i:dec",
        "i:fid",
        "i:magpsf",
        "i:sigmapsf",
        "i:isdiffpos",
        "i:magnr",
        "i:sigmagnr",
        "i:distnr",
        "i:distpsnr1",
        *PS1_MAG_COLUMNS.values(),
    )

    async def _get_classifications(self, object_ids) -> pd.DataFrame:
        time_column = "i:jd"
        columns = [time_column, self.id_column] + [c for c in self.columns if c.startswith("d:")]
        json_dict = {
            "objectId": ",".join(object_ids),
            "columns": ",".join(columns),
            "output-format": "json",
        }
        response = await get_client().post(self._api_url_objects, json=json_dict, timeout=TIMEOUT_CONESEARCH_API)
        self._raise_if_not_ok(response)
        df = pd.read_json(BytesIO(response.content))
        # Select the latest classification for each object
        df = df.loc[df.groupby(self.id_column)[time_column].idxmin()]
        del df[time_column]
        return df.reset_index(drop=True)

    async def _api_query_region(self, ra, dec, radius_arcsec):
        json_dict = {
            "ra": ra,
            "dec": dec,
            "radius": radius_arcsec,
            "output-format": "json",
        }
        response = await get_client().post(self._api_url, json=json_dict, timeout=TIMEOUT_CONESEARCH_API)
        self._raise_if_not_ok(response)
        df = pd.read_json(BytesIO(response.content))
        if len(df) == 0:
            raise NotFound
        classifications = await self._get_classifications(df[self.id_column])
        df = df.join(
            classifications.reset_index(drop=True).set_index(self.id_column),
            on=self.id_column,
            how="left",
        )
        return Table.from_pandas(df)

    async def add_prob_class_columns(self, table):
        for column in self._prob_class_columns.values():
            table[column] = [{} for _ in range(len(table))]
        for row in table:
            for pretty_name, classifier in self._classifiers.items():
                column = self._prob_class_columns[pretty_name]
                class_name = self._class_names[pretty_name]
                if (prob := row[classifier]) is None:
                    continue
                row[column][class_name] = prob

    def get_url(self, id, row=None):
        return urljoin(self._portal_url, id)

    @cache()
    async def light_curve(self, id, row=None):
        await self._raise_if_unavailable_async()
        json_dict = {
            "objectId": id,
            "columns": ",".join(self._light_curve_columns),
            "output-format": "json",
        }
        try:
            response = await get_client().post(self._api_url_objects, json=json_dict, timeout=TIMEOUT_CONESEARCH_API)
        except httpx.HTTPError as e:
            logger.info(str(e))
            raise CatalogUnavailable(catalog=self)
        self._raise_if_not_ok(response)
        df = pd.read_json(BytesIO(response.content))
        if len(df) == 0:
            raise NotFound
        lc = alerts_to_light_curve(df)
        # Alert time is the exposure start, JD UTC; ZTF DR light curves are in HMJD
        coord = SkyCoord(ra=lc["ra"], dec=lc["dec"], unit="deg")
        time = Time(lc["jd"].to_numpy(), format="jd", scale="utc")
        lc["mjd"] = (time + time.light_travel_time(coord, "heliocentric", location=PALOMAR)).mjd
        return lc[LIGHT_CURVE_COLUMNS + ["ref_catalog"]].to_dict(orient="records")

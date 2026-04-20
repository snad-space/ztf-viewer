import numpy as np
import requests
from pydantic import BaseModel
from typing import Literal, List, Dict, Optional

from ztf_viewer.cache import cache
from ztf_viewer.catalogs.ztf_dr import find_ztf_oid
from ztf_viewer.config import MODEL_FIT_API_URL
from ztf_viewer.util import ABZPMAG_JY, LN10_04, immutabledefaultdict


def post_request(url, data):
    try:
        response = requests.post(url, json=data.model_dump())
        response.raise_for_status()
        return {"success": True, "body": response.json()}
    except (
        requests.exceptions.HTTPError,
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
        requests.exceptions.RequestException,
    ) as e:
        print(f"A model-fit-api error occurred: {e}")
        return {"success": False, "body": "API is unavailable"}


def get_request(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        return {"success": True, "body": response.json()}
    except (
        requests.exceptions.HTTPError,
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
        requests.exceptions.RequestException,
    ) as e:
        print(f"A model-fit-api error occurred: {e}")
        return {"success": False, "body": "API is unavailable"}


class Observation(BaseModel):
    mjd: float
    band: str
    flux: float
    fluxerr: float
    zp: float = ABZPMAG_JY
    zpsys: Literal["ab", "vega"] = "ab"


class Target(BaseModel):
    light_curve: List[Observation]
    ebv: float
    name_model: str
    redshift: List[float] = [0.05, 0.3]


class ModelData(BaseModel):
    parameters: Dict[str, float]
    name_model: str
    zp: float = ABZPMAG_JY
    zpsys: str = "ab"
    band_list: List[str]
    t_min: float
    t_max: float
    count: int = 2000
    brightness_type: str
    band_ref: Dict[str, float]


class Response(BaseModel):
    success: bool
    data: Optional[dict] = {}
    message: Optional[str] = []


class ModelFit:
    _base_api_url = f"{MODEL_FIT_API_URL}/api/v1"
    _models_api_url = _base_api_url + "/models"
    _fit_api_url = _base_api_url + "/sncosmo/fit"
    _get_curve_api_url = _base_api_url + "/sncosmo/get_curve"

    def __init__(self):
        self._api_session = requests.Session()

    @cache()
    def fit(
        self,
        oids: tuple[int],
        dr: str,
        *,
        fit_model: str,
        ebv: float,
        min_mjd=None,
        max_mjd=None,
        ref_mag,
        ref_magerr=immutabledefaultdict(float),
    ):
        observations = []
        for oid in oids:
            lc = find_ztf_oid.get_lc(oid, dr, min_mjd=min_mjd, max_mjd=max_mjd)
            flt = find_ztf_oid.get_meta(oid, dr)["filter"]
            ref_flux = 10 ** (-0.4 * (ref_mag[oid] - ABZPMAG_JY))
            ref_fluxerr = LN10_04 * ref_flux * ref_magerr[oid]
            for obs in lc:
                flux_Jy = 10 ** (-0.4 * (obs["mag"] - ABZPMAG_JY))
                fluxerr_Jy = LN10_04 * flux_Jy * obs["magerr"]
                diffflux_Jy = flux_Jy - ref_flux
                difffluxerr_Jy = float(np.hypot(fluxerr_Jy, ref_fluxerr))
                observations.append(
                    Observation(
                        mjd=float(obs["mjd"]),
                        flux=float(diffflux_Jy),
                        fluxerr=difffluxerr_Jy,
                        band="ztf" + flt[1:],
                    )
                )
        res_fit = post_request(
            self._fit_api_url,
            Target(light_curve=observations, ebv=ebv, name_model=fit_model),
        )
        if res_fit["success"]:
            return Response(success=res_fit["success"], data=res_fit["body"])
        else:
            return Response(success=res_fit["success"], data={"parameters": {}}, message=res_fit["body"])

    def get_curve(
        self,
        oids: tuple[int],
        dr: str,
        *,
        bright: str,
        params: dict,
        name_model: str,
        min_mjd=None,
        max_mjd=None,
        ref_mag,
    ):
        band_ref_sums = {}
        band_ref_counts = {}
        mjd_values = []

        for oid in oids:
            lc = find_ztf_oid.get_lc(oid, dr, min_mjd=min_mjd, max_mjd=max_mjd)
            flt = find_ztf_oid.get_meta(oid, dr)["filter"]
            ref_flux = 10 ** (-0.4 * (ref_mag[oid] - ABZPMAG_JY))
            for obs in lc:
                mjd_values.append(obs["mjd"])
                band_ref_sums[flt] = band_ref_sums.get(flt, 0.0) + ref_flux
                band_ref_counts[flt] = band_ref_counts.get(flt, 0) + 1

        band_ref = {flt: band_ref_sums[flt] / band_ref_counts[flt] for flt in band_ref_sums}
        band_list = ["ztf" + flt[1:] for flt in band_ref]
        mjd_min = min(mjd_values)
        mjd_max = max(mjd_values)

        res_curve = post_request(
            self._get_curve_api_url,
            ModelData(
                parameters=dict(params),
                name_model=name_model,
                band_list=band_list,
                t_min=mjd_min,
                t_max=mjd_max,
                brightness_type=bright,
                band_ref=band_ref,
            ),
        )
        if res_curve["success"]:
            return Response(success=res_curve["success"], data=res_curve["body"])
        else:
            return Response(success=res_curve["success"], data={"bright": {}}, message=res_curve["body"])

    def get_list_models(self):
        res_models = get_request(self._models_api_url)
        if res_models["success"]:
            return Response(success=res_models["success"], data=res_models["body"])
        else:
            return Response(success=res_models["success"], data={"models": []}, message=res_models["body"])


model_fit = ModelFit()

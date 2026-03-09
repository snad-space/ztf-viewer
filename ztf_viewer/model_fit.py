import numpy as np
import pandas as pd
import requests
from pydantic import BaseModel
from typing import Literal, List, Dict, Optional
from ztf_viewer.catalogs.ztf_ref import ztf_ref
from ztf_viewer.config import MODEL_FIT_API_URL
from ztf_viewer.exceptions import NotFound, CatalogUnavailable
from ztf_viewer.util import ABZPMAG_JY, LN10_04


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
    bright_fit = "diffflux_Jy"
    brighterr_fit = "difffluxerr_Jy"

    def __init__(self):
        self._api_session = requests.Session()

    def fit(self, df, fit_model, dr, ebv):
        df = df.copy()
        refs = df["ref_flux"].unique()
        print(df["ref_flux"].unique(), (len(refs) == 1 and refs[0] == 0.0), 'there is ref_flux in data')
        oid_ref = {}
        if len(refs) == 1 and refs[0] == 0.0:
            for objectid in df["oid"].unique():
                try:
                    ref = ztf_ref.get(objectid, dr)
                except (NotFound, CatalogUnavailable):
                    return {"error": "ZTF Reference catalog is unavailable"}
                ref_mag = ref["mag"] + ref["magzp"]
                ref_magerr = ref["sigmag"]
                oid_ref[objectid] = {"mag": ref_mag, "err": ref_magerr}
            print(oid_ref, 'oid_ref from modelfit')
            df["ref_flux"] = df["oid"].apply(lambda x: 10 ** (-0.4 * (oid_ref[x]["mag"] - ABZPMAG_JY)))
            df["diffflux_Jy"] = df["flux_Jy"] - df["ref_flux"]
            df["difffluxerr_Jy"] = [
                np.hypot(fluxerr, LN10_04 * ref_flux * oid_ref[oid]["err"])
                for fluxerr, ref_flux, oid in zip(df["fluxerr_Jy"], df["ref_flux"], df["oid"])
            ]
        res_fit = post_request(
            self._fit_api_url,
            Target(
                light_curve=[
                    Observation(
                        mjd=float(mjd),
                        flux=float(br),
                        fluxerr=float(br_err),
                        band="ztf" + str(band[1:]),
                    )
                    for br, mjd, br_err, band in zip(
                        df[self.bright_fit], df["mjd"], df[self.brighterr_fit], df["filter"]
                    )
                ],
                ebv=ebv,
                name_model=fit_model,
            ),
        )
        if res_fit["success"]:
            return Response(success=res_fit["success"], data={"parameters": res_fit["body"]["parameters"], "oid_ref_fit": oid_ref})
        else:
            return Response(success=res_fit["success"], data={"parameters": {}}, message=res_fit["body"])

    def get_curve(self, df, dr, bright, params, name_model):
        band_ref = {}
        band_list = ["ztf" + str(band[1:]) for band in df["filter"].unique()]
        mjd_min = df["mjd"].min()
        mjd_max = df["mjd"].max()
        df = df.copy()
        if "ref_flux" not in df.columns:
            oid_ref = {}
            try:
                for objectid in df["oid"].unique():
                    ref = ztf_ref.get(objectid, dr)
                    ref_mag = ref["mag"] + ref["magzp"]
                    oid_ref[objectid] = ref_mag
                df["ref_flux"] = df["oid"].apply(lambda x: 10 ** (-0.4 * (oid_ref[x] - ABZPMAG_JY)))
            except (NotFound, CatalogUnavailable):
                print("Catalog error")
                return pd.DataFrame.from_records([])

        for band in df["filter"].unique():
            band_ref[band] = df[df["filter"] == band]["ref_flux"].mean().astype(float)
        res_curve = post_request(
            self._get_curve_api_url,
            ModelData(
                parameters=params,
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

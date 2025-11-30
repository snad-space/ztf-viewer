import numpy as np
import pandas as pd
import requests
from pydantic import BaseModel
from typing import Literal, List, Dict
from ztf_viewer.catalogs.ztf_ref import ztf_ref
from ztf_viewer.exceptions import NotFound, CatalogUnavailable
from ztf_viewer.util import ABZPMAG_JY, LN10_04

def post_request(url, data):
    try:
        response = requests.post(url, json=data.model_dump())
        response.raise_for_status()
        return response.status_code, response.json()
    except requests.exceptions.HTTPError as e:
        print(f"HTTP error occurred: {e}")
        return e.response.status_code, None
    except requests.exceptions.ConnectionError as e:
        print(f"Connection error: {e}")
        return 0, None
    except requests.exceptions.Timeout as e:
        print(f"Timeout error: {e}")
        return -1, None
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
        return -2, None

def get_request(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.status_code, response.json()
    except requests.exceptions.HTTPError as e:
        print(f"HTTP error occurred: {e}")
        return e.response.status_code, None
    except requests.exceptions.ConnectionError as e:
        print(f"Connection error: {e}")
        return 0, None
    except requests.exceptions.Timeout as e:
        print(f"Timeout error: {e}")
        return -1, None
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
        return -2, None

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

class ModelFit:
    base_url = "http://host.docker.internal:8000/api/v1"
    bright_fit = "diffflux_Jy"
    brighterr_fit = "difffluxerr_Jy"

    def __init__(self):
        self._api_session = requests.Session()
        self.path = None

    def set_path(self, path):
        self.path = path

    def fit(self, df, fit_model, dr, ebv):
        self.set_path("/sncosmo/fit")
        df = df.copy()
        if 'ref_flux' not in df.columns:
            oid_ref = {}
            try:
                for objectid in df["oid"].unique():
                    ref = ztf_ref.get(objectid, dr)
                    ref_mag = ref["mag"] + ref["magzp"]
                    ref_magerr = ref["sigmag"]
                    oid_ref[objectid] = {"mag": ref_mag, "err": ref_magerr}
                df["ref_flux"] = df["oid"].apply(lambda x: 10 ** (-0.4 * (oid_ref[x]["mag"] - ABZPMAG_JY)))
                df["diffflux_Jy"] = df["flux_Jy"] - df["ref_flux"]
                df["difffluxerr_Jy"] = [
                    np.hypot(fluxerr, LN10_04 * ref_flux * oid_ref[oid]["err"])
                    for fluxerr, ref_flux, oid in zip(df["fluxerr_Jy"], df["ref_flux"], df["oid"])
                ]
            except (NotFound, CatalogUnavailable):
                print(f"Catalog error")
                return {}
        status_code, res_fit = post_request(
            self.base_url + self.path,
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
        if status_code == 200:
            return res_fit["parameters"]
        else:
            return {}

    def get_curve(self, df, dr, bright, params, name_model):
        self.set_path("/sncosmo/get_curve")
        band_ref = {}
        band_list = ["ztf" + str(band[1:]) for band in df["filter"].unique()]
        mjd_min = df["mjd"].min()
        mjd_max = df["mjd"].max()
        df = df.copy()
        if 'ref_flux' not in df.columns:
            oid_ref = {}
            try:
                for objectid in df["oid"].unique():
                    ref = ztf_ref.get(objectid, dr)
                    ref_mag = ref["mag"] + ref["magzp"]
                    oid_ref[objectid] = ref_mag
                df["ref_flux"] = df["oid"].apply(lambda x: 10 ** (-0.4 * (oid_ref[x] - ABZPMAG_JY)))
            except (NotFound, CatalogUnavailable):
                print(f"Catalog error")
                return pd.DataFrame.from_records([])

        for band in df["filter"].unique():
            band_ref[band] = df[df["filter"] == band]["ref_flux"].mean().astype(float)
        status_code, res_fit = post_request(
            self.base_url + self.path,
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
        if status_code == 200:
            df_fit = pd.DataFrame.from_records(res_fit["bright"])
            df_fit["time"] = df_fit["time"] - 58000
            return df_fit
        else:
            return pd.DataFrame.from_records([])

    def get_list_models(self):
        self.set_path("/models")
        status_code, list_models = get_request(self.base_url + self.path)
        if status_code == 200:
            return list_models["models"]
        else: return []


model_fit = ModelFit()

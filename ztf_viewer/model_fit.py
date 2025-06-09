import numpy as np
import pandas as pd
import requests
from ztf_viewer.catalogs.ztf_ref import ztf_ref
from ztf_viewer.exceptions import NotFound, CatalogUnavailable
from ztf_viewer.util import ABZPMAG_JY, LN10_04


class ModelFit:
    base_url = "http://host.docker.internal:8000/api/v1"
    bright_fit = "diffflux_Jy"
    brighterr_fit = "difffluxerr_Jy"

    def __init__(self):
        self._api_session = requests.Session()

    def fit(self, df, fit_model, ref_mag_values, dr, ebv):
        path = "/sncosmo/fit"
        if not ref_mag_values:
            oid_ref = {}
            try:
                for objectid in df["oid"].unique():
                    ref = ztf_ref.get(objectid, dr)
                    ref_mag = np.round(ref["mag"] + ref["magzp"], decimals=3)
                    ref_magerr = np.round(ref["sigmag"], decimals=3)
                    oid_ref[objectid] = {"mag": ref_mag, "err": ref_magerr}
                df["ref_flux"] = df["oid"].apply(lambda x: 10 ** (-0.4 * (oid_ref[x]["mag"] - ABZPMAG_JY)))
                df["diffflux_Jy"] = df["flux_Jy"] - df["ref_flux"]
                df["difffluxerr_Jy"] = [
                    np.hypot(fluxerr, LN10_04 * ref_flux * oid_ref[oid]["err"])
                    for fluxerr, ref_flux, oid in zip(df["fluxerr_Jy"], df["ref_flux"], df["oid"])
                ]
            except (NotFound, CatalogUnavailable):
                pass
        res_fit = requests.post(
            self.base_url + path,
            json={
                "light_curve": [
                    {
                        "mjd": float(mjd),
                        "flux": float(br),
                        "fluxerr": float(br_err),
                        "zp": 8.9,
                        "zpsys": "ab",
                        "band": "ztf" + str(band[1:]),
                    }
                    for br, mjd, br_err, band in zip(
                        df[self.bright_fit], df["mjd"], df[self.brighterr_fit], df["filter"]
                    )
                ],
                "ebv": ebv,
                "name_model": fit_model,
                "redshift": [0.05, 0.3],
            },
        )
        params = res_fit.json()["parameters"]
        return params

    def get_curve(self, df, dr, ref_mag_values, bright, params, name_model):
        path = "/sncosmo/get_curve"
        band_ref = {}
        band_list = ["ztf" + str(band[1:]) for band in df["filter"].unique()]
        mjd_min = df["mjd"].min()
        mjd_max = df["mjd"].max()
        if not ref_mag_values:
            oid_ref = {}
            try:
                for objectid in df["oid"].unique():
                    ref = ztf_ref.get(objectid, dr)
                    ref_mag = np.round(ref["mag"] + ref["magzp"], decimals=3)
                    oid_ref[objectid] = ref_mag
                df["ref_flux"] = df["oid"].apply(lambda x: 10 ** (-0.4 * (oid_ref[x] - ABZPMAG_JY)))
            except (NotFound, CatalogUnavailable):
                pass
        for band in df["filter"].unique():
            band_ref[band] = df[df["filter"] == band]["ref_flux"].mean().astype(float)
        res_fit = requests.post(
            self.base_url + path,
            json={
                "parameters": params,
                "name_model": name_model,
                "zp": 8.9,
                "zpsys": "ab",
                "band_list": band_list,
                "t_min": mjd_min,
                "t_max": mjd_max,
                "count": 2000,
                "brightness_type": bright,
                "band_ref": band_ref,
            },
        )
        return pd.DataFrame.from_records(res_fit.json()["bright"])

    def get_list_models(self):
        path = "/models"
        list_models = requests.get(self.base_url + path).json()
        return list_models["models"]


model_fit = ModelFit()

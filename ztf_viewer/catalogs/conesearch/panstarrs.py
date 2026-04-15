import logging
from itertools import count

import numpy as np
import requests
from astropy.coordinates import EarthLocation, SkyCoord
from astropy.table import MaskedColumn, Table
from astropy.time import Time
from requests import RequestException

from ztf_viewer.catalogs.conesearch._base import (
    ValueWithUncertaintyColumn,
    _BaseCatalogQuery,
    _BaseLightCurveQuery,
)
from ztf_viewer.exceptions import CatalogUnavailable, NotFound
from ztf_viewer.util import ABZPMAG_JY, LGE_25

HALEAKALA = EarthLocation(lon=-156.169, lat=20.71552, height=3048.0)  # EarthLocation.of_site('Haleakala')

_PANSTARRS_API = "https://catalogs.mast.stsci.edu/api/v0.1/panstarrs"


def _mast_json_to_table(json_obj):
    """Convert a MAST catalog JSON response to an astropy masked Table.

    The MAST PanSTARRS API returns rows as dicts and uses the string "None"
    for missing values in numeric columns, which astroquery 0.4.x does not
    handle (raises ValueError when casting to the column type).
    See https://github.com/snad-space/ztf-viewer/issues/565
    """
    data_table = Table(masked=True)
    type_key = "type" if json_obj["info"][0].get("type") else "db_type"

    for col in json_obj["info"]:
        col_name = col.get("column_name") or col.get("name")
        col_type = col[type_key].lower()

        col_data = np.array([row.get(col_name) for row in json_obj["data"]], dtype=object)

        # Identify missing values: JSON null → None, float NaN, or the string "None"
        is_missing = np.array(
            [v is None or v == "None" or (isinstance(v, float) and np.isnan(v)) for v in col_data],
            dtype=bool,
        )

        if col_type in ("char", "string", "null", "datetime") or "varchar" in col_type:
            col_data[is_missing] = ""
            col_mask = col_data == ""
            col_data = col_data.astype(str)
        elif col_type in ("boolean", "binary"):
            col_data[is_missing] = False
            col_data = col_data.astype(bool)
            col_mask = is_missing
        elif col_type == "unsignedbyte":
            col_data[is_missing] = 0
            col_data = col_data.astype(np.ubyte)
            col_mask = is_missing
        elif col_type in ("int", "short", "long", "number", "integer"):
            col_data[is_missing] = 0
            col_data = col_data.astype(np.int64)
            col_mask = is_missing
        elif col_type in ("double", "float", "decimal"):
            col_data[is_missing] = np.nan
            col_data = col_data.astype(np.float64)
            col_mask = is_missing
        else:
            col_mask = is_missing

        if col_name not in data_table.colnames:
            data_table.add_column(MaskedColumn(col_data, name=col_name, mask=col_mask))

    return data_table


def _panstarrs_request(session, release, table, **params):
    """POST to the MAST PanSTARRS catalog API and return an astropy Table."""
    url = f"{_PANSTARRS_API}/{release}/{table}.json"
    response = session.post(
        url,
        json=params,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        timeout=600,
    )
    response.raise_for_status()
    return _mast_json_to_table(response.json())


class PanstarrsDr2StackedQuery(_BaseCatalogQuery, _BaseLightCurveQuery):
    # https://outerspace.stsci.edu/display/PANSTARRS/PS1+FAQ+-+Frequently+asked+questions
    id_column = "objName"
    _table_ra = "raMean"
    _ra_unit = "deg"
    _table_dec = "decMean"
    columns = {
        "__link": "Name",
        "objID": "ID",
        "separation": "Separation, arcsec",
        "_gPSFMag": "g PSF mag",
        "_rPSFMag": "r mag",
        "_iPSFMag": "i mag",
        "_zPSFMag": "z mag",
        "_yPSFMag": "y mag",
    }

    _detection_url = "https://catalogs.mast.stsci.edu/panstarrs/detections.html"

    _bands = "grizy"
    _band_ids = dict(zip(count(1), _bands))
    _phot_types = ("Ap", "PSF")

    _value_with_uncertainty_columns = [
        ValueWithUncertaintyColumn(value=f"{b}PSFMag", uncertainty=f"{b}PSFMagErr") for b in _bands
    ]

    def __init__(self, query_name):
        super().__init__(query_name)
        self._session = requests.Session()

    def __apply_groups(self, df):
        """Averaging stacked objects

        Due to sky cells overlapping we can have multiple rows per a single
        object
        """
        row = df.iloc[0].copy()

        if df.shape[0] == 1:
            return row

        for band in self._bands:
            for phot_type in self._phot_types:
                mag_column = f"{band}{phot_type}Mag"
                err_column = f"{band}{phot_type}MagErr"
                idx = (df[mag_column] >= 0) & (df[err_column] >= 0)
                valid = df[idx]
                if len(valid) == 0:
                    row[mag_column] = np.nan
                    row[err_column] = np.nan
                else:
                    w_ = 1.0 / np.square(valid[err_column])
                    row[mag_column] = np.average(valid[mag_column], weights=w_)
                    row[err_column] = 1.0 / np.sqrt(np.mean(w_))

        return row

    def _query_region(self, coord, radius):
        # radius comes from the base class as a string like "18.0s" (arcseconds)
        if isinstance(radius, str) and radius.endswith("s"):
            radius_deg = float(radius[:-1]) / 3600.0
        else:
            radius_deg = float(radius.deg)
        try:
            table = _panstarrs_request(
                self._session, "dr2", "stack", ra=coord.ra.deg, dec=coord.dec.deg, radius=radius_deg
            )
        except RequestException as e:
            logging.warning(e)
            raise CatalogUnavailable(catalog=self)
        if len(table) == 0:
            raise NotFound
        df = table.to_pandas()
        df = df[df["primaryDetection"] == 1]
        df = df.groupby("objID", sort=False).apply(self.__apply_groups)
        df = df.reset_index()
        table = Table.from_pandas(df)
        return table

    def get_url(self, id, row=None):
        return f'{self._detection_url}?objID={row["objID"]}'

    def _table_to_light_curve(self, table):
        table = table[table["psfFlux"] > 0.0]

        # Pan-STARRS time is MJD in TAI (International Atomic Time) standard, we convert it to HMJD UTC
        # https://outerspace.stsci.edu/display/PANSTARRS/PS1+ForcedWarpMasked+table+fields
        coord = SkyCoord(ra=table["ra"], dec=table["dec"], unit="deg")
        time = Time(Time(table["obsTime"], format="mjd", scale="tai"), scale="utc")
        helio_time = time + time.light_travel_time(coord, "heliocentric", location=HALEAKALA)
        table["hmjd"] = helio_time.mjd

        table["mag"] = ABZPMAG_JY - 2.5 * np.log10(table["psfFlux"])
        table["magErr"] = LGE_25 * table["psfFluxErr"] / table["psfFlux"]

        return [
            {
                "oid": row["objID"],
                "mjd": row["hmjd"],
                "mag": row["mag"],
                "magerr": row["magErr"],
                "filter": f'ps_{self._band_ids[row["filterID"]]}',
            }
            for row in table
        ]

    def light_curve(self, id, row=None):
        self._raise_if_unavailable()
        try:
            table = _panstarrs_request(self._session, "dr2", "detection", objID=int(row["objID"]))
        except RequestException as e:
            logging.info(str(e))
            raise CatalogUnavailable(catalog=self)
        if len(table) == 0:
            raise NotFound
        return self._table_to_light_curve(table)

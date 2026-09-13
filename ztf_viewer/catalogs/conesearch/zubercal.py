from typing import ClassVar

import numpy as np
from astropy.table import Table
from nested_pandas import NestedFrame

from ztf_viewer.catalogs.conesearch._base import _BaseHatsQuery, _BaseLightCurveQuery

# Zubercal stores the error as an integer count of 1e-4 mag.
MAGERR_UNIT = 1e-4


class ZubercalQuery(_BaseHatsQuery, _BaseLightCurveQuery):
    """Zubercal, the ubercalibrated ZTF DR20 photometry.

    A row is one detection, and detections are keyed by the Pan-STARRS1 object they were matched
    to, so grouping by `objectid` is what makes a light curve out of them.
    """

    id_column = "objectid"
    _table_ra = "objra"
    _ra_unit = "deg"
    _table_dec = "objdec"
    columns: ClassVar[dict] = {
        "__link": "PS1 ID",
        "separation": "Separation, arcsec",
        "n_obs": "Number of detections",
    }

    _hats_url = "https://data.lsdb.io/hats/ztf_dr20/zubercal/zubercal"
    _hats_columns = ("objectid", "objra", "objdec", "mjd", "band", "mag", "magerr")

    def _table_from_rows(self, df: NestedFrame) -> Table:
        """One row per PS1 object, the detections matched to it packed into a light curve."""
        objects = NestedFrame.from_flat(
            self._observations(df),
            base_columns=["objra", "objdec"],
            nested_columns=["oid", "mjd", "mag", "magerr", "filter"],
            on="objectid",
            name="lightcurve",
        )
        objects["n_obs"] = objects["lightcurve"].len()

        table = Table.from_pandas(objects.drop(columns="lightcurve").reset_index())
        table["light_curve"] = objects["lightcurve"].to_numpy()
        return table

    def _observations(self, df: NestedFrame) -> NestedFrame:
        """Every usable detection of the cone, in time order, whichever object it belongs to."""
        obs = df.query("magerr > 0 and mag > 0 and mjd > 0")
        obs["oid"] = obs["objectid"]
        obs["magerr"] = obs["magerr"] * MAGERR_UNIT
        # Arrow string_view: pandas cannot concatenate it and the sort's take has no kernel for it
        obs["filter"] = np.char.add("zuber_", obs["band"].to_numpy(dtype=str))
        return obs.drop(columns="band").sort_values("mjd")

    def light_curve(self, id, row=None):
        """The detections `_table_from_rows` packed for this row."""
        return row["light_curve"].to_dict("records")

    def get_url(self, id, row=None):
        return f"https://catalogs.mast.stsci.edu/panstarrs/detections.html?objID={id}"

from typing import ClassVar

import numpy as np
from astropy.table import Table
from nested_pandas import NestedFrame

from ztf_viewer.catalogs.conesearch._base import _BaseHatsQuery, _BaseLightCurveQuery
from ztf_viewer.util import LGE_25

# BTJD is BJD - 2457000; the TDB-to-UTC difference is not corrected
BTJD_TO_MJD = 2457000.0 - 2400000.5

# Tmag of one electron per second: Tmag = 10 at 15000 e-/s (TESS Instrument Handbook).
TESS_ZP_MAG = 20.44


class TessLightCurveQuery(_BaseHatsQuery, _BaseLightCurveQuery):
    """TESS 2-minute cadence light curves.

    A row is one sector of one target, holding that sector's photometry packed into the
    `lightcurve` struct, so an object is the rows sharing a TIC ID.
    """

    id_column = "ticid"
    _table_ra = "ra_obj"
    _ra_unit = "deg"
    _table_dec = "dec_obj"
    columns: ClassVar[dict] = {
        "__link": "TIC ID",
        "separation": "Separation, arcsec",
        "n_obs": "Number of valid points",
    }

    _hats_url = "/tess/tess_lightcurve/tess_lightcurve"
    _hats_columns = (
        "ticid",
        "sector",
        "ra_obj",
        "dec_obj",
        "lightcurve.time",
        "lightcurve.sap_flux",
        "lightcurve.sap_flux_err",
        "lightcurve.quality",
    )

    def _table_from_rows(self, df: NestedFrame) -> Table:
        """One row per TIC, the cadences of all its sectors packed into a single light curve."""
        objects = NestedFrame.from_flat(
            self._observations(df),
            base_columns=["ra_obj", "dec_obj"],
            nested_columns=["oid", "mjd", "mag", "magerr", "filter", "sector"],
            on="ticid",
            name="lightcurve",
        )
        objects["n_obs"] = objects["lightcurve"].len()

        table = Table.from_pandas(objects.drop(columns="lightcurve").reset_index())
        table["light_curve"] = objects["lightcurve"].to_numpy()
        return table

    def _observations(self, df: NestedFrame) -> NestedFrame:
        """Every valid cadence of the cone as its own row, in time order.

        Exploding the nested column repeats the target's own columns onto each of its cadences,
        so the whole cone -- every TIC, every sector -- converts to magnitudes in one pass.
        """
        obs = df.query("lightcurve.quality == 0 and lightcurve.sap_flux > 0 and lightcurve.sap_flux_err > 0").explode(
            "lightcurve"
        )

        obs["oid"] = obs["ticid"]
        obs["mjd"] = obs["time"] + BTJD_TO_MJD
        obs["mag"] = TESS_ZP_MAG - 2.5 * np.log10(obs["sap_flux"])
        obs["magerr"] = LGE_25 * obs["sap_flux_err"] / obs["sap_flux"]
        obs["filter"] = "TESS"
        return obs.sort_values("mjd")

    async def find_closest(self, ra, dec, radius_arcsec, has_light_curve=True):
        """The longest light curve in the cone, not the nearest object."""
        table = await self.find(ra, dec, radius_arcsec)
        return table[np.argmax(table["n_obs"])]

    def light_curve(self, id, row=None):
        """The observations `_table_from_rows` packed for this row."""
        return row["light_curve"].to_dict("records")

    def get_url(self, id, row=None):
        return f"https://exofop.ipac.caltech.edu/tess/target.php?id={id}"

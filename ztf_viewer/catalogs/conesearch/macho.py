from typing import ClassVar

import pandas as pd
from astropy.table import Table
from nested_pandas import NestedFrame

from ztf_viewer.catalogs.conesearch._base import _BaseHatsQuery, _BaseLightCurveQuery

# m_AB - m_Vega for Bessell V and R, Blanton & Roweis 2007, Table 1
# https://ui.adsabs.harvard.edu/abs/2007AJ....133..734B
VEGA_TO_AB = {"V": 0.02, "R": 0.21}

# Cuts of varstar_view.magave_kv / magave_kr in the MACHO TAP schema (machotap.asvo.nci.org.au)
GOOD_TYPES = frozenset(range(1, 7)) | frozenset(range(21, 27))
MIN_INSTRUMENTAL_MAG = -12.0


class MachoQuery(_BaseHatsQuery, _BaseLightCurveQuery):
    """MACHO light curves, Kron-Cousins V and R converted to AB.

    A row is one star, its photometry packed into the `lc` struct with both bands sharing an epoch.
    """

    id_column = "starid"
    _name_column = "macho_id"
    _table_ra = "ra"
    _ra_unit = "deg"
    _table_dec = "dec"
    columns: ClassVar[dict] = {
        "__link": "MACHO ID",
        "separation": "Separation, arcsec",
        "n_obs": "Number of detections",
    }

    _hats_url = "/macho/macho"
    _hats_columns = (
        "starid",
        "fieldid",
        "tileid",
        "seqn",
        "ra",
        "dec",
        "lc.dateobs",
        "lc.bmag",
        "lc.berr",
        "lc.btype",
        "lc.kv",
        "lc.rmag",
        "lc.rerr",
        "lc.rtype",
        "lc.kr",
    )

    def _table_from_rows(self, df: NestedFrame) -> Table:
        """One row per star, its usable V and R detections packed into a light curve."""
        objects = NestedFrame.from_flat(
            self._observations(df),
            base_columns=["fieldid", "tileid", "seqn", "ra", "dec"],
            nested_columns=["oid", "mjd", "mag", "magerr", "filter"],
            on="starid",
            name="lightcurve",
        )
        objects["n_obs"] = objects["lightcurve"].len()
        objects["macho_id"] = [
            f"{field}.{tile}.{seqn}"
            for field, tile, seqn in zip(objects["fieldid"], objects["tileid"], objects["seqn"])
        ]

        table = Table.from_pandas(objects.drop(columns="lightcurve").reset_index())
        table["light_curve"] = objects["lightcurve"].to_numpy()
        return table

    def _observations(self, df: NestedFrame) -> NestedFrame:
        """Every usable detection of the cone in either band as its own row, in time order."""
        epochs = df.explode("lc")
        bands = [
            self._band(epochs, band="V", calibrated="kv", instrumental="bmag", err="berr", type_="btype"),
            self._band(epochs, band="R", calibrated="kr", instrumental="rmag", err="rerr", type_="rtype"),
        ]
        return pd.concat(bands).sort_values("mjd")

    @staticmethod
    def _band(epochs, *, band, calibrated, instrumental, err, type_):
        # The catalog nulls kv / kr / errors where MACHO's cut flag rejects the band
        good = (
            epochs[calibrated].notna()
            & (epochs[err] > 0)
            & epochs[type_].isin(GOOD_TYPES)
            & (epochs[instrumental] >= MIN_INSTRUMENTAL_MAG)
        )
        obs = epochs[good.fillna(False).astype(bool)]
        return NestedFrame(
            {
                "starid": obs["starid"],
                "fieldid": obs["fieldid"],
                "tileid": obs["tileid"],
                "seqn": obs["seqn"],
                "ra": obs["ra"],
                "dec": obs["dec"],
                "oid": obs["starid"],
                "mjd": obs["dateobs"],
                "mag": obs[calibrated] + VEGA_TO_AB[band],
                "magerr": obs[err],
                "filter": f"macho_{band}",
            }
        )

    def light_curve(self, id, row=None):
        """The detections `_table_from_rows` packed for this row."""
        return row["light_curve"].to_dict("records")

    def get_link(self, id, name, row=None):
        """MACHO has no per-star page to link to."""
        return name

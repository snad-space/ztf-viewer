from typing import ClassVar

import numpy as np
from astropy.table import Table
from nested_pandas import NestedFrame

from ztf_viewer.catalogs.conesearch._base import _BaseHatsQuery, _BaseLightCurveQuery

# The cuts DR4 makes for its master-table means: Source Extractor flags < 4 (4 and up are saturated,
# truncated or broken), fewer than 5 masked pixels, and not the worst of the three image qualities.
MAX_SEXTRACTOR_FLAGS = 3
MAX_NIMAFLAGS = 4
MAX_IMG_QUAL = 2


class SkyMapperDr4Query(_BaseHatsQuery, _BaseLightCurveQuery):
    """SkyMapper DR4 photometry, AB PSF magnitudes in uvgriz.

    A row is one master-table object, its detections packed into the `photometry` struct.
    """

    id_column = "object_id"
    _table_ra = "raj2000"
    _ra_unit = "deg"
    _table_dec = "dej2000"
    columns: ClassVar[dict] = {
        "__link": "SkyMapper DR4 ID",
        "separation": "Separation, arcsec",
        "n_obs": "Number of detections",
    }

    _hats_url = "/skymapper_dr4/skymapper_dr4"
    # Not the object-level `flags`: it would clash with `photometry.flags` once exploded
    _hats_columns = (
        "object_id",
        "raj2000",
        "dej2000",
        "photometry.date",
        "photometry.filter",
        "photometry.mag_psf",
        "photometry.e_mag_psf",
        "photometry.flags",
        "photometry.nimaflags",
        "photometry.img_qual",
    )

    def _table_from_rows(self, df: NestedFrame) -> Table:
        """One row per object, its usable detections packed into a light curve."""
        objects = NestedFrame.from_flat(
            self._observations(df),
            base_columns=["raj2000", "dej2000"],
            nested_columns=["oid", "mjd", "mag", "magerr", "filter"],
            on="object_id",
            name="lightcurve",
        )
        objects["n_obs"] = objects["lightcurve"].len()

        table = Table.from_pandas(objects.drop(columns="lightcurve").reset_index())
        table["light_curve"] = objects["lightcurve"].to_numpy()
        return table

    def _observations(self, df: NestedFrame) -> NestedFrame:
        """Every usable detection of the cone as its own row, in time order.

        Not `use_in_clipped == 1`: that also drops the detections clipped out of the mean
        magnitude, which for a variable are the very ones worth plotting.
        """
        obs = df.query(
            f"photometry.flags <= {MAX_SEXTRACTOR_FLAGS} and photometry.nimaflags <= {MAX_NIMAFLAGS}"
            f" and photometry.img_qual <= {MAX_IMG_QUAL} and photometry.e_mag_psf > 0"
        ).explode("photometry")
        obs = obs.dropna(subset=["mag_psf", "e_mag_psf"])

        obs["oid"] = obs["object_id"]
        # MJD at the start of an exposure of at most 100 s
        obs["mjd"] = obs["date"]
        obs["mag"] = obs["mag_psf"]
        obs["magerr"] = obs["e_mag_psf"]
        # Arrow string_view: pandas cannot concatenate it and a take has no kernel for it
        obs["filter"] = np.char.add("sm_", obs["filter"].to_numpy(dtype=str))
        return obs.sort_values("mjd")

    def light_curve(self, id, row=None):
        """The detections `_table_from_rows` packed for this row."""
        return row["light_curve"].to_dict("records")

    def get_url(self, id, row=None):
        return f"https://skymapper.anu.edu.au/object-viewer/dr4/{id}/"

import logging

from astropy.coordinates import SkyCoord, Angle
from astropy.time import Time
from astroquery.imcce import Skybot

from ztf_viewer.cache import cache
from ztf_viewer.exceptions import NotFound
from ztf_viewer.util import PALOMAR_OBS_CODE


class SkybotQuery:
    def __init__(self):
        self._query = Skybot()

    query_radius = Angle(120, "arcsec")
    """Radius to use for Skybot queries, results will be sub-sampled to the requested radius"""

    @cache()
    def find(self, ra, dec, observatory_mjd, radius_arcsec):
        logging.info(f"Querying Skybot ra={ra}, dec={dec}, mjd={observatory_mjd}, r={radius_arcsec}")
        coord = SkyCoord(ra, dec, unit="deg", frame="icrs")
        radius = Angle(radius_arcsec, "arcsec")
        if radius > self.query_radius:
            raise ValueError(f"Radius {radius} is too large, maximum is {self.query_radius}")
        try:
            table = self._query.cone_search(
                coord,
                # We've found that it is better to use a larger radius than required
                rad=Angle(120, "arcsec"),
                epoch=observatory_mjd,
                location=PALOMAR_OBS_CODE,
                find_planets=True,
                find_asteroids=True,
                find_comets=True,
            )
        except RuntimeError:
            raise NotFound("Skybot query failed")

        # Filter down to requested radius, but include some margin for error
        table = table[table["centerdist"] <= radius + 3.0 * table["posunc"]]

        if len(table) == 0:
            raise NotFound("Skybot query returned no results")

        table["__name"] = [row["Name"] or f"#{row['Number']}" for row in table]
        table["__separation"] = [
            f"{row['centerdist'].to_value('arcsec'):.02f}″±{row['posunc'].to_value('arcsec'):.02f}″" for row in table
        ]
        table["__delta_epoch"] = observatory_mjd - Time(table["epoch"], format="jd")
        return table


SKYBOT_QUERY = SkybotQuery()

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
        """Find Solar System objects near (ra, dec) at a given epoch.

        Parameters
        ----------
        observatory_mjd : float
            Modified Julian Date of the observation at the observatory
            (i.e. already corrected from heliocentric to geocentric time).
            Passed as a plain float so that the cache key is stable and
            serialisable regardless of the backend (memory or Redis).
        """
        logging.info(f"Querying Skybot ra={ra}, dec={dec}, mjd={observatory_mjd}, r={radius_arcsec}")
        coord = SkyCoord(ra, dec, unit="deg", frame="icrs")
        radius = Angle(radius_arcsec, "arcsec")
        if radius > self.query_radius:
            raise ValueError(f"Radius {radius} is too large, maximum is {self.query_radius}")
        epoch = Time(observatory_mjd, format="mjd")
        try:
            table = self._query.cone_search(
                coord,
                # We've found that it is better to use a larger radius than required
                rad=Angle(120, "arcsec"),
                epoch=epoch,
                location=PALOMAR_OBS_CODE,
                find_planets=True,
                find_asteroids=True,
                find_comets=True,
            )
        except (RuntimeError, ValueError):
            # RuntimeError: general Skybot failure
            # ValueError("No table found"): Skybot returned an error VOTable (e.g. invalid epoch)
            raise NotFound("Skybot query failed")

        # When Skybot returns zero rows, astroquery skips column renaming, so
        # "centerdist" / "posunc" are not present — check length first.
        if len(table) == 0:
            raise NotFound("Skybot query returned no results")

        # Filter down to requested radius, but include some margin for error
        table = table[table["centerdist"] <= radius + 3.0 * table["posunc"]]

        if len(table) == 0:
            raise NotFound("Skybot query returned no results")

        # Return plain dicts so the Redis LRU cache can pickle the result.
        # astropy QTable / MaskedColumn objects are not picklable.
        return [
            {
                "__name": row["Name"] or f"#{row['Number']}",
                "__separation": (
                    f"{row['centerdist'].to_value('arcsec'):.02f}″"
                    f"±{row['posunc'].to_value('arcsec'):.02f}″"
                ),
                "__delta_epoch": (epoch - Time(row["epoch"], format="jd")).to_value("day"),
                "__v_mag": float(row["V"]),
            }
            for row in table
        ]


SKYBOT_QUERY = SkybotQuery()

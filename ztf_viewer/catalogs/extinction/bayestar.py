import astropy.units as u

from ztf_viewer.catalogs.extinction._base import _BaseApiExtinctionQuery
from ztf_viewer.config import DUSTMAPS_API_URL


class BayestarQuery(_BaseApiExtinctionQuery):
    # Bayestar19 (Green et al. 2019), mode="best", 0.884 conversion factor already applied
    url = f"{DUSTMAPS_API_URL}/api/v1/bayestar2019"

    def ebv(self, coord):
        if not coord.distance.unit.is_equivalent(u.pc):
            raise ValueError("coord must include distance")
        icrs = coord.icrs
        return self.query({"ra": icrs.ra.deg, "dec": icrs.dec.deg, "distance": icrs.distance.to_value(u.pc)})


bayestar = BayestarQuery()

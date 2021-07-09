from functools import partial

import astropy.units as u
from dustmaps.bayestar import BayestarQuery as LocalQuery, BayestarWebQuery as WebQuery

from ztf_viewer.catalogs.extinction._base import _BaseLocalRemoteExtinctionQuery


class BayestarQuery(_BaseLocalRemoteExtinctionQuery):
    # We use best fit because it leads to much less memory usage
    # Median would be better
    def __init__(self):
        super().__init__()
        self._web_query = WebQuery()

    def web_query(self, coord):
        return self._web_query(coord, mode='best')

    def new_local_query(self):
        return partial(LocalQuery(max_samples=0), mode='best')

    def ebv(self, coord):
        if not coord.distance.unit.is_equivalent(u.pc):
            raise ValueError('coord must include distance')
        # http://argonaut.skymaps.info/usage
        return 0.884 * self.query(coord)


bayestar = BayestarQuery()

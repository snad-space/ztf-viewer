import logging
from collections import namedtuple

import numpy as np
from astropy.coordinates import SkyCoord
from astroquery.cds import cds
from astroquery.vizier import Vizier

from ztf_viewer.cache import cache
from ztf_viewer.exceptions import NotFound


class VizierCatalogDetails:
    @staticmethod
    @cache()
    def _query_cds(catalog_id):
        try:
            table = cds.find_datasets(f"ID=*{catalog_id}*")
        except np.ma.MaskError as e:
            logging.error(str(e))
            raise NotFound from e
        if len(table) == 0:
            raise NotFound
        return table[0]

    @staticmethod
    def description(catalog_id):
        result = VizierCatalogDetails._query_cds(catalog_id)
        if result is None:
            raise NotFound
        return result["obs_description"]


vizier_catalog_details = VizierCatalogDetails()


class FindVizier:
    FindVizierResult = namedtuple(
        "FindVizierResult",
        (
            "search_link",
            "table_list",
        ),
    )

    row_limit = 10

    _table_ra = "_RAJ2000"
    _table_dec = "_DEJ2000"
    _table_sep = "_r"

    def __init__(self):
        self._query = Vizier(columns=[self._table_ra, self._table_dec, self._table_sep])
        self._query.ROW_LIMIT = self.row_limit

    @cache()
    def find(self, ra, dec, radius_arcsec):
        coord = SkyCoord(ra, dec, unit="deg", frame="icrs")
        radius = f"{radius_arcsec}s"
        logging.info(f"Querying Vizier ra={ra}, dec={dec}, r={radius_arcsec}")
        table_list = self._query.query_region(coord, radius=radius)
        return table_list

    @staticmethod
    def get_search_url(ra, dec, radius_arcsec):
        return f"//vizier.u-strasbg.fr/viz-bin/VizieR-4?&-to=2&-from=-1&-this=-1&-out.add=_r&-out.add=_RAJ%2C_DEJ&-sort=_r&-order=I&-oc.form=sexa&-meta.foot=1&-meta=1&-meta.ucd=2&-c={ra}%2C+{dec}&-c.r=++{radius_arcsec}&-c.geom=r&-meta.ucd=2&-usenav=1&-bmark=POST&-out.max=50&-out.form=HTML+Table&-c.eq=J2000&-c.u=arcsec&-4c=Go%21"

    @staticmethod
    def get_catalog_url(catalog, ra, dec, radius_arcsec):
        return f"//vizier.u-strasbg.fr/viz-bin/VizieR-3?-source={catalog}&-c={ra},%20{dec}&-c.u=arcsec&-c.r={radius_arcsec}&-c.eq=J2000&-c.geom=r&-out.max=50&-out.form=HTML%20Table&-out.add=_r&-out.add=_RAJ,_DEJ&-sort=_r&-oc.form=sexa"


find_vizier = FindVizier()

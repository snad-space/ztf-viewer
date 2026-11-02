import asyncio
import json
import logging

logger = logging.getLogger(__name__)
from typing import ClassVar

import antares_client.search
from antares_client.exceptions import AntaresException
from antares_client.models import Locus
from astropy.coordinates import Angle, SkyCoord
from astropy.table import Table
from httpx import HTTPError

from ztf_viewer.cache import cache
from ztf_viewer.catalogs.conesearch._base import _BaseCatalogApiQuery, _BaseNameResolverQuery
from ztf_viewer.exceptions import CatalogUnavailable, NotFound


class AntaresQuery(_BaseCatalogApiQuery, _BaseNameResolverQuery):
    id_column = "locus_id"
    _table_ra = "ra"
    _ra_unit = "deg"
    _table_dec = "dec"
    columns: ClassVar[dict] = {
        "__link": "oid",
        "separation": "Separation, arcsec",
    }

    @cache()
    def query_region_loci(self, ra, dec, radius) -> list[Locus]:
        self._raise_if_unavailable()
        coord = SkyCoord(ra, dec, unit="deg")
        if not (isinstance(radius, str) and radius.endswith("s")):
            raise ValueError('radius argument should be strings that ends with "s" letter')
        radius = Angle(radius)
        try:
            loci = sorted(
                antares_client.search.cone_search(coord, radius), key=lambda locus: locus.coordinates.separation(coord)
            )
        # The client builds AntaresException from response.json(), so a non-JSON error page raises JSONDecodeError
        except (HTTPError, AntaresException, json.JSONDecodeError) as e:
            logger.warning(str(e))
            raise CatalogUnavailable(catalog=self)
        return loci

    def query_region_closest_locus(self, coord, radius) -> tuple[Angle, Locus]:
        loci = self.query_region_loci(coord.ra.deg, coord.dec.deg, radius)
        if len(loci) == 0:
            raise NotFound
        separations = [locus.coordinates.separation(coord) for locus in loci]
        sep, locus = min(zip(separations, loci), key=lambda x: x[0])
        return sep, locus

    def _query_region(self, coord, radius):
        loci = self.query_region_loci(coord.ra.deg, coord.dec.deg, radius)
        # It works better then Table(rows=...) for empty tables
        table = Table(
            {
                "locus_id": [locus.locus_id for locus in loci],
                "ra": [locus.ra for locus in loci],
                "dec": [locus.dec for locus in loci],
            }
        )
        # table = Table(rows=[(l.locus_id, l.ra, l.dec) for l in loci], names=('locus_id', 'ra', 'dec',))
        return table

    def get_url(self, id, row=None):
        return f"//antares.noirlab.edu/loci/{id}"

    def get_record_by_id(self, id) -> Locus:
        """ "id is something like ZTF18abqkqdm"""
        locus = antares_client.search.get_by_ztf_object_id(id)
        if locus is None:
            raise NotFound
        return locus

    @cache()
    async def resolve_name(self, id) -> SkyCoord:
        locus = await asyncio.to_thread(self.get_record_by_id, id)
        return locus.coordinates

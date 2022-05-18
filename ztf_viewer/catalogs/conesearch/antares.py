import antares_client.search
from antares_client.models import Locus
from astropy.coordinates import Angle, SkyCoord
from astropy.table import Table

from ztf_viewer.cache import cache
from ztf_viewer.catalogs.conesearch._base import _BaseCatalogApiQuery
from ztf_viewer.exceptions import NotFound


class AntaresQuery(_BaseCatalogApiQuery):
    id_column = 'locus_id'
    _table_ra = 'ra'
    _ra_unit = 'deg'
    _table_dec = 'dec'
    columns = {
        '__link': 'oid',
        'separation': 'Separation, arcsec',
    }

    @staticmethod
    @cache()
    def query_region_loci(ra, dec, radius) -> list[Locus]:
        coord = SkyCoord(ra, dec, unit='deg')
        if not (isinstance(radius, str) and radius.endswith('s')):
            raise ValueError('radius argument should be strings that ends with "s" letter')
        radius = Angle(radius)
        loci = sorted(antares_client.search.cone_search(coord, radius),
                      key=lambda locus: locus.coordinates.separation(coord))
        return loci

    @staticmethod
    def query_region_closest_locus(coord, radius) -> tuple[Angle, Locus]:
        loci = AntaresQuery.query_region_loci(coord.ra.deg, coord.dec.deg, radius)
        if len(loci) == 0:
            raise NotFound
        separations = [locus.coordinates.separation(coord) for locus in loci]
        sep, locus = min(zip(separations, loci), key=lambda x: x[0])
        return sep, locus

    def _query_region(self, coord, radius):
        loci = self.query_region_loci(coord.ra.deg, coord.dec.deg, radius)
        table = Table(rows=[(l.locus_id, l.ra, l.dec) for l in loci], names=('locus_id', 'ra', 'dec',))
        return table

    def get_url(self, id, row=None):
        return f'//antares.noirlab.edu/loci/{id}'

import logging

import antares_client.search
import numpy as np
from antares_client.models import Locus
from astropy.coordinates import Angle, SkyCoord
from astropy.table import Table
from requests import RequestException

from ztf_viewer.cache import cache
from ztf_viewer.catalogs.conesearch._base import _BaseCatalogApiQuery, _BaseLightCurveQuery
from ztf_viewer.exceptions import NotFound, CatalogUnavailable


class AntaresQuery(_BaseCatalogApiQuery, _BaseLightCurveQuery):
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
        try:
            loci = sorted(antares_client.search.cone_search(coord, radius),
                          key=lambda locus: locus.coordinates.separation(coord))
        except RequestException as e:
            logging.warning(str(e))
            raise CatalogUnavailable
        return loci

    def query_region_closest_locus(self, coord, radius) -> tuple[Angle, Locus]:
        loci = self.query_region_loci(coord.ra.deg, coord.dec.deg, radius)
        if len(loci) == 0:
            raise NotFound
        separations = [locus.coordinates.separation(coord) for locus in loci]
        sep, locus = min(zip(separations, loci), key=lambda x: x[0])
        return sep, locus

    @staticmethod
    def _locus_to_light_curve(locus):
        lc = locus.lightcurve[~np.isnan(locus.lightcurve['ant_mag'])]
        return [
            {
                'oid': locus.locus_id,
                'mjd': obs.ant_mjd,
                'mag': obs.ant_mag,
                'magerr': obs.ant_magerr,
                'filter': f"ant_{obs.ant_passband}",
            }
            for obs in lc.itertuples()
        ]

    @cache()
    def light_curve(self, id, row=None):
        locus = antares_client.search.get_by_id(id)
        if locus is None:
            raise NotFound
        return self._locus_to_light_curve(locus)

    def closest_light_curve(self, ra, dec, radius_arcsec, fail_on_empty=True, fail_on_unavailable=True):
        try:
            loci = self.query_region_loci(ra, dec, f'{radius_arcsec}s')
        except CatalogUnavailable:
            if fail_on_unavailable:
                raise
            return self._empty_light_curve()
        if len(loci) == 0:
            if fail_on_empty:
                raise NotFound
            return self._empty_light_curve()
        coord = SkyCoord(ra=ra, dec=dec, unit='deg')
        locus = min(loci, key=lambda locus: locus.coordinates.separation(coord))
        return self._locus_to_light_curve(locus)

    def _query_region(self, coord, radius):
        loci = self.query_region_loci(coord.ra.deg, coord.dec.deg, radius)
        # It works better then Table(rows=...) for empty tables
        table = Table(dict(locus_id=[l.locus_id for l in loci], ra=[l.ra for l in loci], dec=[l.dec for l in loci]))
        # table = Table(rows=[(l.locus_id, l.ra, l.dec) for l in loci], names=('locus_id', 'ra', 'dec',))
        return table

    def get_url(self, id, row=None):
        return f'//antares.noirlab.edu/loci/{id}'

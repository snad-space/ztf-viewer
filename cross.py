from functools import lru_cache, partial

from astropy.coordinates import SkyCoord
from astroquery.simbad import Simbad


simbad = Simbad()
simbad.cache_location = None
simbad.add_votable_fields('distance', 'fluxdata(R)', 'fluxdata(V)', 'otype', 'otypes', 'v*')


CACHE_SIZE = 1 << 10


def find_simbad(ra, dec, radius_arcmin=2):
    coord = SkyCoord(ra, dec, unit='deg', frame='icrs')
    radius = f'{radius_arcmin}m'
    table = simbad.query_region(coord, radius=radius)
    if table is None:
        return None
    catalog_coord = SkyCoord(table['RA'], table['DEC'], unit=['hour', 'deg'], frame='icrs')
    table['separation'] = coord.separation(catalog_coord).to('arcmin')
    return table

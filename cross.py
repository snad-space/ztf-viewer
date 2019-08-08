from functools import lru_cache
from time import sleep

import numpy as np
from astropy.coordinates import SkyCoord
# Dirty hack to overcome problem of simultaneous cache folder creation
while True:
    try:
        from astroquery.simbad import Simbad
        break
    except FileExistsError:
        sleep(np.random.uniform(0.05, 0.2))


simbad = Simbad()
# simbad.cache_location = None
simbad.add_votable_fields('distance', 'fluxdata(R)', 'fluxdata(V)', 'otype', 'otypes', 'v*')


CACHE_SIZE = 1 << 10


@lru_cache(maxsize=CACHE_SIZE)
def find_simbad(ra, dec, radius_arcsec=2):
    coord = SkyCoord(ra, dec, unit='deg', frame='icrs')
    radius = f'{radius_arcsec}s'
    table = simbad.query_region(coord, radius=radius)
    if table is None:
        return None
    catalog_coord = SkyCoord(table['RA'], table['DEC'], unit=['hour', 'deg'], frame='icrs')
    table['separation'] = coord.separation(catalog_coord).to('arcsec')
    return table

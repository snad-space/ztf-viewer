import urllib.parse
from functools import lru_cache
from time import sleep

import numpy as np
from astropy.coordinates import SkyCoord
# Dirty hack to overcome problem of simultaneous cache folder creation
while True:
    try:
        from astroquery.simbad import Simbad
        from astroquery.vizier import Vizier
        break
    except FileExistsError:
        sleep(np.random.uniform(0.05, 0.2))


simbad = Simbad()
simbad.add_votable_fields('distance', 'fluxdata(R)', 'fluxdata(V)', 'otype', 'otypes', 'v*')

gcvs = Vizier(
    columns=['GCVS', 'RAJ2000', 'DEJ2000', 'VarType', 'magMax', 'Period', 'SpType', 'VarTypeII', 'VarName', 'Simbad'],
)


CACHE_SIZE = 1 << 10


@lru_cache(maxsize=CACHE_SIZE)
def find_simbad(ra, dec, radius_arcsec):
    coord = SkyCoord(ra, dec, unit='deg', frame='icrs')
    radius = f'{radius_arcsec}s'
    table = simbad.query_region(coord, radius=radius)
    if table is None:
        return None
    catalog_coord = SkyCoord(table['RA'], table['DEC'], unit=['hour', 'deg'], frame='icrs')
    table['separation'] = coord.separation(catalog_coord).to('arcsec')
    return table


@lru_cache(maxsize=CACHE_SIZE)
def find_gcvs(ra, dec, radius_arcsec):
    coord = SkyCoord(ra, dec, unit='deg', frame='icrs')
    radius = f'{radius_arcsec}s'
    tables = gcvs.query_region(coord, radius=radius, catalog='B/gcvs/gcvs_cat')
    if not tables:
        return None
    table = tables[0]
    catalog_coord = SkyCoord(table['RAJ2000'], table['DEJ2000'], unit=['hour', 'deg'], frame='icrs')
    table['separation'] = coord.separation(catalog_coord)
    return table


def find(catalog, *args, **kwargs):
    if catalog.lower() == 'simbad':
        return find_simbad(*args, **kwargs)
    if catalog.lower() == 'gcvs':
        return find_gcvs(*args, **kwargs)
    raise NotImplemented(f'Search in catalog "{catalog}" is not implemented')


def object_url(catalog, id):
    if catalog.lower() == 'simbad':
        qid = urllib.parse.quote(id)
        return f'//simbad.u-strasbg.fr/simbad/sim-id?Ident={qid}'
    if catalog.lower() == 'gcvs':
        qid = urllib.parse.quote_plus(id)
        return f'http://www.sai.msu.su/gcvs/cgi-bin/search.cgi?search={qid}'
    raise NotImplemented(f'Object url is not implemented for {catalog}')


CATALOG_ID_COLUMN = {
    'simbad': 'MAIN_ID',
    'gcvs': 'GCVS',
}


def catalog_id_column(catalog):
    catalog = catalog.lower()
    return CATALOG_ID_COLUMN[catalog]

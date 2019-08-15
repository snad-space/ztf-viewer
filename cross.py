import urllib.parse
from functools import lru_cache, partial
from time import sleep

import numpy as np
from astropy.coordinates import SkyCoord
from astroquery.utils.commons import TableList
# Dirty hack to overcome problem of simultaneous cache folder creation
while True:
    try:
        from astroquery.simbad import Simbad
        from astroquery.vizier import Vizier
        break
    except FileExistsError:
        sleep(np.random.uniform(0.05, 0.2))


class _CatalogQuery:
    _cache_size = 1 << 10
    id_column = None
    _query_region = None
    _table_ra = None
    _table_dec = None
    columns = None

    @lru_cache(maxsize=_cache_size)
    def find(self, ra, dec, radius_arcsec):
        coord = SkyCoord(ra, dec, unit='deg', frame='icrs')
        radius = f'{radius_arcsec}s'
        table = self._query_region(coord, radius=radius)
        if table is None:
            return None
        if isinstance(table, TableList):
            if len(table) == 0:
                return None
            table = table[0]
        catalog_coord = SkyCoord(table[self._table_ra], table[self._table_dec], unit=['hour', 'deg'], frame='icrs')
        table['separation'] = coord.separation(catalog_coord).to('arcsec')
        return table

    def get_url(self, id):
        raise NotImplemented


class SimbadQuery(_CatalogQuery):
    id_column = 'MAIN_ID'
    _table_ra = 'RA'
    _table_dec = 'DEC'
    columns = {
        'url': 'MAIN_ID',
        'separation': 'Separation, arcsec',
        'OTYPE': 'Main type',
        'OTYPES': 'Other types',
        'V__vartyp': 'Variable type',
        'V__period': 'Period',
        'Distance_distance': 'Distance',
        'Distance_unit': 'Distance unit',
    }

    def __init__(self):
        self._query = Simbad()
        self._query.add_votable_fields('distance', 'fluxdata(R)', 'fluxdata(V)', 'otype', 'otypes', 'v*')
        self._query_region = self._query.query_region

    def get_url(self, id):
        qid = urllib.parse.quote(id)
        return f'//simbad.u-strasbg.fr/simbad/sim-id?Ident={qid}'


SIMBAD_QUERY = SimbadQuery()


class GCVSQuery(_CatalogQuery):
    id_column = 'GCVS'
    _table_ra = 'RAJ2000'
    _table_dec = 'DEJ2000'
    columns = {
        'url': 'Designation',
        'separation': 'Separation, arcsec',
        'Period': 'Period, days',
        'VarType': '<a href="http://cdsarc.u-strasbg.fr/viz-bin/getCatFile_Redirect/?-plus=-%2b&B/gcvs/./vartype.txt">Type of variability</a>',
        'SpType': 'Spectral type',
    }

    def __init__(self):
        self._query = Vizier(
            columns=['GCVS', 'RAJ2000', 'DEJ2000', 'VarType', 'magMax', 'Period', 'SpType', 'VarTypeII', 'VarName',
                     'Simbad'],
        )
        self._query_region = partial(self._query.query_region, catalog='B/gcvs/gcvs_cat')

    def get_url(self, id):
        qid = urllib.parse.quote_plus(id)
        return f'http://www.sai.msu.su/gcvs/cgi-bin/search.cgi?search={qid}'


GCVS_QUERY = GCVSQuery()


class VSXQuery(_CatalogQuery):
    id_column = 'OID'
    _table_ra = 'RAJ2000'
    _table_dec = 'DEJ2000'
    columns = {
        'url': 'Designation',
        'separation': 'Separation, arcsec',
        'Name': 'Name',
        'Period': 'Period, days',
        'Type': '<a href="https://aavso.org/vsx/help/VariableStarTypeDesignationsInVSX.pdf">Variability type</a>',
        'max': 'Maximum mag',
        'n_max': 'Band of max mag',
        'min': 'Minimum mag',
        'n_min': 'Band of min mag',
    }
    
    def __init__(self):
        self._query = Vizier()
        self._query_region = partial(self._query.query_region, catalog='B/vsx/vsx')

    def get_url(self, id):
        return f'//www.aavso.org/vsx/index.php?view=detail.top&oid={id}'


VSX_QUERY = VSXQuery()


def get_catalog_query(catalog):
    if catalog.lower() == 'simbad':
        return SIMBAD_QUERY
    if catalog.lower() == 'gcvs':
        return GCVS_QUERY
    if catalog.lower() == 'vsx':
        return VSX_QUERY
    raise

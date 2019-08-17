import logging
import urllib.parse
from base64 import b64encode
from collections import namedtuple
from functools import lru_cache, partial
from io import BytesIO
from time import sleep

import astropy.io.ascii
import numpy as np
import requests
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

from util import to_str, anchor_form


class _CatalogQuery:
    _cache_size = 1 << 5
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
        if len(table) == 0:
            return None
        catalog_coord = SkyCoord(table[self._table_ra], table[self._table_dec], unit=['hour', 'deg'], frame='icrs')
        table['separation'] = coord.separation(catalog_coord).to('arcsec')
        table['link'] = [self.get_link(row[self.id_column], to_str(row[self.id_column])) for row in table]
        return table

    def get_url(self, id):
        raise NotImplemented

    def get_link(self, id, name):
        return f'<a href="{self.get_url(id)}">{name}</a>'


class SimbadQuery(_CatalogQuery):
    id_column = 'MAIN_ID'
    _table_ra = 'RA'
    _table_dec = 'DEC'
    columns = {
        'link': 'MAIN_ID',
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
        'link': 'Designation',
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
        'link': 'Designation',
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


class OGLEQuery(_CatalogQuery):
    id_column = 'ID'
    _table_ra = 'RA'
    _table_dec = 'Decl'
    columns = {
        'link': 'Designation',
        'separation': 'Separation, arcsec',
        'light_curve': 'Light curve',
        'Type': 'Type',
        'Subtype': 'Subtype',
        'P_1': 'Period, days',
        'A_1': 'I-band amplitude, mag',
        'I': 'Mean I-magnitude',
        'V': 'Mean V-magnitude',
        'Remarks': 'Remarks',
    }
    _base_api_url = 'http://ogle3.snad.space/api/v1/circle'
    _base_light_curve_url = 'http://ogledb.astrouw.edu.pl/~ogle/CVS/images/'
    _post_url = 'http://ogledb.astrouw.edu.pl/~ogle/CVS/query.php?first=1&qtype=catalog'
    _post_data = {
        'db_target': 'all',
        'sort': 'id',
        'use_id': 'on',
        'disp_field': 'on',
        'disp_starid': 'on',
        'disp_type': '1',
        'disp_subtype': '1',
        'disp_ra': 'on',
        'disp_decl': 'on',
        'disp_i': 'on',
        'disp_v': 'on',
        'disp_p1': 'on',
        'disp_a1': 'on',
        'disp_id_ogle_ii': 'on',
        'disp_id_macho': 'on',
        'disp_id_asas': 'on',
        'disp_id_gcvs': 'on',
        'disp_id_other': 'on',
        'disp_remarks': 'on',
        'sorting': 'ASC',
        'hexout': 'on',
        'pagelen': '50',
    }

    def __init__(self):
        self._api_session = requests.Session()
        self._light_curve_session = requests.Session()

    def _get_api_url(self, query):
        parts = list(urllib.parse.urlparse(self._base_api_url))
        query = dict(urllib.parse.parse_qsl(parts[4]), **query)
        parts[4] = urllib.parse.urlencode(query)
        return urllib.parse.urlunparse(parts)

    def _download_light_curve(self, id):
        basepath = f'{id[-2:]}/{id}'
        paths = [basepath + '.png', basepath + '_1.png']
        light_curve_urls = [urllib.parse.urljoin(self._base_light_curve_url, path) for path in paths]
        for url in light_curve_urls:
            response = self._light_curve_session.get(url)
            if response.status_code == 200:
                data = b64encode(response.content).decode()
                return f'<a href="{url}"><img src="data:image/png;base64,{data}" width=200px /></a>'
        return ''

    def _query_region(self, coord, radius):
        ra = coord.ra.to_value('deg')
        dec = coord.dec.to_value('deg')
        if not (isinstance(radius, str) and radius.endswith('s')):
            raise ValueError('radius argument should be strings that ends with "s" letter')
        radius_arcsec = float(radius[:-1])
        query = {'ra': ra, 'dec': dec, 'radius_arcsec': radius_arcsec, 'format': 'tsv'}
        response = self._api_session.get(self._get_api_url(query))
        if response.status_code != 200:
            logging.warning(response.text)
            return None
        table = astropy.io.ascii.read(BytesIO(response.content), format='tab', guess=False)
        table['light_curve'] = [self._download_light_curve(row[self.id_column]) for row in table]
        return table

    def get_link(self, id, name):
        return anchor_form(self._post_url, dict(**self._post_data, val_id=id), name)


OGLE_QUERY = OGLEQuery()


#curl 'http://vizier.u-strasbg.fr/viz-bin/VizieR-4' \
#-XPOST \
#-H 'Content-Type: application/x-www-form-urlencoded' \
#-H 'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8' \
#-H 'Host: vizier.u-strasbg.fr' \
#-H 'Accept-Language: en-us' \
#-H 'Accept-Encoding: gzip, deflate' \
#-H 'Origin: http://vizier.u-strasbg.fr' \
#-H 'Referer: http://vizier.u-strasbg.fr/viz-bin/VizieR' \
#-H 'Content-Length: 306' \
#-H 'Upgrade-Insecure-Requests: 1' \
#-H 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/12.1.2 Safari/605.1.15' \
#-H 'Connection: keep-alive' \
#-H 'Cookie: _pk_id.5.f41c=11034d0adfb3b628.1565010803.9.1565980506.1565980180.; _pk_ses.5.f41c=1' \
#--data '-ref=VIZ5d56f7585b30&-to=2&-from=-1&-this=-1&-out.add=_r&-out.add=_RAJ%2C_DEJ&-sort=_r&-order=I&-oc.form=sexa&-meta.foot=1&-meta=1&-meta.ucd=2&-c=277.87862000000024%2C+-23.77108000000002&-c.r=++1&-c.geom=r&-meta.ucd=2&-usenav=1&-bmark=POST&-out.max=50&-out.form=HTML+Table&-c.eq=J2000&-c.u=arcsec&-4c=Go%21'

# http://vizier.u-strasbg.fr/viz-bin/VizieR-3?-source=I/252/out&-c=277.87862000000024,%20-23.77108000000002&-c.u=arcsec&-c.r=1.33&-c.eq=J2000&-c.geom=r&-out.max=50&-out.form=HTML%20Table&-out.add=_r&-out.add=_RAJ,_DEJ&-sort=_r&-oc.form=sexa
class FindVizier:
    FindVizierResult = namedtuple('FindVizierResult', ('search_link', 'table_list',))

    row_limit = 10
    _cache_size = 1 << 5

    _table_ra = '_RAJ2000'
    _table_dec = '_DEJ2000'
    _table_sep = '_r'

    def __init__(self):
        self._query = Vizier(columns=[self._table_ra, self._table_dec, self._table_sep])
        self._query.ROW_LIMIT = self.row_limit

    @lru_cache(maxsize=_cache_size)
    def find(self, ra, dec, radius_arcsec):
        coord = SkyCoord(ra, dec, unit='deg', frame='icrs')
        radius = f'{radius_arcsec}s'
        table_list = self._query.query_region(coord, radius=radius)
        return table_list

    def get_search_url(self, ra, dec, radius_arcsec):
        return f'//vizier.u-strasbg.fr/viz-bin/VizieR-4?&-to=2&-from=-1&-this=-1&-out.add=_r&-out.add=_RAJ%2C_DEJ&-sort=_r&-order=I&-oc.form=sexa&-meta.foot=1&-meta=1&-meta.ucd=2&-c={ra}%2C+{dec}&-c.r=++{radius_arcsec}&-c.geom=r&-meta.ucd=2&-usenav=1&-bmark=POST&-out.max=50&-out.form=HTML+Table&-c.eq=J2000&-c.u=arcsec&-4c=Go%21'

    def get_catalog_url(self, catalog, ra, dec, radius_arcsec):
        return f'//vizier.u-strasbg.fr/viz-bin/VizieR-3?-source={catalog}&-c={ra},%20{dec}&-c.u=arcsec&-c.r={radius_arcsec}&-c.eq=J2000&-c.geom=r&-out.max=50&-out.form=HTML%20Table&-out.add=_r&-out.add=_RAJ,_DEJ&-sort=_r&-oc.form=sexa'


find_vizier = FindVizier()


def get_catalog_query(catalog):
    if catalog.lower() == 'simbad':
        return SIMBAD_QUERY
    if catalog.lower() == 'gcvs':
        return GCVS_QUERY
    if catalog.lower() == 'vsx':
        return VSX_QUERY
    if catalog.lower() == 'ogle':
        return OGLE_QUERY
    raise

import json
import logging
import urllib.parse
from base64 import b64encode
from collections import namedtuple
from functools import partial
from io import BytesIO
from urllib.parse import urljoin, urlsplit, urlunsplit, urlencode

import astropy.io.ascii
import numpy as np
import pandas as pd
import requests
from astropy import units
from astropy.coordinates import SkyCoord
from astropy.cosmology import FlatLambdaCDM
from astropy.table import Table
from astroquery.cds import cds
from astroquery.simbad import Simbad
from astroquery.vizier import Vizier
from astroquery.utils.commons import TableList

from cache import cache
from config import LC_API_URL, TNS_API_URL, TNS_API_KEY
from util import to_str, anchor_form, INF, NotFound, CatalogUnavailable


COSMO = FlatLambdaCDM(H0=70, Om0=0.3)


class _CatalogQuery:
    __objects = {}

    id_column = None
    type_column = None
    period_column = None
    redshift_column = None
    _name_column = None
    _query_region = None
    _table_ra = None
    _ra_unit = None
    _table_dec = None
    columns = None

    def __new__(cls, query_name):
        name = cls._normalize_name(query_name)
        if name in cls.__objects:
            raise ValueError(f'Query name "{query_name}" already exists')
        obj = super().__new__(cls)
        cls.__objects[name] = obj
        return obj

    def __init__(self, query_name):
        self.__query_name = query_name

    @classmethod
    def get_objects(self):
        return self.__objects.copy()

    @staticmethod
    def _normalize_name(name):
        return name.replace(' ', '-').lower()

    @classmethod
    def get_object(cls, name):
        normalized_name = cls._normalize_name(name)
        return cls.__objects[normalized_name]

    @property
    def query_name(self):
        return self.__query_name

    @property
    def normalized_query_name(self):
        return self._normalize_name(self.query_name)

    @property
    def name_column(self):
        if self._name_column is not None:
            return self._name_column
        return self.id_column

    @cache()
    def find(self, ra, dec, radius_arcsec):
        coord = SkyCoord(ra, dec, unit='deg', frame='icrs')
        radius = f'{radius_arcsec}s'
        logging.info(f'Querying ra={ra}, dec={dec}, r={radius_arcsec}')
        table = self._query_region(coord, radius=radius)
        if table is None:
            raise NotFound
        if isinstance(table, TableList):
            if len(table) == 0:
                raise NotFound
            table = table[0]
        if len(table) == 0:
            raise NotFound
        catalog_coord = SkyCoord(
            table[self._table_ra], table[self._table_dec],
            unit=[self._ra_unit, 'deg'],
            frame='icrs'
        )
        table['separation'] = coord.separation(catalog_coord).to('arcsec')
        self.add_additional_columns(table)
        return table

    def add_additional_columns(self, table):
        self.add_objname_column(table)
        self.add_link_column(table)
        self.add_type_column(table)
        self.add_redshift_column(table)
        self.add_distance_column(table)

    def add_objname_column(self, table):
        table['__objname'] = [to_str(row[self.name_column]) for row in table]

    def add_link_column(self, table):
        table['__link'] = [self.get_link(row[self.id_column], row['__objname']) for row in table]

    def add_type_column(self, table):
        if self.type_column is not None:
            table['__type'] = [to_str(row[self.type_column]) for row in table]

    def add_period_column(self, table):
        if self.period_column is not None:
            table['__period'] = table[self.period_column]

    def add_redshift_column(self, table):
        if self.redshift_column is not None:
            table['__redshift'] = table[self.redshift_column]

    def add_distance_column(self, table):
        if '__redshift' in table.columns:
            table['__distance'] = [None if z is None else COSMO.luminosity_distance(z) for z in table['__redshift']]

    def get_url(self, id):
        raise NotImplemented

    def get_link(self, id, name):
        return f'<a href="{self.get_url(id)}">{name}</a>'


catalog_query_objects = _CatalogQuery.get_objects


class SimbadQuery(_CatalogQuery):
    id_column = 'MAIN_ID'
    type_column = 'OTYPE'
    period_column = 'V__period'
    _table_ra = 'RA'
    _ra_unit = 'hour'
    _table_dec = 'DEC'
    columns = {
        '__link': 'MAIN_ID',
        'separation': 'Separation, arcsec',
        'OTYPE': 'Main type',
        'OTYPES': 'Other types',
        'V__vartyp': 'Variable type',
        'V__period': 'Period',
        'Distance_distance': 'Distance',
        'Distance_unit': 'Distance unit',
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._query = Simbad()
        self._query.add_votable_fields('distance', 'fluxdata(R)', 'fluxdata(V)', 'otype', 'otypes', 'v*')
        self._query_region = self._query.query_region

    def get_url(self, id):
        qid = urllib.parse.quote(id)
        return f'//simbad.u-strasbg.fr/simbad/sim-id?Ident={qid}'

    def add_distance_column(self, table):
        table['__distance'] = table['Distance_distance'] * [units.Unit(u) for u in table['Distance_unit']]


SIMBAD_QUERY = SimbadQuery('Simbad')


class GCVSQuery(_CatalogQuery):
    id_column = 'GCVS'
    type_column = 'VarType'
    period_column = 'Period'
    _table_ra = 'RAJ2000'
    _ra_unit = 'hour'
    _table_dec = 'DEJ2000'
    columns = {
        '__link': 'Designation',
        'separation': 'Separation, arcsec',
        'Period': 'Period, days',
        'VarType': '<a href="http://cdsarc.u-strasbg.fr/viz-bin/getCatFile_Redirect/?-plus=-%2b&B/gcvs/./vartype.txt">Type of variability</a>',
        'SpType': 'Spectral type',
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._query = Vizier(
            columns=['GCVS', 'RAJ2000', 'DEJ2000', 'VarType', 'magMax', 'Period', 'SpType', 'VarTypeII', 'VarName',
                     'Simbad'],
        )
        self._query_region = partial(self._query.query_region, catalog='B/gcvs/gcvs_cat')

    def get_url(self, id):
        qid = urllib.parse.quote_plus(id)
        return f'http://www.sai.msu.su/gcvs/cgi-bin/search.cgi?search={qid}'


GCVS_QUERY = GCVSQuery('GCVS')


class VSXQuery(_CatalogQuery):
    id_column = 'OID'
    type_column = 'Type'
    period_column = 'Period'
    _table_ra = 'RAJ2000'
    _ra_unit = 'hour'
    _table_dec = 'DEJ2000'
    columns = {
        '__link': 'Designation',
        'separation': 'Separation, arcsec',
        'Name': 'Name',
        'Period': 'Period, days',
        'Type': '<a href="https://aavso.org/vsx/help/VariableStarTypeDesignationsInVSX.pdf">Variability type</a>',
        'max': 'Maximum mag',
        'n_max': 'Band of max mag',
        'min': 'Minimum mag',
        'n_min': 'Band of min mag',
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._query = Vizier()
        self._query_region = partial(self._query.query_region, catalog='B/vsx/vsx')

    def get_url(self, id):
        return f'//www.aavso.org/vsx/index.php?view=detail.top&oid={id}'


VSX_QUERY = VSXQuery('VSX')


class AtlasQuery(_CatalogQuery):
    id_column = 'ATOID'
    type_column = 'Class'
    period_column = 'fp-LSper'
    _table_ra = 'RAJ2000'
    _ra_unit = 'hour'
    _table_dec = 'DEJ2000'
    columns = {
        '__link': 'Name',
        'separation': 'Separation, arcsec',
        'fp-LSper': 'Period, days',
        'Class': 'Class',
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._query = Vizier(
            columns=['ATOID', 'RAJ2000', 'DEJ2000', 'fp-LSper', 'Class'],
        )
        self._query_region = partial(self._query.query_region, catalog='J/AJ/156/241/table4')

    def get_link(self, id, name):
        return name


ATLAS_QUERY = AtlasQuery('ATLAS')


class Gaia2Dis(_CatalogQuery):
    """Gaia DR2 distances from Bailer-Jones et al 2018

    Estimating Distance from Parallaxes. IV. Distances to 1.33 Billion Stars
    in Gaia Data Release 2
    https://ui.adsabs.harvard.edu/abs/2018AJ....156...58B
    """
    id_column = 'Source'
    _table_ra = 'RA_ICRS'
    _ra_unit = 'deg'
    _table_dec = 'DE_ICRS'
    columns = {
        '__link': 'Source ID',
        'separation': 'Separation, arcsec',
        'rest': 'Distance, pc',
        'b_rest': 'Lower bound of conf. interval, pc',
        'B_rest': 'Upper bound of conf. interval, pc',
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._query = Vizier(
            columns=['Source', 'RA_ICRS', 'DE_ICRS', 'rest', 'b_rest', 'B_rest', 'rlen', 'ResFlag', 'ModFlag'],
        )
        self._query_region = partial(self._query.query_region, catalog='I/347/gaia2dis')

    def get_url(self, id):
        return f'//vizier.u-strasbg.fr/viz-bin/VizieR-6?-out.form=%2bH&-source=I/347/gaia2dis&Source={id}'

    def add_distance_column(self, table):
        table['__distance'] = [x * units.pc for x in table['rest']]


GAIA2_DIS = Gaia2Dis('Gaia DR2 Distances')


class _ApiQuery(_CatalogQuery):
    @property
    def _base_api_url(self):
        raise NotImplemented

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._api_session = requests.Session()

    @staticmethod
    def _raise_if_not_ok(response):
        if response.status_code != 200:
            logging.warning(response.text)
            raise CatalogUnavailable(response.text)

    def _api_query_region(self, ra, dec, radius_arcsec):
        raise NotImplemented

    def _query_region(self, coord, radius):
        ra = coord.ra.to_value('deg')
        dec = coord.dec.to_value('deg')
        if not (isinstance(radius, str) and radius.endswith('s')):
            raise ValueError('radius argument should be strings that ends with "s" letter')
        radius_arcsec = float(radius[:-1])
        return self._api_query_region(ra, dec, radius_arcsec)

    def _get_api_url(self, query):
        query_string = urllib.parse.urlencode(query)
        return f'{self._base_api_url}?{query_string}'


class ZtfPeriodicQuery(_ApiQuery):
    id_column = 'SourceID'
    type_column = 'Type'
    period_column = 'Per'
    _name_column = 'ID'
    _table_ra = 'RAdeg'
    _ra_unit = 'deg'
    _table_dec = 'DEdeg'
    columns = {
        '__link': 'ZTF ID',
        'separation': 'Separation, arcsec',
        'Type': 'Type',
        'Per': 'Period, days',
        'Per_g': 'zg period, days',
        'Per_r': 'zr period, days',
        'Amp_g': 'zg amplitude',
        'Amp_r': 'zr amplitude',
    }
    _base_api_url = 'http://periodic.ztf.snad.space/api/v1/circle'

    def _api_query_region(self, ra, dec, radius_arcsec):
        query = {'ra': ra, 'dec': dec, 'radius_arcsec': radius_arcsec}
        response = self._api_session.get(self._get_api_url(query))
        self._raise_if_not_ok(response)
        j = response.json()
        table = Table.from_pandas(pd.DataFrame.from_records(j))
        return table

    def get_url(self, id):
        return f'http://variables.cn:88/lcz.php?SourceID={id}'


ZTF_PERIODIC_QUERY = ZtfPeriodicQuery('ZTF Periodic')


class TnsQuery(_ApiQuery):
    id_column = 'name'
    type_column = 'object_type'
    _name_column = 'fullname'
    _table_ra = 'radeg'
    _ra_unit = 'deg'
    _table_dec = 'decdeg'
    columns = {
        '__link': 'Name',
        'separation': 'Separation, arcsec',
        'discoverydate': 'Discovery date',
        'discoverymag': 'Discovery mag',
        'object_type': 'Type',
        'redshift': 'Redshift',
        'hostname': 'Host',
        'host_redshift': 'Host redshift',
        'internal_names': 'Internal names',
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._search_api_url = urllib.parse.urljoin(TNS_API_URL, '/api/get/search')
        self._object_api_url = urllib.parse.urljoin(TNS_API_URL, '/api/get/object')

    @staticmethod
    def _prepare_request_data(data=None):
        if TNS_API_KEY is None:
            raise CatalogUnavailable('TNS_API_KEY is not specified')
        prep = dict(api_key=(None, TNS_API_KEY))
        if data is not None:
            prep['data'] = (None, json.dumps(data))
        return prep

    def _reply(self, response):
        self._raise_if_not_ok(response)
        j = response.json()
        if j['id_code'] != 200:
            logging.warning(j['id_message'])
            raise CatalogUnavailable(j['id_message'])
        return j['data']['reply']

    def _get_search(self, ra, dec, radius_arcsec):
        data = dict(ra=ra, dec=dec, radius=radius_arcsec, units='arcsec')
        response = self._api_session.post(self._search_api_url, files=self._prepare_request_data(data))
        reply = self._reply(response)
        return [obj['objname'] for obj in reply]

    def _get_object(self, objname):
        data = dict(objname=objname, photometry=0, spectra=0)
        response = self._api_session.post(self._object_api_url, files=self._prepare_request_data(data))

        reply = self._reply(response)
        if not reply['public']:
            return None

        if isinstance(reply['object_type'], dict):
            reply['object_type'] = reply['object_type']['name']

        def flat(x):
            if isinstance(x, list) or isinstance(x, dict):
                return str(x)
            return x
        reply = {k: flat(v) for k, v in reply.items()}

        return reply

    def _api_query_region(self, ra, dec, radius_arcsec):
        objnames = self._get_search(ra, dec, radius_arcsec)
        objs = [obj for name in objnames if (obj := self._get_object(name))]
        table = Table.from_pandas(pd.DataFrame.from_records(objs))
        table['fullname'] = [f'{row["name_prefix"] or ""}{row["objname"]}' for row in table]
        return table

    def get_url(self, id):
        return f'//wis-tns.weizmann.ac.il/object/{id}'

    def add_redshift_column(self, table):
        table['__redshift'] = [row['redshift'] if row['redshift'] else row['host_redshift'] for row in table]


TNS_QUERY = TnsQuery('Transient Name Server')


class AstrocatsQuery(_ApiQuery):
    id_column = 'event'
    type_column = 'claimedtype'
    redshift_column = 'redshift'
    _table_ra = 'ra'
    _ra_unit = 'hour'
    _table_dec = 'dec'
    columns = {
        '__link': 'Event name',
        'separation': 'Separation, arcsec',
        'claimedtype': 'Claimed type',
        'stellarclass': 'Stellar class',
        'spectraltype': 'Spectral type',
        'redshift': 'Redshift',
        'host': 'Host',
        'references': 'References',
    }
    _base_api_url = 'https://api.astrocats.space/all'
    _base_astrocats_urls = {
        'SNE': 'https://sne.space/sne/',
        'TDE': 'https://tde.space/tde/',
        'KNE': 'https://kilonova.space/kne/',
        'HVS': 'https://faststars.space/hvs/',
    }

    def _api_query_region(self, ra, dec, radius_arcsec):
        query = {'ra': ra, 'dec': dec, 'radius': radius_arcsec, 'format': 'csv', 'item': 0}
        response = self._api_session.get(self._get_api_url(query))
        self._raise_if_not_ok(response)
        table = astropy.io.ascii.read(BytesIO(response.content), format='csv', guess=False)
        table['references'] = [', '.join(f'<a href=//adsabs.harvard.edu/abs/{r}>{r}</a>'
                                         for r in row['references'].split(','))
                               for row in table]
        return table

    def get_link(self, id, name):
        urls = {}
        for cat, base_url in self._base_astrocats_urls.items():
            url = urllib.parse.urljoin(base_url, id)
            urls[cat] = url
        link_list = ', '.join(f'<a href="{url}">{cat}</a>' for cat, url in urls.items())
        return f'{name}<br>{link_list}'


ASTROCATS_QUERY = AstrocatsQuery('Astrocats')


class OGLEQuery(_ApiQuery):
    id_column = 'ID'
    type_column = 'Type'
    period_column = 'P_1'
    _table_ra = 'RA'
    _ra_unit = 'hour'
    _table_dec = 'Decl'
    columns = {
        '__link': 'Designation',
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._light_curve_session = requests.Session()

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

    def _api_query_region(self, ra, dec, radius_arcsec):
        query = {'ra': ra, 'dec': dec, 'radius_arcsec': radius_arcsec, 'format': 'tsv'}
        response = self._api_session.get(self._get_api_url(query))
        self._raise_if_not_ok(response)
        table = astropy.io.ascii.read(BytesIO(response.content), format='tab', guess=False)
        table['light_curve'] = [self._download_light_curve(row[self.id_column]) for row in table]
        return table

    def get_link(self, id, name):
        return anchor_form(self._post_url, dict(**self._post_data, val_id=id), name)


OGLE_QUERY = OGLEQuery('OGLE')


def get_catalog_query(catalog):
    try:
        return _CatalogQuery.get_object(catalog)
    except KeyError as e:
        raise ValueError(f'No catalog query engine for catalog type "{catalog}"') from e


class VizierCatalogDetails:
    @staticmethod
    @cache()
    def _query_cds(catalog_id):
        try:
            table = cds.find_datasets(f'ID=*{catalog_id}*')
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
        return result['obs_description']


vizier_catalog_details = VizierCatalogDetails()


class FindVizier:
    FindVizierResult = namedtuple('FindVizierResult', ('search_link', 'table_list',))

    row_limit = 10

    _table_ra = '_RAJ2000'
    _table_dec = '_DEJ2000'
    _table_sep = '_r'

    def __init__(self):
        self._query = Vizier(columns=[self._table_ra, self._table_dec, self._table_sep])
        self._query.ROW_LIMIT = self.row_limit

    @cache()
    def find(self, ra, dec, radius_arcsec):
        coord = SkyCoord(ra, dec, unit='deg', frame='icrs')
        radius = f'{radius_arcsec}s'
        logging.info(f'Querying Vizier ra={ra}, dec={dec}, r={radius_arcsec}')
        table_list = self._query.query_region(coord, radius=radius)
        return table_list

    @staticmethod
    def get_search_url(ra, dec, radius_arcsec):
        return f'//vizier.u-strasbg.fr/viz-bin/VizieR-4?&-to=2&-from=-1&-this=-1&-out.add=_r&-out.add=_RAJ%2C_DEJ&-sort=_r&-order=I&-oc.form=sexa&-meta.foot=1&-meta=1&-meta.ucd=2&-c={ra}%2C+{dec}&-c.r=++{radius_arcsec}&-c.geom=r&-meta.ucd=2&-usenav=1&-bmark=POST&-out.max=50&-out.form=HTML+Table&-c.eq=J2000&-c.u=arcsec&-4c=Go%21'

    @staticmethod
    def get_catalog_url(catalog, ra, dec, radius_arcsec):
        return f'//vizier.u-strasbg.fr/viz-bin/VizieR-3?-source={catalog}&-c={ra},%20{dec}&-c.u=arcsec&-c.r={radius_arcsec}&-c.eq=J2000&-c.geom=r&-out.max=50&-out.form=HTML%20Table&-out.add=_r&-out.add=_RAJ,_DEJ&-sort=_r&-oc.form=sexa'


find_vizier = FindVizier()


class _BaseFindZTF:
    _base_api_url = urljoin(LC_API_URL, '/api/v3/')

    def __init__(self):
        self._api_session = requests.Session()

    def _api_url(self, dr):
        return urljoin(self._base_api_url, f'data/{dr}/')

    def find(self, *args, **kwargs):
        raise NotImplemented


class FindZTFOID(_BaseFindZTF):
    def __init__(self):
        super().__init__()

    def _oid_api_url(self, dr):
        return urljoin(self._api_url(dr), 'oid/full/json')

    def json_url(self, oid, dr):
        parts = list(urlsplit(self._oid_api_url(dr)))
        parts[3] = urlencode(self._query_dict(oid))
        return urlunsplit(parts)

    @staticmethod
    def _query_dict(oid):
        return dict(oid=oid)

    @cache()
    def find(self, oid, dr):
        resp = self._api_session.get(self._oid_api_url(dr), params=self._query_dict(oid))
        if resp.status_code != 200:
            message = f'{resp.url} returned {resp.status_code}: {resp.text}'
            logging.info(message)
            raise NotFound(message)
        return resp.json()[str(oid)]

    def get_coord(self, oid, dr):
        meta = self.get_meta(oid, dr)
        if meta is None:
            raise NotFound
        coord = meta['coord']
        return coord['ra'], coord['dec']

    def get_coord_string(self, oid, dr):
        try:
            ra, dec = self.get_coord(oid, dr)
        except TypeError as e:
            raise NotFound from e
        return f'{ra:.5f} {dec:.5f}'

    def get_meta(self, oid, dr):
        j = self.find(oid, dr)
        return j['meta']

    def get_lc(self, oid, dr, min_mjd=None, max_mjd=None):
        if min_mjd is None:
            min_mjd = -INF
        if max_mjd is None:
            max_mjd = INF
        j = self.find(oid, dr)
        lc = [obs.copy() for obs in j['lc'] if min_mjd <= obs['mjd'] <= max_mjd]
        return lc


find_ztf_oid = FindZTFOID()


class FindZTFCircle(_BaseFindZTF):
    def __init__(self):
        super().__init__()

    def _circle_api_url(self, dr):
        return urljoin(self._api_url(dr), 'circle/full/json')

    @cache()
    def find(self, ra, dec, radius_arcsec, dr):
        resp = self._api_session.get(
            self._circle_api_url(dr),
            params=dict(ra=ra, dec=dec, radius_arcsec=radius_arcsec),
        )
        if resp.status_code != 200:
            raise NotFound
        j = resp.json()
        coord = SkyCoord(ra, dec, unit='deg', frame='icrs')
        cat_coord = SkyCoord(ra=[obj['meta']['coord']['ra'] for obj in j.values()],
                             dec=[obj['meta']['coord']['dec'] for obj in j.values()],
                             unit='deg',
                             frame='icrs')
        sep = coord.separation(cat_coord).to_value('arcsec')
        for obj, r in zip(j.values(), sep):
            obj['separation'] = r
        return j


find_ztf_circle = FindZTFCircle()


class LightCurveFeatures:
    _base_api_url = 'http://features.lc.snad.space'

    def __init__(self):
        self._api_session = requests.Session()
        self._find_ztf_oid = find_ztf_oid

    @cache()
    def __call__(self, oid, dr, min_mjd=None, max_mjd=None):
        lc = find_ztf_oid.get_lc(oid, dr, min_mjd=min_mjd, max_mjd=max_mjd)
        light_curve = [dict(t=obs['mjd'], m=obs['mag'], err=obs['magerr']) for obs in lc]
        j = dict(light_curve=light_curve)
        resp = self._api_session.post(self._base_api_url, json=j)
        if resp.status_code != 200:
            raise NotFound
        return resp.json()


light_curve_features = LightCurveFeatures()

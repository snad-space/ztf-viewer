import logging
import urllib.parse

import pandas as pd
import requests
from astropy.coordinates import SkyCoord
from astropy.cosmology import FlatLambdaCDM
from astropy.table import Table
from astroquery.utils.commons import TableList

from ztf_viewer.cache import cache
from ztf_viewer.exceptions import NotFound, CatalogUnavailable
from ztf_viewer.util import to_str

COSMO = FlatLambdaCDM(H0=70, Om0=0.3)


class _BaseCatalogQuery:
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
        table.sort('separation')
        self.add_additional_columns(table)
        return table

    def add_additional_columns(self, table):
        self.add_objname_column(table)
        self.add_link_column(table)
        self.add_type_column(table)
        self.add_period_column(table)
        self.add_redshift_column(table)
        self.add_distance_column(table)

    def add_objname_column(self, table):
        table['__objname'] = [to_str(row[self.name_column]) for row in table]

    def add_link_column(self, table):
        table['__link'] = [self.get_link(row[self.id_column], row['__objname'], row=row) for row in table]

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

    def get_url(self, id, row=None):
        raise NotImplemented

    def get_link(self, id, name, row=None):
        return f'<a href="{self.get_url(id, row=row)}">{name}</a>'


class _BaseCatalogApiQuery(_BaseCatalogQuery):
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
        query = {'ra': ra, 'dec': dec, 'radius_arcsec': radius_arcsec}
        response = self._api_session.get(self._get_api_url(query))
        self._raise_if_not_ok(response)
        j = response.json()
        table = Table.from_pandas(pd.DataFrame.from_records(j))
        return table

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

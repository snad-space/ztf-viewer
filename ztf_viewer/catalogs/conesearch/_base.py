import dataclasses
import logging
import urllib.parse
from functools import partial
from typing import Dict, List, Optional

import pandas as pd
import requests
from astropy.coordinates import SkyCoord
from astropy.cosmology import FlatLambdaCDM
from astropy.table import Table
from astroquery.utils.commons import TableList
from astroquery.vizier import Vizier
from requests import RequestException

from ztf_viewer.cache import cache
from ztf_viewer.catalogs import find_ztf_oid, unavailable_catalogs
from ztf_viewer.exceptions import NotFound, CatalogUnavailable
from ztf_viewer.util import to_str, compose_plus_minus_expression

COSMO = FlatLambdaCDM(H0=70, Om0=0.3)


@dataclasses.dataclass
class ValueWithIntervalColumn:
    value: str
    lower: Optional[str] = None
    upper: Optional[str] = None
    name: Optional[str] = None
    float_decimal_digits: int = 3

    def __post_init__(self):
        if self.name is None:
            self.name = f'_{self.value}'
        if self.lower is None:
            self.lower = f'b_{self.value}'
        if self.upper is None:
            self.upper = f'B_{self.value}'

    def html(self, row) -> str:
        if not row[self.value] or not row[self.lower] or not row[self.upper]:
            return ''
        return compose_plus_minus_expression(
            row[self.value],
            row[self.lower],
            row[self.upper],
            float_decimal_digits=self.float_decimal_digits
        )


@dataclasses.dataclass
class ValueWithUncertaintyColumn:
    value: str
    uncertainty: Optional[str] = None
    name: Optional[str] = None
    float_decimal_digits: int = 3

    def __post_init__(self):
        if self.name is None:
            self.name = f'_{self.value}'
        if self.uncertainty is None:
            self.uncertainty = f'e_{self.value}'

    def html(self, row) -> str:
        if not row[self.value] or not row[self.uncertainty]:
            return ''
        return f'{to_str(row[self.value], float_decimal_digits=self.float_decimal_digits)}±{to_str(row[self.uncertainty], float_decimal_digits=self.float_decimal_digits)}'


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

    # classifier pretty name -> column name
    _prob_class_columns: Dict[str, str] = {}

    _value_with_interval_columns: List[ValueWithIntervalColumn] = []
    _value_wirh_uncertanty_columns: List[ValueWithUncertaintyColumn] = []

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

    def _raise_if_unavailable(self):
        if self.query_name in unavailable_catalogs:
            raise CatalogUnavailable(self.query_name, prolongate=False)

    @cache()
    def find(self, ra, dec, radius_arcsec):
        self._raise_if_unavailable()
        coord = SkyCoord(ra, dec, unit='deg', frame='icrs')
        radius = f'{radius_arcsec}s'
        logging.info(f'Querying ra={ra}, dec={dec}, r={radius_arcsec}')
        try:
            table = self._query_region(coord, radius=radius)
        except RequestException as e:  # this gives a good chance to catch network or service problem
            logging.warning(str(e))
            raise CatalogUnavailable(catalog=self)
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

    def find_closest(self, ra, dec, radius_arcsec, has_light_curve=True):
        table = self.find(ra, dec, radius_arcsec)
        return table[0]

    def add_additional_columns(self, table):
        self.add_objname_column(table)
        self.add_link_column(table)
        self.add_type_column(table)
        self.add_period_column(table)
        self.add_redshift_column(table)
        self.add_distance_column(table)
        self.add_prob_class_columns(table)
        self.add_value_interval_columns(table)
        self.add_value_uncertaincy_columns(table)

    def add_value_interval_columns(self, table):
        for x in self._value_with_interval_columns:
            table[x.name] = [x.html(row) for row in table]

    def add_value_uncertaincy_columns(self, table):
        for x in self._value_wirh_uncertanty_columns:
            table[x.name] = [x.html(row) for row in table]

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

    def add_prob_class_columns(self, table):
        """Assign column values to {'class': probability, ...}"""
        if len(self._prob_class_columns) != 0:
            raise NotImplemented

    def get_url(self, id, row=None):
        raise NotImplemented

    def get_link(self, id, name, row=None):
        return f'<a href="{self.get_url(id, row=row)}">{name}</a>'


class _BaseLightCurveQuery:
    def light_curve(self, id, row=None):
        raise NotImplemented

    @staticmethod
    def _empty_light_curve():
        return Table(dict.fromkeys(['oid', 'mjd', 'mag', 'magerr', 'filter'], []))

    def closest_light_curve(self, ra, dec, radius_arcsec, fail_on_empty=True, fail_on_unavailable=True):
        try:
            row = self.find_closest(ra, dec, radius_arcsec, has_light_curve=True)
            return self.light_curve(row[self.id_column], row=row)
        except NotFound:
            if fail_on_empty:
                raise
            return self._empty_light_curve()
        except CatalogUnavailable:
            if fail_on_unavailable:
                raise
            return self._empty_light_curve()

    def closest_light_curve_by_oid(self, oid, dr, radius_arcsec, fail_on_empty=True, fail_on_unavailable=True):
        ra, dec = find_ztf_oid.get_coord(oid, dr)
        return self.closest_light_curve(ra, dec, radius_arcsec, fail_on_empty=fail_on_empty,
                                        fail_on_unavailable=fail_on_unavailable)


class _BaseCatalogApiQuery(_BaseCatalogQuery):
    @property
    def _base_api_url(self):
        raise NotImplemented

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._api_session = requests.Session()

    def _raise_if_not_ok(self, response):
        if response.status_code != 200:
            logging.warning(response.text)
            raise CatalogUnavailable(response.text, catalog=self)

    def _api_query_region(self, ra, dec, radius_arcsec):
        query = {'ra': ra, 'dec': dec, 'radius_arcsec': radius_arcsec}
        response = self._api_session.get(self._get_api_url(query), timeout=10)
        self._raise_if_not_ok(response)
        j = response.json()
        table = Table.from_pandas(pd.DataFrame.from_records(j))
        return table

    def _query_region(self, coord, radius):
        ra = coord.ra.to_value('deg')
        dec = coord.dec.to_value('deg')
        if not (isinstance(radius, str) and radius.endswith('s')):
            raise ValueError('radius argument should be a string that ends with "s" letter')
        radius_arcsec = float(radius[:-1])
        return self._api_query_region(ra, dec, radius_arcsec)

    def _get_api_url(self, query):
        query_string = urllib.parse.urlencode(query)
        return f'{self._base_api_url}?{query_string}'


class _BaseVizierQuery(_BaseCatalogQuery):
    _table_ra = '_RAJ2000'
    _ra_unit = 'deg'
    _table_dec = '_DEJ2000'
    _vizier_columns = ['*']

    @property
    def _vizier_catalog(self) -> str:
        raise NotImplemented

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._query = Vizier(columns=['+_r', '_RAJ2000', '_DEJ2000'] + self._vizier_columns)
        self._query_region = partial(self._query.query_region, catalog=self._vizier_catalog)

    def get_url(self, id, row=None):
        id = to_str(id)
        id = urllib.parse.quote_plus(id)
        return f'//vizier.u-strasbg.fr/viz-bin/VizieR-6?-out.form=%2bH&-source={self._vizier_catalog}&{self.id_column}={id}'

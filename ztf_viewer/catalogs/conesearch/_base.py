import asyncio
import dataclasses
import inspect
import logging

logger = logging.getLogger(__name__)
import urllib.parse
from functools import partial
from typing import ClassVar

import httpx
import pandas as pd
from astropy.coordinates import SkyCoord
from astropy.cosmology import FlatLambdaCDM
from astropy.table import Table
from astroquery.utils.commons import TableList
from astroquery.vizier import Vizier
from requests import RequestException

from ztf_viewer.cache import cache
from ztf_viewer.catalogs import find_ztf_oid, unavailable_catalogs, unavailable_catalogs_async
from ztf_viewer.config import TIMEOUT_CONESEARCH_API
from ztf_viewer.exceptions import CatalogUnavailable, NotFound
from ztf_viewer.http import get_client
from ztf_viewer.rate_limit import AsyncCallQuota, AsyncRateLimiter, RateLimitTimeout
from ztf_viewer.util import async_timeout, compose_plus_minus_expression, safe_link, to_str

COSMO = FlatLambdaCDM(H0=70, Om0=0.3)


def _ensure_coroutine(func):
    """Wrap a sync callable in ``asyncio.to_thread``; pass an already-async one through unchanged.

    Lets ``find()`` await ``_query_region`` uniformly regardless of whether a given catalog's
    implementation is genuine async I/O or a still-sync third-party client (astroquery, an
    unconverted ``requests`` call).
    """
    if inspect.iscoroutinefunction(func):
        return func

    async def wrapper(*args, **kwargs):
        return await asyncio.to_thread(func, *args, **kwargs)

    return wrapper


@dataclasses.dataclass
class ValueWithIntervalColumn:
    value: str
    lower: str | None = None
    upper: str | None = None
    name: str | None = None
    float_decimal_digits: int = 3

    def __post_init__(self):
        if self.name is None:
            self.name = f"_{self.value}"
        if self.lower is None:
            self.lower = f"b_{self.value}"
        if self.upper is None:
            self.upper = f"B_{self.value}"

    def html(self, row) -> str:
        if not row[self.value] or not row[self.lower] or not row[self.upper]:
            return ""
        return compose_plus_minus_expression(
            row[self.value], row[self.lower], row[self.upper], float_decimal_digits=self.float_decimal_digits
        )


@dataclasses.dataclass
class ValueWithUncertaintyColumn:
    value: str
    uncertainty: str | None = None
    name: str | None = None
    float_decimal_digits: int = 3

    def __post_init__(self):
        if self.name is None:
            self.name = f"_{self.value}"
        if self.uncertainty is None:
            self.uncertainty = f"e_{self.value}"

    def html(self, row) -> str:
        if not row[self.value] or not row[self.uncertainty]:
            return ""
        value = to_str(row[self.value], float_decimal_digits=self.float_decimal_digits)
        err = to_str(row[self.uncertainty], float_decimal_digits=self.float_decimal_digits)
        return f"{value}±{err}"


class _BaseCatalogQuery:
    __objects: ClassVar[dict] = {}

    id_column = None
    type_column = None
    period_column = None
    redshift_column = None
    event_mjd_column = None
    _name_column = None
    _query_region = None
    _table_ra = None
    _ra_unit = None
    _table_dec = None
    columns = None

    # classifier pretty name -> column name
    _prob_class_columns: ClassVar[dict[str, str]] = {}

    _value_with_interval_columns: ClassVar[list[ValueWithIntervalColumn]] = []
    _value_with_uncertainty_columns: ClassVar[list[ValueWithUncertaintyColumn]] = []

    # Self-imposed cap on how often this catalog's upstream may be queried, or None where the
    # upstream publishes no policy. A pace (`AsyncRateLimiter`) or a budget (`AsyncCallQuota`),
    # whichever shape that upstream words its policy in; both are acquired the same way below.
    # Set on the subclass, so every instance of it -- in practice the single singleton in
    # `conesearch/__init__.py` -- shares one schedule. See `conesearch/simbad.py`,
    # `conesearch/colibri.py` and `ztf_viewer/rate_limit.py`.
    _rate_limiter: ClassVar[AsyncRateLimiter | AsyncCallQuota | None] = None

    # Column keys with pre-built HTML cell values (see html_from_astropy_table's html_columns).
    # Subclasses with extra HTML columns should extend this, e.g. `frozenset({"__link", "x"})`.
    _declared_html_columns: frozenset = frozenset({"__link"})

    @property
    def html_columns(self) -> frozenset:
        return self._declared_html_columns | {x.name for x in self._value_with_interval_columns}

    def __new__(cls, query_name):
        name = cls._normalize_name(query_name)
        if name in cls.__objects:
            raise ValueError(f'Query name "{query_name}" already exists')
        obj = super().__new__(cls)
        cls.__objects[name] = obj
        return obj

    def __init__(self, query_name):
        self.__query_name = query_name
        self._timeout_decorator = async_timeout(
            seconds=10.0,
            exception=CatalogUnavailable,
            exception_kwargs={"catalog": self},
        )

    @classmethod
    def get_objects(self):
        return self.__objects.copy()

    @staticmethod
    def _normalize_name(name):
        return name.replace(" ", "-").lower()

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

    def __cache_key__(self):
        """How ``@cache()`` identifies this object in the key of a cached method.

        ``ztf_viewer.cache.core.encode_self`` keys ``self`` on its class, which is what makes a
        cached method entry outlive the process that computed it.  These instances are the one
        place in the app where that is not enough: a subclass is constructed with a catalog
        name, so two instances of one class would be two different catalogs.
        """
        return self.normalized_query_name

    @property
    def name_column(self):
        if self._name_column is not None:
            return self._name_column
        return self.id_column

    def _raise_if_unavailable(self):
        if self.query_name in unavailable_catalogs:
            raise CatalogUnavailable(self.query_name, prolongate=False)

    async def _raise_if_unavailable_async(self):
        if await unavailable_catalogs_async.contains(self.query_name):
            raise CatalogUnavailable(self.query_name, prolongate=False)

    async def _wait_for_rate_limit(self):
        """Hold the caller until this catalog's self-imposed query rate allows another query.

        Called outside ``_timeout_decorator`` on purpose: that budget is for how long the
        upstream may take to answer, and time spent queueing here is not the upstream being
        slow. The limiter's own ``max_wait`` bounds this wait instead, and turns a queue too
        deep to be worth joining into a shed request rather than one that keeps a slot warm for
        a user who has already given up.
        """
        if self._rate_limiter is None:
            return
        try:
            wait = await self._rate_limiter.acquire()
        except RateLimitTimeout as e:
            # prolongate=False: this is us declining to send a query, so we have learned nothing
            # about the upstream's health -- the next request must be free to try it again.
            raise CatalogUnavailable(str(e), catalog=self, prolongate=False) from e
        if wait > 0:
            logger.info(f"Waited {wait:.2f}s for the {self.query_name} rate limit")

    @cache()
    async def find(self, ra, dec, radius_arcsec):
        await self._raise_if_unavailable_async()
        coord = SkyCoord(ra, dec, unit="deg", frame="icrs")
        radius = f"{radius_arcsec}s"
        logger.info(f"Querying ra={ra}, dec={dec}, r={radius_arcsec}")
        await self._wait_for_rate_limit()
        query_region = self._timeout_decorator(_ensure_coroutine(self._query_region))
        try:
            table = await query_region(coord, radius=radius)
        except (RequestException, httpx.HTTPError) as e:  # a good chance to catch network or service problems
            logger.warning(str(e))
            raise CatalogUnavailable(catalog=self)
        if table is None:
            raise NotFound
        if isinstance(table, TableList):
            if len(table) == 0:
                raise NotFound
            table = table[0]
        if len(table) == 0:
            raise NotFound
        await self.add_additional_columns(table)
        table["separation"] = coord.separation(table["__coord"]).to("arcsec")
        table.sort("separation")
        return table

    async def find_closest(self, ra, dec, radius_arcsec, has_light_curve=True):
        table = await self.find(ra, dec, radius_arcsec)
        return table[0]

    async def add_additional_columns(self, table):
        self.add_objname_column(table)
        self.add_coord_column(table)
        self.add_link_column(table)
        self.add_type_column(table)
        self.add_period_column(table)
        self.add_redshift_column(table)
        self.add_distance_column(table)
        self.add_event_mjd_column(table)
        await self.add_prob_class_columns(table)
        self.add_value_interval_columns(table)
        self.add_value_uncertaincy_columns(table)

    def add_value_interval_columns(self, table):
        for x in self._value_with_interval_columns:
            table[x.name] = [x.html(row) for row in table]

    def add_value_uncertaincy_columns(self, table):
        for x in self._value_with_uncertainty_columns:
            table[x.name] = [x.html(row) for row in table]

    def add_objname_column(self, table):
        table["__objname"] = [to_str(row[self.name_column]) for row in table]

    def _construct_coord(self, row_or_table) -> SkyCoord:
        return SkyCoord(
            row_or_table[self._table_ra],
            row_or_table[self._table_dec],
            unit=[self._ra_unit, "deg"],
            frame="icrs",
        )

    def add_coord_column(self, table):
        table["__coord"] = self._construct_coord(table)

    def add_link_column(self, table):
        table["__link"] = [self.get_link(row[self.id_column], row["__objname"], row=row) for row in table]

    def add_type_column(self, table):
        if self.type_column is not None:
            table["__type"] = [to_str(row[self.type_column]) for row in table]

    def add_period_column(self, table):
        if self.period_column is not None:
            table["__period"] = table[self.period_column]

    def add_redshift_column(self, table):
        if self.redshift_column is not None:
            table["__redshift"] = table[self.redshift_column]

    def add_distance_column(self, table):
        if "__redshift" in table.columns:
            table["__distance"] = [None if z is None else COSMO.luminosity_distance(z) for z in table["__redshift"]]

    def add_event_mjd_column(self, table):
        if self.event_mjd_column is not None:
            table["__event_mjd"] = table[self.event_mjd_column]

    async def add_prob_class_columns(self, table):
        """Assign column values to {'class': probability, ...}"""
        if len(self._prob_class_columns) != 0:
            raise NotImplementedError

    def get_url(self, id, row=None):
        raise NotImplementedError

    def get_link(self, id, name, row=None):
        return safe_link(self.get_url(id, row=row), name)


class _BaseLightCurveQuery:
    def light_curve(self, id, row=None):
        raise NotImplementedError

    @staticmethod
    def _empty_light_curve():
        return Table({key: [] for key in ["oid", "mjd", "mag", "magerr", "filter"]})

    async def closest_light_curve(self, ra, dec, radius_arcsec, fail_on_empty=True, fail_on_unavailable=True):
        try:
            row = await self.find_closest(ra, dec, radius_arcsec, has_light_curve=True)
            light_curve = _ensure_coroutine(self.light_curve)
            return await light_curve(row[self.id_column], row=row)
        except NotFound:
            if fail_on_empty:
                raise
            return self._empty_light_curve()
        except CatalogUnavailable:
            if fail_on_unavailable:
                raise
            return self._empty_light_curve()

    async def closest_light_curve_by_oid(self, oid, dr, radius_arcsec, fail_on_empty=True, fail_on_unavailable=True):
        ra, dec = await find_ztf_oid.get_coord(oid, dr)
        closest_light_curve = _ensure_coroutine(self.closest_light_curve)
        return await closest_light_curve(
            ra, dec, radius_arcsec, fail_on_empty=fail_on_empty, fail_on_unavailable=fail_on_unavailable
        )


class _BaseNameResolverQuery:
    def get_record_by_id(self, id):
        raise NotImplementedError

    @cache()
    async def resolve_name(self, id) -> SkyCoord:
        get_record_by_id = _ensure_coroutine(self.get_record_by_id)
        obj = await get_record_by_id(id)
        return self._construct_coord(obj)


class _BaseCatalogApiQuery(_BaseCatalogQuery):
    @property
    def _base_api_url(self):
        raise NotImplementedError

    def _raise_if_not_ok(self, response):
        if response.status_code != 200:
            logger.warning(response.text)
            raise CatalogUnavailable(response.text, catalog=self)

    async def _api_query_region(self, ra, dec, radius_arcsec):
        query = {"ra": ra, "dec": dec, "radius_arcsec": radius_arcsec}
        response = await get_client().get(self._get_api_url(query), timeout=TIMEOUT_CONESEARCH_API)
        self._raise_if_not_ok(response)
        j = response.json()
        table = Table.from_pandas(pd.DataFrame.from_records(j))
        return table

    async def _query_region(self, coord, radius):
        ra = coord.ra.to_value("deg")
        dec = coord.dec.to_value("deg")
        if not (isinstance(radius, str) and radius.endswith("s")):
            raise ValueError('radius argument should be a string that ends with "s" letter')
        radius_arcsec = float(radius[:-1])
        return await self._api_query_region(ra, dec, radius_arcsec)

    def _get_api_url(self, query):
        query_string = urllib.parse.urlencode(query)
        return f"{self._base_api_url}?{query_string}"


class _BaseVizierQuery(_BaseCatalogQuery):
    _table_ra = "_RAJ2000"
    _ra_unit = "deg"
    _table_dec = "_DEJ2000"
    _vizier_columns: ClassVar[list] = ["*"]

    @property
    def _vizier_catalog(self) -> str:
        raise NotImplementedError

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._query = Vizier(columns=["+_r", "_RAJ2000", "_DEJ2000"] + self._vizier_columns)
        self._query_region = partial(self._query.query_region, catalog=self._vizier_catalog)

    def get_url(self, id, row=None):
        id = to_str(id)
        id = urllib.parse.quote_plus(id)
        source_param = f"-source={self._vizier_catalog}"
        id_param = f"{self.id_column}={id}"
        return f"//vizier.u-strasbg.fr/viz-bin/VizieR-6?-out.form=%2bH&{source_param}&{id_param}"

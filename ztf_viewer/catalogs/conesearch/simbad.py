import logging
import threading
import urllib.parse
from typing import ClassVar

import numpy as np
from astropy import units
from astropy.table import hstack, vstack
from astroquery.simbad import Simbad
from cachetools import TTLCache
from pyvo.dal import DALFormatError, DALServiceError
from requests import RequestException
from requests.adapters import HTTPAdapter

from ztf_viewer.catalogs.conesearch._base import _BaseCatalogQuery
from ztf_viewer.config import (
    SIMBAD_MAX_QUERIES_PER_SECOND,
    SIMBAD_RATE_LIMIT_MAX_WAIT,
    SIMBAD_SERVER_DOWN_TTL,
    SIMBAD_SERVER_TIMEOUT,
    SIMBAD_SERVERS,
)
from ztf_viewer.rate_limit import AsyncRateLimiter

logger = logging.getLogger(__name__)


class SimbadUnavailable(RequestException):
    """No SIMBAD host answered; a RequestException so `find()` reports the catalog unavailable."""


class _DefaultTimeoutAdapter(HTTPAdapter):
    """pyvo sends SIMBAD's TAP requests with no timeout, so a hung host would never fail over."""

    def send(self, request, timeout=None, **kwargs):
        return super().send(request, timeout=SIMBAD_SERVER_TIMEOUT if timeout is None else timeout, **kwargs)


class SimbadServers:
    """SIMBAD hosts, main first; a host that failed is skipped for a while."""

    def __init__(self, servers=SIMBAD_SERVERS, down_ttl=SIMBAD_SERVER_DOWN_TTL):
        self.servers = servers
        self._down = TTLCache(maxsize=len(self.servers), ttl=down_ttl)
        # find() runs queries in worker threads, and TTLCache is not thread-safe.
        self._lock = threading.Lock()

    def available(self):
        """Hosts to try in order; when every one is down, all of them rather than none."""
        with self._lock:
            up = [server for server in self.servers if server not in self._down]
        return up or list(self.servers)

    def call(self, func):
        """``func(server)`` on each available host until one answers."""
        for server in self.available():
            try:
                return func(server)
            # pyvo wraps transport errors in these, and a read timeout mid-body in DALFormatError
            except (OSError, DALServiceError, DALFormatError) as e:
                error = e
            logger.warning(f"SIMBAD host {server} failed: {error}")
            with self._lock:
                self._down[server] = None
        raise SimbadUnavailable(f"No SIMBAD host answered, last error: {error}") from error


class SimbadQuery(_BaseCatalogQuery):
    # SIMBAD asks for no more than 8 queries in the same second and temporarily blacklists
    # clients that ignore it. astroquery will not hold us back, so `find()` waits here before
    # every uncached query (issue #51).
    _rate_limiter: ClassVar[AsyncRateLimiter] = AsyncRateLimiter(
        max_calls=SIMBAD_MAX_QUERIES_PER_SECOND,
        period=1.0,
        max_wait=SIMBAD_RATE_LIMIT_MAX_WAIT,
    )
    # Up to a full per-host timeout on a hung main host, then the same again for the mirror.
    _query_timeout_seconds: ClassVar[float] = 2 * sum(SIMBAD_SERVER_TIMEOUT)

    id_column = "main_id"
    type_column = "otype"
    period_column = "mesvar.period"
    # astroquery >=0.4.8 returns SIMBAD's TAP column names, so coordinates come back as `ra`/`dec`
    # in degrees. They were `RA`/`DEC` in hours until then, which is what this class asked for.
    _table_ra = "ra"
    _ra_unit = "deg"
    _table_dec = "dec"
    columns: ClassVar[dict] = {
        "__link": "main_id",
        "separation": "Separation, arcsec",
        "otype": "Main type",
        "__otypes": "Other types",
        "mesvar.vartyp": "Variable type",
        "mesvar.period": "Period, days",
        "mesdistance.dist": "Distance",
        "mesdistance.unit": "Distance unit",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._servers = SimbadServers()
        self._clients = {}

    def _client(self, server):
        # add_votable_fields validates the field names against SIMBAD's TAP schema over the
        # network, so build the client on first query instead of at import. find() reaches this
        # through _ensure_coroutine, so the build runs in a worker thread, not on the loop.
        if server not in self._clients:
            query = Simbad()
            query.server = server
            query._session.mount("https://", _DefaultTimeoutAdapter())
            query.add_votable_fields("mesdistance", "R", "V", "otype", "otypes", "mesVar")
            self._clients[server] = query
        return self._clients[server]

    def _query_region(self, coord, radius=None):
        table = self._servers.call(lambda server: self._client(server).query_region(coord, radius=radius))
        return self._one_row_per_object(table)

    @classmethod
    def _one_row_per_object(cls, table):
        """Collapse SIMBAD's one-row-per-measurement answer down to one row per object.

        ``otypes``, ``mesdistance`` and ``mesVar`` are one-to-many tables, and SIMBAD returns
        their cross product: a 5″ cone search on RR Lyr comes back as 48 rows for that one star
        (8 object types × 2 distances × 3 variability measurements), which the cross-match table
        would draw as 48 near-identical lines and the summary would count as 48 matches.

        Each ``mes*`` table ranks its own rows in ``mespos``, 1 being the measurement SIMBAD
        prefers, and the rows do not arrive in that order — so every group picks its own
        preferred row instead of the whole object inheriting whichever row came back first.
        """
        if table is None or len(table) == 0:
            return table

        # Column names are `<votable field>.<column>` for the one-to-many tables and bare for
        # `basic`, which is the same for every row of an object.
        basic_columns = [name for name in table.colnames if "." not in name]
        prefixes = dict.fromkeys(name.split(".", 1)[0] for name in table.colnames if "." in name)
        grouped_columns = {
            prefix: [name for name in table.colnames if name.startswith(f"{prefix}.")] for prefix in prefixes
        }

        rows = []
        other_types = []
        for group in table.group_by(cls.id_column).groups:
            pieces = [group[basic_columns][:1]]
            for prefix, columns in grouped_columns.items():
                index = cls._preferred_row(group, prefix)
                # A one-row slice rather than an element-by-element copy, so each column keeps
                # its own dtype, unit and mask however astroquery built it.
                pieces.append(group[columns][index : index + 1])
            rows.append(hstack(pieces, metadata_conflicts="silent"))
            other_types.append(cls._other_types(group))

        collapsed = vstack(rows, metadata_conflicts="silent")
        collapsed["__otypes"] = other_types
        return collapsed

    @staticmethod
    def _preferred_row(group, prefix):
        """Index of the row holding ``prefix``'s preferred measurement, ``mespos`` 1 being it.

        ``otypes`` carries no ``mespos`` — every row of it is equally valid, and
        :meth:`_other_types` keeps all of them anyway — so its first row will do.
        """
        mespos = f"{prefix}.mespos"
        if mespos not in group.colnames:
            return 0
        ranks = group[mespos]
        if np.all(np.ma.getmaskarray(ranks)):
            # The object has no rows in this table at all; SIMBAD left-joined nulls instead.
            return 0
        return int(np.ma.argmin(ranks))

    @staticmethod
    def _other_types(group):
        """SIMBAD's full list of object types for one object, as one cell.

        The list is what the "Other types" column showed before astroquery started returning
        `otypes` as its own table, one row per type.
        """
        if "otypes.otype" not in group.colnames:
            return ""
        values = (str(value).strip() for value in group["otypes.otype"] if not np.ma.is_masked(value))
        # dict, not set: SIMBAD returns the types in a stable order worth keeping.
        return ", ".join(dict.fromkeys(value for value in values if value))

    def get_url(self, id, row=None):
        qid = urllib.parse.quote(id)
        return f"//simbad.u-strasbg.fr/simbad/sim-id?Ident={qid}"

    def add_distance_column(self, table):
        # Most objects have no distance measurement, and the unit is per row (pc, kpc or Mpc),
        # so this cannot be a single Quantity column over the whole table.
        distances = []
        for row in table:
            distance, unit = row["mesdistance.dist"], row["mesdistance.unit"]
            if np.ma.is_masked(distance) or np.ma.is_masked(unit):
                distances.append(None)
            else:
                distances.append(distance * units.Unit(unit))
        table["__distance"] = distances

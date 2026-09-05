import urllib.parse
from typing import ClassVar

from astropy import units
from astroquery.simbad import Simbad

from ztf_viewer.catalogs.conesearch._base import _BaseCatalogQuery
from ztf_viewer.config import SIMBAD_MAX_QUERIES_PER_SECOND, SIMBAD_RATE_LIMIT_MAX_WAIT
from ztf_viewer.rate_limit import AsyncRateLimiter


class SimbadQuery(_BaseCatalogQuery):
    # SIMBAD blacklists clients that query it more than 8 times in the same second. astroquery
    # will not hold us back, so `find()` waits here before every uncached query (issue #51).
    _rate_limiter: ClassVar[AsyncRateLimiter] = AsyncRateLimiter(
        max_calls=SIMBAD_MAX_QUERIES_PER_SECOND,
        period=1.0,
        max_wait=SIMBAD_RATE_LIMIT_MAX_WAIT,
    )

    id_column = "main_id"
    type_column = "otype"
    _table_ra = "RA"
    _ra_unit = "hour"
    _table_dec = "DEC"
    columns: ClassVar[dict] = {
        "__link": "main_id",
        "separation": "Separation, arcsec",
        "otype": "Main type",
        "otype2": "Other type",
        "mesotype.otype": "Variable type",
        "mesdistance.dist": "Distance",
        "mesdistance.unit": "Distance unit",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._query = None

    def _query_region(self, coord, radius=None):
        # add_votable_fields validates the field names against SIMBAD's TAP schema over the
        # network, so build the client on first query instead of at import. find() reaches this
        # through _ensure_coroutine, so the build runs in a worker thread, not on the loop.
        if self._query is None:
            query = Simbad()
            query.add_votable_fields("mesdistance", "R", "V", "otype", "otypes")
            self._query = query
        return self._query.query_region(coord, radius=radius)

    def get_url(self, id, row=None):
        qid = urllib.parse.quote(id)
        return f"//simbad.u-strasbg.fr/simbad/sim-id?Ident={qid}"

    def add_distance_column(self, table):
        table["__distance"] = table["mesdistance.dist"] * [units.Unit(u) for u in table["mesdistance.unit"]]

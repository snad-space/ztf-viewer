import email.utils
import importlib.resources
from datetime import UTC, datetime, timedelta
from io import BytesIO

import httpx
from astropy.coordinates import Angle, SkyCoord
from astropy.io import ascii

from ztf_viewer import config
from ztf_viewer.cache.single_flight import AsyncSingleFlight
from ztf_viewer.catalogs.snad import data
from ztf_viewer.exceptions import NotFound
from ztf_viewer.http import get_client


class _SnadCatalog:
    url = "https://snad.space/catalog/snad_catalog.csv"

    def __init__(self, interval_seconds=600, failure_retry_seconds=60):
        self.check_interval = timedelta(seconds=interval_seconds)
        self.failure_retry_interval = timedelta(seconds=failure_retry_seconds)

        with importlib.resources.open_binary(data, "snad_catalog.csv") as fh:
            self.table = self._create_table(fh)

        self.updated_at = datetime(1900, 1, 1, 1, 1, tzinfo=UTC)
        self._failed_at = None
        # Coalesces concurrent refreshes into one download; AsyncSingleFlight is already
        # per-loop internally, so this instance is safe to share across loops.
        self._single_flight = AsyncSingleFlight()

    @staticmethod
    def _create_table(src):
        table = ascii.read(src, format="csv")
        table["coord"] = SkyCoord(ra=table["R.A."], dec=table["Dec."], unit="deg")
        table.add_index("Name")
        return table

    @staticmethod
    def _last_modified(resp):
        s = resp.headers["last-modified"]
        parsed = email.utils.parsedate(s)
        dt = datetime(*parsed[:7], tzinfo=UTC)
        return dt

    async def _update(self):
        now = datetime.now(tz=UTC)
        if now - self.updated_at < self.check_interval:
            return
        if self._failed_at is not None and now - self._failed_at < self.failure_retry_interval:
            return
        await self._single_flight.run("update", lambda: self._fetch(now))

    async def _fetch(self, now):
        client = get_client()
        try:
            resp = await client.get(self.url, timeout=config.TIMEOUT_SNAD)
        except httpx.HTTPError:
            self._failed_at = now
            return
        if resp.status_code != 200:
            self._failed_at = now
            return
        self._failed_at = None
        if self.updated_at > self._last_modified(resp):
            # Already current: not a failure, just nothing new to fetch.
            self.updated_at = now
            return
        self.updated_at = now
        self.table = self._create_table(BytesIO(resp.content))

    async def __call__(self):
        await self._update()
        return self.table.copy()

    async def search_region(self, ra, dec, radius_arcsec):
        await self._update()
        coord = SkyCoord(ra=ra, dec=dec, unit="deg")
        radius = Angle(radius_arcsec, unit="arcsec")
        idx, sep, _ = coord.match_to_catalog_sky(self.table["coord"])
        if sep > radius:
            raise NotFound
        return self.table["Name"][idx]


snad_catalog = _SnadCatalog()


class SnadCatalogSource:
    def __init__(self, row):
        self.row = row

    @classmethod
    async def create(cls, name):
        if isinstance(name, int) or not name.upper().startswith("SNAD"):
            name = f"SNAD{name}"
        name = name.upper()
        catalog = await snad_catalog()
        row = catalog.loc[name]
        return cls(row)

    @property
    def coord(self):
        return self.row["coord"]

    @property
    def ztf_oid(self):
        return int(self.row["OID"])

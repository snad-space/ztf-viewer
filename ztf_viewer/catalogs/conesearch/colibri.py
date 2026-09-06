"""Astro-COLIBRI cone search.

Astro-COLIBRI restricts its documented ``POST /cone_search`` to registered users and meters it
at 100 requests per day per account (issue #421,
https://forum.astro-colibri.science/t/upcoming-api-access-restrictions/169). Working with that
policy takes both halves: identifying ourselves with a ``uid`` so the calls are attributed to an
account that is allowed to make them, and holding ourselves to the allowance that account gets.

Both halves need a ``uid``, and the viewer has always queried an older, unauthenticated ``GET``
form of the same endpoint that is not metered. So `ASTRO_COLIBRI_UID` picks the path: configured,
we use the documented endpoint under its quota; unset, nothing changes and the legacy call
carries on. That keeps a deployment with no Astro-COLIBRI account working exactly as it does
today rather than silently capping it at an allowance nobody is counting. It is not somewhere to
stay, though: the legacy form is a side door around a policy its owners have already announced,
undocumented and free to disappear without notice, so a deployment that wants this catalog to
keep working should register an account and set the variable.
"""

import datetime
from typing import ClassVar

import numpy as np
from astropy.table import Table
from astropy.time import Time

from ztf_viewer import config
from ztf_viewer.catalogs.conesearch._base import _BaseCatalogApiQuery
from ztf_viewer.exceptions import NotFound
from ztf_viewer.http import get_client
from ztf_viewer.rate_limit import AsyncCallQuota
from ztf_viewer.util import safe_link

SECONDS_PER_DAY = 86400.0

#: The widest time window the endpoint accepts, as unix seconds: every event Astro-COLIBRI has.
#: The upper bound is the end of 32-bit time, which is what the legacy endpoint has always been
#: asked for here; both forms of the query derive their arguments from these two numbers, so the
#: window cannot drift between them.
_DATE_MIN_UNIX = 0
_DATE_MAX_UNIX = (1 << 31) - 1


def _isoformat(unix_seconds: int) -> str:
    """The same instant as an ISO date, which is what `time_range` takes.

    `datetime` rather than `astropy.time.Time`: ERFA has no leap-second table out to 2038 and
    warns about the "dubious year" every time it is asked to format one, which is noise on a
    bound that is deliberately far in the future.
    """
    return datetime.datetime.fromtimestamp(unix_seconds, datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S")


class ColibriQuery(_BaseCatalogApiQuery):
    id_column = "source_name"
    type_column = "type"
    redshift_column = "redshift"
    event_mjd_column = "mjd"
    _table_ra = "ra"
    _ra_unit = "deg"
    _table_dec = "dec"
    columns: ClassVar[dict] = {
        "__link": "Source name",
        "separation": "Separation, arcsec",
        "type": "Type",
        "mjd": "MJD",
        "date": "Date",
        "simbad_url": "Simbad page",
        "observatory": "Observatory",
    }
    __root_api_url = "https://astro-colibri.science"
    _base_api_url = f"{__root_api_url}/cone_search"
    _declared_html_columns = frozenset({"simbad_url"})  # get_link() below returns plain text

    # The daily allowance that comes with the account we identify as, and nothing to enforce
    # without one -- see the module docstring. `find()` spends one call from it per uncached cone
    # search, and a page that arrives with the day's budget gone is told the catalog is
    # unavailable instead of waiting hours for the window to roll.
    _rate_limiter: ClassVar[AsyncCallQuota | None] = (
        AsyncCallQuota(max_calls=config.ASTRO_COLIBRI_MAX_QUERIES_PER_DAY, period=SECONDS_PER_DAY)
        if config.ASTRO_COLIBRI_UID
        else None
    )

    @staticmethod
    def _post_body(ra, dec, radius_deg):
        """The documented request body, for the endpoint the rate-limit policy applies to.

        No ``filter``: the API then applies the filter configuration saved in the account's
        member space, and the account we query as is a deployment's, not a viewer's, so what it
        has saved is the deployment's choice of what this catalog shows. The filter structure
        itself is documented only by example in Astro-COLIBRI's notebooks, and an account with
        nothing saved is answered with ``"No filter and no uid data..."`` rather than results, so
        setting `ASTRO_COLIBRI_UID` means configuring that account's filters too.
        """
        return {
            "uid": config.ASTRO_COLIBRI_UID,
            "properties": {"position": {"ra": ra, "dec": dec}, "radius": radius_deg},
            "time_range": {"min": _isoformat(_DATE_MIN_UNIX), "max": _isoformat(_DATE_MAX_UNIX)},
        }

    @staticmethod
    def _legacy_query(ra, dec, radius_deg):
        """The unauthenticated call this viewer has always made. Dates are in unix milliseconds."""
        return {
            "cone": f"[{ra},{dec},{radius_deg}]",
            "datemin": _DATE_MIN_UNIX * 1000,
            "datemax": _DATE_MAX_UNIX * 1000,
        }

    async def _api_query_region(self, ra, dec, radius_arcsec):
        radius_deg = radius_arcsec / 3600.0
        client = get_client()
        if config.ASTRO_COLIBRI_UID:
            response = await client.post(
                self._base_api_url,
                json=self._post_body(ra, dec, radius_deg),
                timeout=config.TIMEOUT_CONESEARCH_API,
            )
        else:
            response = await client.get(
                self._get_api_url(self._legacy_query(ra, dec, radius_deg)),
                timeout=config.TIMEOUT_CONESEARCH_API,
            )
        self._raise_if_not_ok(response)
        data = response.json()
        # Both forms answer with the same lists (`voevents`, `sources`, ...), so everything below
        # is shared.
        vo_events = data["voevents"]

        if len(vo_events) == 0:
            raise NotFound
        for event in vo_events:
            for field, value in event.items():
                if value == "None":
                    event[field] = None
        table = Table(vo_events, masked=True)

        times = Time(table["timestamp"] / 1000.0, format="unix")
        table["mjd"] = times.mjd
        table["date"] = times.iso

        simbad_url = [safe_link(link, "Simbad") if link else "" for link in table["simbad_link"]]
        table["simbad_url"] = np.ma.array(simbad_url, mask=simbad_url == "")
        return table

    def get_link(self, id, name, row=None):
        return name

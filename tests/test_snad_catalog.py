"""Tests for the async SNAD catalog port (``ztf_viewer/catalogs/snad/catalog.py``).

No network access: the refresh goes through a fake ``httpx.AsyncClient`` built on
``httpx.MockTransport``, so these exercise the same client plumbing as production
(``ztf_viewer.http.get_client``) without hitting ``snad.space``.
"""

import asyncio
import email.utils
from datetime import UTC, datetime, timedelta

import httpx

from ztf_viewer import config
from ztf_viewer.catalogs.snad.catalog import _SnadCatalog

CSV_HEADER = "Name,R.A.,Dec.,OID,Discovery date (UT),mag,er_down,er_up,ref,er_ref,TNS,Type,Comments"
CSV_ROW = "SNAD999,10.0,20.0,42,2018-04-08 09:45:49,21.11,0.27,0.36,20.84,0.06,AT 2018abc,PSN,test"
CSV_BODY = f"{CSV_HEADER}\n{CSV_ROW}\n"


def _stale_catalog():
    """A catalog whose in-memory table is already due for a refresh."""
    catalog = _SnadCatalog(interval_seconds=600)
    catalog.updated_at = datetime(1900, 1, 1, tzinfo=UTC)
    return catalog


def _csv_response(when):
    return httpx.Response(
        200,
        headers={"last-modified": email.utils.format_datetime(when, usegmt=True)},
        content=CSV_BODY.encode(),
    )


async def test_update_goes_through_the_shared_client_with_the_snad_timeout(monkeypatch):
    seen = {}

    async def handler(request):
        seen["url"] = str(request.url)
        seen["timeout"] = request.extensions.get("timeout")
        return _csv_response(datetime.now(tz=UTC))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr("ztf_viewer.catalogs.snad.catalog.get_client", lambda: client)

    catalog = _stale_catalog()
    await catalog._update()

    assert seen["url"] == _SnadCatalog.url
    budget = config.TIMEOUT_SNAD
    assert seen["timeout"] == {
        "connect": budget.connect,
        "read": budget.read,
        "write": budget.write,
        "pool": budget.pool,
    }
    assert "SNAD999" in catalog.table["Name"]
    await client.aclose()


async def test_hung_upstream_is_bounded_not_hanging_forever(monkeypatch):
    """A timed-out request must be swallowed, not propagate and not hang the caller."""

    async def handler(request):
        raise httpx.ReadTimeout("simulated timeout", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr("ztf_viewer.catalogs.snad.catalog.get_client", lambda: client)

    catalog = _stale_catalog()
    stale_updated_at = catalog.updated_at
    stale_table = catalog.table

    await asyncio.wait_for(catalog._update(), timeout=5.0)

    # the timeout was swallowed: no refresh happened, the stale table is kept
    assert catalog.updated_at == stale_updated_at
    assert catalog.table is stale_table
    await client.aclose()


async def test_concurrent_stale_lookups_trigger_one_fetch(monkeypatch):
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return _csv_response(datetime.now(tz=UTC))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr("ztf_viewer.catalogs.snad.catalog.get_client", lambda: client)

    catalog = _stale_catalog()

    await asyncio.gather(*(catalog._update() for _ in range(8)))

    assert calls == 1, "N concurrent stale lookups must trigger one fetch, not N"
    await client.aclose()


async def test_fresh_table_within_check_interval_skips_fetch(monkeypatch):
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        return _csv_response(datetime.now(tz=UTC))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr("ztf_viewer.catalogs.snad.catalog.get_client", lambda: client)

    catalog = _SnadCatalog(interval_seconds=600)
    catalog.updated_at = datetime.now(tz=UTC)

    await catalog._update()

    assert calls == 0
    await client.aclose()


async def test_search_region_awaits_update_and_returns_match():
    catalog = _SnadCatalog(interval_seconds=600)
    catalog.updated_at = datetime.now(tz=UTC)  # fresh: no network call needed
    row = catalog.table[0]
    ra, dec = float(row["R.A."]), float(row["Dec."])

    name = await catalog.search_region(ra, dec, radius_arcsec=3)

    assert name == row["Name"]


async def test_failed_refresh_backs_off_then_retries_after_the_interval(monkeypatch):
    """A non-200/HTTPError attempt must not be retried on every call, only after backoff."""
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr("ztf_viewer.catalogs.snad.catalog.get_client", lambda: client)

    catalog = _SnadCatalog(interval_seconds=600, failure_retry_seconds=30)
    catalog.updated_at = datetime(1900, 1, 1, tzinfo=UTC)
    stale_table = catalog.table

    await catalog._update()
    assert calls == 1
    assert catalog._failed_at is not None
    # the fallback table must still be served after a failed refresh
    assert catalog.table is stale_table

    # a sequential call still within the retry backoff must not re-attempt the fetch
    await catalog._update()
    assert calls == 1
    assert catalog.table is stale_table

    # once the retry interval has elapsed, the next call must re-attempt
    catalog._failed_at = datetime.now(tz=UTC) - catalog.failure_retry_interval - timedelta(seconds=1)
    await catalog._update()
    assert calls == 2
    assert catalog.table is stale_table

    await client.aclose()


async def test_already_current_response_is_not_treated_as_a_failure(monkeypatch):
    """Server confirming our copy is current is a success, not something to back off from."""
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        # last-modified far in the past: older than our (recent) updated_at below
        return _csv_response(datetime.now(tz=UTC) - timedelta(days=1))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr("ztf_viewer.catalogs.snad.catalog.get_client", lambda: client)

    catalog = _SnadCatalog(interval_seconds=600, failure_retry_seconds=30)
    # due for a check, but newer than the server's last-modified above
    catalog.updated_at = datetime.now(tz=UTC) - catalog.check_interval - timedelta(seconds=1)
    stale_table = catalog.table

    await catalog._update()

    assert calls == 1
    assert catalog._failed_at is None, "an already-current response is not a failure"
    assert catalog.table is stale_table, "nothing new to download, table is unchanged"

    # updated_at was bumped to now, so an immediate follow-up call is within check_interval
    # and skips the fetch entirely, not merely within the (shorter) failure backoff
    await catalog._update()
    assert calls == 1

    await client.aclose()


def test_last_modified_returns_none_for_a_missing_header():
    resp = httpx.Response(200, content=CSV_BODY.encode())

    assert _SnadCatalog._last_modified(resp) is None


async def test_fetch_with_no_last_modified_header_does_not_raise_and_downloads(monkeypatch):
    """A response missing the header can't be compared, so it is treated as newer: the table
    is (re)downloaded rather than the fetch raising or silently doing nothing.
    """
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=CSV_BODY.encode())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr("ztf_viewer.catalogs.snad.catalog.get_client", lambda: client)

    catalog = _stale_catalog()

    await catalog._update()

    assert calls == 1
    assert catalog._failed_at is None
    assert "SNAD999" in catalog.table["Name"]

    await client.aclose()

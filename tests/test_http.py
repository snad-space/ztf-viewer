"""Tests for the shared async HTTP client and its timeout helper.

No network access here: the client-identity tests only check which loop a client is bound to,
and the timeout test drives ``ztf_viewer.util.async_timeout`` directly against a coroutine that
never resolves, exactly the shape a hung upstream call has.
"""

import asyncio
import importlib

import httpx
import pytest

from ztf_viewer import config
from ztf_viewer.catalogs.conesearch._base import _BaseCatalogQuery
from ztf_viewer.exceptions import CatalogUnavailable
from ztf_viewer.http import get_client
from ztf_viewer.ttl_set import LocalTTLSet
from ztf_viewer.util import async_timeout


def test_two_successive_asyncio_run_calls_get_different_clients() -> None:
    """Simulates Flask's per-request event loop (`tests/test_loop_registry.py`'s idiom): each
    `asyncio.run()` call must get its own client, not one bound to an already-closed loop."""

    async def body():
        client = get_client()
        assert client is get_client()  # same loop, same call: reused within the request
        await client.aclose()
        return client

    first = asyncio.run(body())
    second = asyncio.run(body())
    assert first is not second


def test_single_long_lived_loop_reuses_one_client() -> None:
    """Simulates FastAPI's one-loop-per-worker model: repeated calls on the same running loop
    return the same client instance."""

    async def body():
        first, second = get_client(), get_client()
        await first.aclose()
        return first, second

    first, second = asyncio.run(body())
    assert first is second


def test_client_is_configured_from_config() -> None:
    async def body():
        client = get_client()
        try:
            assert isinstance(client, httpx.AsyncClient)
            assert client.timeout.connect == config.HTTP_TIMEOUT_SECONDS
            pool = client._transport._pool
            assert pool._max_connections == config.HTTP_MAX_CONNECTIONS
            assert pool._max_keepalive_connections == config.HTTP_MAX_KEEPALIVE_CONNECTIONS
        finally:
            await client.aclose()

    asyncio.run(body())


async def test_async_timeout_raises_catalog_unavailable_with_catalog_kwarg(monkeypatch) -> None:
    """Mirrors today's `_base.py:108` behaviour: a query that outruns its budget becomes
    `CatalogUnavailable(catalog=...)`, not a bare `TimeoutError`."""
    # CatalogUnavailable's default `prolongate=True` records the catalog in the shared
    # unavailable-catalogs set, which defaults to a real Redis backend; swap in a local one so
    # this stays hermetic without changing the exception path under test.
    # `ztf_viewer.catalogs/__init__.py` re-exports the name `unavailable_catalogs` as a package
    # attribute, shadowing the submodule of the same name there; go through sys.modules to reach
    # the actual submodule and patch its attribute instead.
    unavailable_catalogs_module = importlib.import_module("ztf_viewer.catalogs.unavailable_catalogs")
    monkeypatch.setattr(unavailable_catalogs_module, "unavailable_catalogs", LocalTTLSet(maxsize=16, ttl=60))
    catalog = _BaseCatalogQuery("test-async-timeout-catalog")

    @async_timeout(seconds=0.01, exception=CatalogUnavailable, exception_kwargs=dict(catalog=catalog))
    async def hangs_forever():
        await asyncio.sleep(10)

    with pytest.raises(CatalogUnavailable) as excinfo:
        await hangs_forever()

    assert catalog.query_name in str(excinfo.value)


async def test_async_timeout_lets_fast_calls_through() -> None:
    @async_timeout(seconds=5.0, exception=CatalogUnavailable, exception_kwargs=dict(catalog=None))
    async def resolves_immediately():
        return "ok"

    assert await resolves_immediately() == "ok"

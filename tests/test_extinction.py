"""Tests for the async extinction port (``ztf_viewer/catalogs/extinction/``).

No network access: each request goes through a fake ``httpx.AsyncClient`` built on
``httpx.MockTransport``, so these exercise the same client plumbing as production
(``ztf_viewer.http.get_client``) without hitting ``dustmaps.snad.space``.
"""

import astropy.units as u
import httpx
import pytest
from astropy.coordinates import SkyCoord

from ztf_viewer import config
from ztf_viewer.catalogs.extinction.bayestar import BayestarQuery
from ztf_viewer.catalogs.extinction.csfd import CsfdQuery
from ztf_viewer.exceptions import CatalogUnavailable


def _json_response(ebv):
    return httpx.Response(200, json={"ebv": ebv})


async def test_ebv_goes_through_the_shared_client_with_the_extinction_timeout(monkeypatch):
    seen = {}

    async def handler(request):
        seen["url"] = str(request.url)
        seen["timeout"] = request.extensions.get("timeout")
        return _json_response(0.5)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr("ztf_viewer.catalogs.extinction._base.get_client", lambda: client)

    query = CsfdQuery()
    coord = SkyCoord(ra=10.0, dec=20.0, unit="deg")

    ebv = await query.ebv(coord)

    assert ebv == 0.5
    assert seen["url"].startswith(query.url)
    budget = config.TIMEOUT_EXTINCTION
    assert seen["timeout"] == {
        "connect": budget.connect,
        "read": budget.read,
        "write": budget.write,
        "pool": budget.pool,
    }
    await client.aclose()


async def test_http_error_raises_catalog_unavailable(monkeypatch):
    async def handler(request):
        return httpx.Response(503)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr("ztf_viewer.catalogs.extinction._base.get_client", lambda: client)

    query = CsfdQuery()
    coord = SkyCoord(ra=10.0, dec=20.0, unit="deg")

    with pytest.raises(CatalogUnavailable):
        await query.ebv(coord)

    await client.aclose()


async def test_null_ebv_raises_catalog_unavailable(monkeypatch):
    async def handler(request):
        return _json_response(None)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr("ztf_viewer.catalogs.extinction._base.get_client", lambda: client)

    query = CsfdQuery()
    coord = SkyCoord(ra=10.0, dec=20.0, unit="deg")

    with pytest.raises(CatalogUnavailable):
        await query.ebv(coord)

    await client.aclose()


async def test_bayestar_requires_a_distance():
    query = BayestarQuery()
    coord = SkyCoord(ra=10.0, dec=20.0, unit="deg")  # no distance attached

    with pytest.raises(ValueError, match="distance"):
        await query.ebv(coord)


async def test_bayestar_passes_distance_in_parsecs(monkeypatch):
    seen = {}

    async def handler(request):
        seen["params"] = dict(request.url.params)
        return _json_response(0.2)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr("ztf_viewer.catalogs.extinction._base.get_client", lambda: client)

    query = BayestarQuery()
    coord = SkyCoord(ra=10.0 * u.deg, dec=20.0 * u.deg, distance=100 * u.pc)

    ebv = await query.ebv(coord)

    assert ebv == 0.2
    assert float(seen["params"]["distance"]) == pytest.approx(100.0)
    await client.aclose()


async def test_call_returns_per_band_av_mapping(monkeypatch):
    async def handler(request):
        return _json_response(1.0)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr("ztf_viewer.catalogs.extinction._base.get_client", lambda: client)

    query = CsfdQuery()
    coord = SkyCoord(ra=10.0, dec=20.0, unit="deg")

    result = await query(coord)

    av = query.r * 1.0
    assert result == {band: av * af2av for band, af2av in query.af2av.items()}
    await client.aclose()

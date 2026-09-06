"""Astro-COLIBRI cone search: the two request forms, and the parsing they share.

Only the first test here talks to the real service, and it exercises the unauthenticated legacy
call, which is what a checkout with no `ASTRO_COLIBRI_UID` makes. The documented `POST` form
cannot be exercised for real without an account's user id -- the endpoint answers 400 to anyone
else -- so what is pinned for it is the request body against the published schema
(https://astro-colibri.science/apidoc), and the fact that the response handling is the same code
either way is pinned by feeding one canned payload through both paths.
"""

import pytest

CONE_RA, CONE_DEC = 10.684, 41.269
CONE_RADIUS_ARCSEC = 18.0

#: One event in the shape the API returns, cut down to the fields the parser touches. `"None"`
#: as a string is Astro-COLIBRI's own way of saying "no value", which the parser turns into a
#: real `None`; the empty `simbad_link` is an event with no Simbad counterpart.
CANNED_EVENT = {
    "source_name": "TestEvent",
    "type": "GRB",
    "ra": CONE_RA,
    "dec": CONE_DEC,
    "redshift": "None",
    "observatory": "Test observatory",
    "simbad_link": "",
    "timestamp": 1704067200000,  # 2024-01-01T00:00:00Z, MJD 60310
}


class _FakeResponse:
    status_code = 200
    text = ""

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeClient:
    """Records the one request made through it and answers with a canned payload."""

    def __init__(self, payload):
        self._payload = payload
        self.calls = []

    async def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        return _FakeResponse(self._payload)

    async def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))
        return _FakeResponse(self._payload)


@pytest.fixture
def fake_client(monkeypatch):
    """Swap the shared httpx client for a recorder, and hand the test what it recorded."""
    from ztf_viewer.catalogs.conesearch import colibri

    client = _FakeClient({"voevents": [CANNED_EVENT]})
    monkeypatch.setattr(colibri, "get_client", lambda: client)
    return client


async def test_cone_search():
    """Regression test against the real Astro-COLIBRI server, over the unauthenticated call.

    The cone is centred on M31, where the service holds a long-standing CBAT nova candidate. As
    with the other catalog tests, the expected object is whatever the live database currently
    returns; it was last verified 2026-09-05.
    """
    from ztf_viewer.catalogs.conesearch.colibri import ColibriQuery

    query = ColibriQuery("Test Astro-COLIBRI")
    table = await query._api_query_region(ra=CONE_RA, dec=CONE_DEC, radius_arcsec=CONE_RADIUS_ARCSEC)

    assert len(table) > 0
    for column in ("source_name", "ra", "dec", "type", "mjd", "date", "simbad_url"):
        assert column in table.colnames, f"Missing column: {column}"


async def test_cone_search_not_found():
    """A patch of sky Astro-COLIBRI has nothing in answers with an empty list, not an error.

    An arbitrary position rather than a round one: (0, 0) has a real event sitting on it.
    """
    from ztf_viewer.catalogs.conesearch.colibri import ColibriQuery
    from ztf_viewer.exceptions import NotFound

    query = ColibriQuery("Test Astro-COLIBRI 2")
    with pytest.raises(NotFound):
        await query._api_query_region(ra=123.4567, dec=-12.3456, radius_arcsec=1.0)


async def test_an_unauthenticated_deployment_queries_the_legacy_endpoint(fake_client, monkeypatch):
    """No uid configured: exactly the call this viewer has always made, unchanged."""
    from ztf_viewer.catalogs.conesearch.colibri import ColibriQuery

    monkeypatch.setattr("ztf_viewer.config.ASTRO_COLIBRI_UID", "")
    query = ColibriQuery("Test Astro-COLIBRI 3")

    table = await query._api_query_region(ra=CONE_RA, dec=CONE_DEC, radius_arcsec=CONE_RADIUS_ARCSEC)

    ((method, url, _kwargs),) = fake_client.calls
    assert method == "get"
    assert url.startswith("https://astro-colibri.science/cone_search?")
    assert f"cone=%5B{CONE_RA}%2C{CONE_DEC}%2C{CONE_RADIUS_ARCSEC / 3600.0}%5D" in url
    assert table["source_name"][0] == "TestEvent"


async def test_a_registered_deployment_posts_the_documented_body(fake_client, monkeypatch):
    """With a uid, the request is the documented one, so it is the metered one.

    Pinned field by field against the published schema, because getting a name wrong here does
    not fail loudly -- the endpoint would answer 400 and the catalog would simply be missing
    from every page.
    """
    from ztf_viewer.catalogs.conesearch.colibri import ColibriQuery

    monkeypatch.setattr("ztf_viewer.config.ASTRO_COLIBRI_UID", "test-uid")
    query = ColibriQuery("Test Astro-COLIBRI 4")

    table = await query._api_query_region(ra=CONE_RA, dec=CONE_DEC, radius_arcsec=CONE_RADIUS_ARCSEC)

    ((method, url, kwargs),) = fake_client.calls
    assert method == "post"
    assert url == "https://astro-colibri.science/cone_search"
    assert kwargs["json"] == {
        "uid": "test-uid",
        "properties": {
            "position": {"ra": CONE_RA, "dec": CONE_DEC},
            # The API takes degrees, and the viewer's search boxes are in arcseconds.
            "radius": CONE_RADIUS_ARCSEC / 3600.0,
        },
        # The widest window the API accepts, matching the legacy call's unix-millisecond bounds.
        "time_range": {"min": "1970-01-01T00:00:00", "max": "2038-01-19T03:14:07"},
    }
    # Same answer out of the same parser, whichever way the question was asked.
    assert table["source_name"][0] == "TestEvent"


async def test_the_response_is_parsed_the_same_way_on_both_paths(fake_client):
    """Timestamps, absent Simbad links and the API's string `"None"` are handled once, not twice."""
    from ztf_viewer.catalogs.conesearch.colibri import ColibriQuery

    query = ColibriQuery("Test Astro-COLIBRI 5")

    table = await query._api_query_region(ra=CONE_RA, dec=CONE_DEC, radius_arcsec=CONE_RADIUS_ARCSEC)

    assert table["mjd"][0] == 60310.0
    assert table["date"][0].startswith("2024-01-01")
    assert table["simbad_url"][0] == ""
    assert table["redshift"][0] is None

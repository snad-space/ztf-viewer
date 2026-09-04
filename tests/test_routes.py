"""`ztf_viewer/routes.py`: the URL patterns the page router matches on, and the document title
derived from the same patterns, so a tab or a bookmark says which page it is."""

import pytest
from dash.development.base_component import Component

from ztf_viewer.routes import SITE_TITLE, page_title
from ztf_viewer.util import DEFAULT_DR

_DR = DEFAULT_DR.upper()
_OID = "633207400004730"


@pytest.mark.parametrize(
    ("pathname", "expected"),
    [
        ("/", f"SNAD ZTF {_DR} viewer"),
        ("/dr23/", "SNAD ZTF DR23 viewer"),
        (f"/view/{_OID}", f"{_OID} — SNAD ZTF {_DR} viewer"),
        (f"/dr23/view/{_OID}", f"{_OID} — SNAD ZTF DR23 viewer"),
        ("/dr23/search/M57/1.5", "Search M57 r=1.5″ — SNAD ZTF DR23 viewer"),
        ("/login", f"Login — {SITE_TITLE}"),
        ("/anomalies", f"Anomalies — {SITE_TITLE}"),
        ("/akb", f"Anomalies — {SITE_TITLE}"),
        ("/tags", f"Tags — {SITE_TITLE}"),
        ("/dr7/view/1", f"DR7 is not supported — {SITE_TITLE}"),
        ("/no/such/page", f"404 — {SITE_TITLE}"),
    ],
)
def test_page_title(pathname, expected):
    assert page_title(pathname) == expected


def test_search_title_shows_the_decoded_query():
    """The pathname carries the query percent-encoded, the title must not."""
    title = page_title("/search/00h00m00s%20%2B00d00m00s/2")

    assert "00h00m00s +00d00m00s" in title
    assert "%" not in title


def test_page_title_of_a_pathname_dash_has_not_set_yet():
    """`url.pathname` is `None` until the first navigation; the router skips those, and the
    title falls back rather than raising."""
    assert page_title(None) == SITE_TITLE


def test_pages_have_distinct_titles():
    pathnames = ["/", f"/view/{_OID}", "/dr23/search/M57/1.5", "/login", "/anomalies", "/tags", "/no/such/page"]

    titles = [page_title(pathname) for pathname in pathnames]

    assert len(set(titles)) == len(titles)


def _load_app():
    """Import the fully wired app, forcing the in-memory cache backends first.

    Same dance as `tests/test_golden_http.py`: `ztf_viewer.catalogs.unavailable_catalogs`
    connects to Redis eagerly at import time.
    """
    from ztf_viewer import config

    config.CACHE_TYPE = "memory"
    config.UNAVAILABLE_CATALOGS_CACHE_TYPE = "memory"

    import ztf_viewer.__main__ as main_module

    return main_module.app


def _component_ids(component):
    children = getattr(component, "children", None)
    if isinstance(children, Component):
        children = [children]
    for child in children or ():
        if not isinstance(child, Component):
            continue
        if (id_ := getattr(child, "id", None)) is not None:
            yield id_
        yield from _component_ids(child)


def test_title_callback_is_wired_to_the_layout():
    """The store the server callback writes, and the sink the clientside one writes, must carry
    the ids that are really in the layout -- nothing else validates that, the app is built with
    `suppress_callback_exceptions`."""
    app = _load_app()

    # Clientside entries are the ones with no "callback" key.
    assert "callback" in app.callback_map["page-title.data"]
    assert "callback" not in app.callback_map["page-title-sink.children"]
    assert {"page-title", "page-title-sink"} <= set(_component_ids(app.layout))

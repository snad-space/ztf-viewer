"""`ztf_viewer.routes` gives every page its own browser title, for the same URLs the router
dispatches on."""

import pytest

from ztf_viewer.routes import BASE_TITLE, page_title
from ztf_viewer.util import DEFAULT_DR

_DEFAULT_DR_TITLE = f"SNAD ZTF {DEFAULT_DR.upper()} viewer"


@pytest.mark.parametrize(
    "pathname,expected",
    [
        ("/", _DEFAULT_DR_TITLE),
        ("/dr17/", "SNAD ZTF DR17 viewer"),
        ("/view/633207400004730", f"633207400004730 — {_DEFAULT_DR_TITLE}"),
        ("/dr17/view/633207400004730", "633207400004730 — SNAD ZTF DR17 viewer"),
        ("/search/M31/10", f"M31 search — {_DEFAULT_DR_TITLE}"),
        ("/dr17/search/M31/10", "M31 search — SNAD ZTF DR17 viewer"),
        ("/login", f"Login — {BASE_TITLE}"),
        ("/anomalies", f"Anomalies — {BASE_TITLE}"),
        ("/akb", f"Anomalies — {BASE_TITLE}"),
        ("/tags", f"Tags — {BASE_TITLE}"),
        ("/dr7/view/633207400004730", f"DR7 is not supported — {BASE_TITLE}"),
        ("/no-such-page", f"404 — {BASE_TITLE}"),
    ],
)
def test_page_title(pathname, expected):
    assert page_title(pathname) == expected


def test_search_title_is_url_decoded():
    assert page_title("/search/00h00m00s%20%2B00d00m00s/1").startswith("00h00m00s +00d00m00s search")


def test_page_title_of_a_missing_pathname():
    """`dcc.Location.pathname` is None until the browser reports it."""
    assert page_title(None) == BASE_TITLE


def test_every_page_has_a_distinct_title():
    pathnames = ["/", "/view/1", "/search/M31/10", "/login", "/anomalies", "/tags", "/no-such-page"]
    titles = [page_title(pathname) for pathname in pathnames]
    assert len(set(titles)) == len(titles)

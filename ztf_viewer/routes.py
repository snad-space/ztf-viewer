"""URL patterns of the single-page router, and the browser title of every page.

The patterns live here rather than inline in `ztf_viewer.__main__` so that the page router and
`page_title` cannot drift apart: both match the same pathname against the same regular
expressions.
"""

import re
import urllib.parse

from ztf_viewer.util import DEFAULT_DR

DR7 = re.compile(r"^/dr7((?:/.*)?)$")
HOME = re.compile(r"^/+(?:(?P<dr>dr\d{1,2})/+)?$")
VIEWER_DEFAULT_DR = re.compile(r"^/+view/+(?P<oid>\d+)")
VIEWER = re.compile(r"^/+(?P<dr>dr\d{1,2})/+view/+(?P<oid>\d+)")
SEARCH = re.compile(
    r"""^
        (?:/+(?P<dr>dr\d{1,2}))?
        /+search
        /+(?P<coord_or_name>[^/]+)
        /+(?P<radius_arcsec>[^/]+)
        /*
        $""",
    flags=re.VERBOSE,
)
LOGIN = re.compile(r"^/+login/*$")
ANOMALIES = re.compile(r"^/+(?:(?:anomalies)|(?:akb))/*$")
TAGS = re.compile(r"^/+tags/*$")


BASE_TITLE = "SNAD ZTF viewer"


def _dr_title(dr: str | None) -> str:
    return f"SNAD ZTF {(dr or DEFAULT_DR).upper()} viewer"


def page_title(pathname: str | None) -> str:
    """Browser title for a pathname, the distinguishing part first.

    Tab labels are truncated, so the object or search being looked at goes before the site name.
    """
    if not isinstance(pathname, str):
        return BASE_TITLE
    if DR7.search(pathname):
        return f"DR7 is not supported — {BASE_TITLE}"
    if match := HOME.search(pathname):
        return _dr_title(match["dr"])
    if match := VIEWER_DEFAULT_DR.search(pathname):
        return f"{match['oid']} — {_dr_title(None)}"
    if match := VIEWER.search(pathname):
        return f"{match['oid']} — {_dr_title(match['dr'])}"
    if match := SEARCH.search(pathname):
        coord_or_name = urllib.parse.unquote(match["coord_or_name"])
        return f"{coord_or_name} search — {_dr_title(match['dr'])}"
    if LOGIN.search(pathname):
        return f"Login — {BASE_TITLE}"
    if ANOMALIES.search(pathname):
        return f"Anomalies — {BASE_TITLE}"
    if TAGS.search(pathname):
        return f"Tags — {BASE_TITLE}"
    return f"404 — {BASE_TITLE}"

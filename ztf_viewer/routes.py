"""URL patterns of the Dash pages, and the document title that goes with each.

The page router in `ztf_viewer/__main__.py` and `page_title` must agree on which page a
pathname belongs to, so the patterns live here rather than inline at the router's call sites.
"""

import re
import urllib.parse

from ztf_viewer.util import DEFAULT_DR

#: Title suffix for the pages that do not belong to a single data release.
SITE_TITLE = "SNAD ZTF viewer"

DR7 = re.compile(r"^/dr7((?:/.*)?)$")
HOME = re.compile(r"^/+(?:(dr\d{1,2})/+)?$")
VIEW_DEFAULT_DR = re.compile(r"^/+view/+(?P<oid>\d+)")
VIEW = re.compile(r"^/+(?P<dr>dr\d{1,2})/+view/+(?P<oid>\d+)")
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


def _site_title(dr: str | None = None) -> str:
    """The site title, naming the data release on the pages that belong to one."""
    if dr is None:
        return SITE_TITLE
    return f"SNAD ZTF {dr.upper()} viewer"


def _page_title(page: str, dr: str | None = None) -> str:
    return f"{page} — {_site_title(dr)}"


def page_title(pathname) -> str:
    """The document title for `pathname`, matching the page the router builds for it."""
    if not isinstance(pathname, str):
        return SITE_TITLE
    if DR7.search(pathname):
        return _page_title("DR7 is not supported")
    if match := HOME.search(pathname):
        return _site_title(match.group(1) or DEFAULT_DR)
    if match := VIEW.search(pathname) or VIEW_DEFAULT_DR.search(pathname):
        return _page_title(match["oid"], match.groupdict().get("dr") or DEFAULT_DR)
    if match := SEARCH.search(pathname):
        coord_or_name = urllib.parse.unquote(match["coord_or_name"])
        return _page_title(f"Search {coord_or_name} r={match['radius_arcsec']}″", match["dr"] or DEFAULT_DR)
    if LOGIN.search(pathname):
        return _page_title("Login")
    if ANOMALIES.search(pathname):
        return _page_title("Anomalies")
    if TAGS.search(pathname):
        return _page_title("Tags")
    return _page_title("404")

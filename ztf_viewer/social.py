"""Open Graph and Twitter card tags, so a shared link previews as the page it points at.

The app is a single Dash page whose content is filled in by callbacks, and crawlers do not run
that JavaScript: whatever a preview shows has to be in the HTML the server sends, and the only
thing telling the server what the link is about is the pathname it was asked for. So the tags
are built here from the pathname, matched against the same `ztf_viewer.routes` patterns the
router and the browser title use, and injected per request in `ztf_viewer.app`.
"""

import html
import urllib.parse

from ztf_viewer import routes
from ztf_viewer.figure_render import CARD_MIMETYPE, CARD_SUFFIX
from ztf_viewer.util import DEFAULT_DR

SITE_NAME = "SNAD ZTF viewer"

SITE_DESCRIPTION = "Light curves, cross-matches and cutouts of ZTF data release objects."


def _dr(dr: str | None) -> str:
    return (dr or DEFAULT_DR).upper()


def _object(pathname: str) -> tuple[str, str] | None:
    """The `(dr, oid)` an object page is of, or `None` for any other page."""
    if match := routes.VIEWER_DEFAULT_DR.search(pathname):
        return DEFAULT_DR, match["oid"]
    if match := routes.VIEWER.search(pathname):
        return match["dr"], match["oid"]
    return None


def _description(pathname: str, snad_name: str | None) -> str:
    """One line about the page, the same pathnames `routes.page_title` distinguishes."""
    if obj := _object(pathname):
        dr, oid = obj
        named = f"{snad_name}, " if snad_name else ""
        return f"Light curve, cross-matches and cutouts of {named}ZTF {_dr(dr)} object {oid}."
    if match := routes.SEARCH.search(pathname):
        coord_or_name = urllib.parse.unquote(match["coord_or_name"])
        return f"ZTF {_dr(match['dr'])} objects within {match['radius_arcsec']}″ of {coord_or_name}."
    return SITE_DESCRIPTION


LOGO_PATH = "static/img/logo.png"

# The site's own card, for pages with no light curve to show; `ztf_viewer.pages.figure` serves
# this path, and the two must agree, which `tests/test_golden_http.py` checks.
SITE_CARD_PATH = f"card.{CARD_SUFFIX}"


def _preview_image(pathname: str) -> tuple[str, str, str]:
    """Relative URL of the preview picture, its media type, and the card shape that fits it.

    An object page has a picture of its own -- the light curve `ztf_viewer.pages.figure` draws
    for the card -- and every other page shows the site's card. Both are wide, so a link
    unfurls as a picture rather than as a URL with a stamp beside it.
    """
    if obj := _object(pathname):
        dr, oid = obj
        return f"{dr}/card/{oid}.{CARD_SUFFIX}", CARD_MIMETYPE, "summary_large_image"
    return SITE_CARD_PATH, CARD_MIMETYPE, "summary_large_image"


def social_meta_tags(pathname: str, url: str, root: str, snad_name: str | None = None) -> list[dict[str, str]]:
    """Open Graph and Twitter tags for `pathname`, as attribute mappings.

    `url` is the URL being served and `root` the site root both come from the request, so a
    deployment behind any hostname advertises itself under that hostname. `snad_name` is the
    object's name where the page is an object page and the object is in the SNAD catalog: it
    is what the object is called, so the preview leads with it, as the page itself does.
    """
    title = routes.page_title(pathname)
    if snad_name and _object(pathname):
        title = f"{snad_name} — {title}"
    description = _description(pathname, snad_name)
    image_path, image_type, card = _preview_image(pathname)
    image_url = urllib.parse.urljoin(root, image_path)

    return [
        {"name": "description", "content": description},
        {"property": "og:type", "content": "website"},
        {"property": "og:site_name", "content": SITE_NAME},
        {"property": "og:title", "content": title},
        {"property": "og:description", "content": description},
        {"property": "og:url", "content": url},
        {"property": "og:image", "content": image_url},
        # The type is worth stating for a card: it tells a crawler the picture is WebP before
        # it spends a fetch finding out, and one that cannot read WebP can skip it outright.
        {"property": "og:image:type", "content": image_type},
        {"property": "og:image:alt", "content": title},
        {"name": "twitter:card", "content": card},
        {"name": "twitter:title", "content": title},
        {"name": "twitter:description", "content": description},
        {"name": "twitter:image", "content": image_url},
    ]


def social_meta_html(pathname: str, url: str, root: str, snad_name: str | None = None) -> str:
    """`social_meta_tags` rendered as `<meta>` tags for the index `<head>`."""
    return "\n      ".join(
        "<meta " + " ".join(f'{name}="{html.escape(value)}"' for name, value in tag.items()) + ">"
        for tag in social_meta_tags(pathname, url, root, snad_name)
    )

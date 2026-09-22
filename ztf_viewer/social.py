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
from ztf_viewer.util import DEFAULT_DR

SITE_NAME = "SNAD ZTF viewer"

SITE_DESCRIPTION = "Light curves, cross-matches and cutouts of ZTF data release objects."


def _dr(dr: str | None) -> str:
    return (dr or DEFAULT_DR).upper()


def _description(pathname: str) -> str:
    """One line about the page, the same pathnames `routes.page_title` distinguishes."""
    if match := routes.VIEWER_DEFAULT_DR.search(pathname):
        return f"Light curve, cross-matches and cutouts of ZTF {_dr(None)} object {match['oid']}."
    if match := routes.VIEWER.search(pathname):
        return f"Light curve, cross-matches and cutouts of ZTF {_dr(match['dr'])} object {match['oid']}."
    if match := routes.SEARCH.search(pathname):
        coord_or_name = urllib.parse.unquote(match["coord_or_name"])
        return f"ZTF {_dr(match['dr'])} objects within {match['radius_arcsec']}″ of {coord_or_name}."
    return SITE_DESCRIPTION


LOGO_PATH = "static/img/logo.png"


def _preview_image(pathname: str) -> tuple[str, str]:
    """Relative URL of the preview picture, and the card shape that fits it.

    An object page has a picture of its own -- the light curve `ztf_viewer.pages.figure` draws
    for the card, wide enough for the big card -- and every other page falls back to the SNAD
    logo, which is square and belongs in the small one.
    """
    if match := routes.VIEWER_DEFAULT_DR.search(pathname):
        return f"{DEFAULT_DR}/card/{match['oid']}.png", "summary_large_image"
    if match := routes.VIEWER.search(pathname):
        return f"{match['dr']}/card/{match['oid']}.png", "summary_large_image"
    return LOGO_PATH, "summary"


def social_meta_tags(pathname: str, url: str, root: str) -> list[dict[str, str]]:
    """Open Graph and Twitter tags for `pathname`, as attribute mappings.

    `url` is the URL being served and `root` the site root both come from the request, so a
    deployment behind any hostname advertises itself under that hostname.
    """
    title = routes.page_title(pathname)
    description = _description(pathname)
    image_path, card = _preview_image(pathname)
    image_url = urllib.parse.urljoin(root, image_path)

    return [
        {"name": "description", "content": description},
        {"property": "og:type", "content": "website"},
        {"property": "og:site_name", "content": SITE_NAME},
        {"property": "og:title", "content": title},
        {"property": "og:description", "content": description},
        {"property": "og:url", "content": url},
        {"property": "og:image", "content": image_url},
        {"property": "og:image:alt", "content": title},
        {"name": "twitter:card", "content": card},
        {"name": "twitter:title", "content": title},
        {"name": "twitter:description", "content": description},
        {"name": "twitter:image", "content": image_url},
    ]


def social_meta_html(pathname: str, url: str, root: str) -> str:
    """`social_meta_tags` rendered as `<meta>` tags for the index `<head>`."""
    return "\n      ".join(
        "<meta " + " ".join(f'{name}="{html.escape(value)}"' for name, value in tag.items()) + ">"
        for tag in social_meta_tags(pathname, url, root)
    )

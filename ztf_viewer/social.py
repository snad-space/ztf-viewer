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


def _image_path(pathname: str) -> str | None:
    """Relative URL of the preview image, or `None` for a page without one.

    Only object pages have a picture to show: the light curve `ztf_viewer.pages.figure` renders
    for the card.
    """
    if match := routes.VIEWER_DEFAULT_DR.search(pathname):
        return f"{DEFAULT_DR}/card/{match['oid']}.png"
    if match := routes.VIEWER.search(pathname):
        return f"{match['dr']}/card/{match['oid']}.png"
    return None


def social_meta_tags(pathname: str, url: str, root: str) -> list[dict[str, str]]:
    """Open Graph and Twitter tags for `pathname`, as attribute mappings.

    `url` is the URL being served and `root` the site root both come from the request, so a
    deployment behind any hostname advertises itself under that hostname.
    """
    title = routes.page_title(pathname)
    description = _description(pathname)
    image_path = _image_path(pathname)

    tags = [
        {"name": "description", "content": description},
        {"property": "og:type", "content": "website"},
        {"property": "og:site_name", "content": SITE_NAME},
        {"property": "og:title", "content": title},
        {"property": "og:description", "content": description},
        {"property": "og:url", "content": url},
        {"name": "twitter:title", "content": title},
        {"name": "twitter:description", "content": description},
    ]
    if image_path is None:
        # No picture, so the narrow card: a large one would leave an empty frame.
        tags.append({"name": "twitter:card", "content": "summary"})
    else:
        image_url = urllib.parse.urljoin(root, image_path)
        tags += [
            {"property": "og:image", "content": image_url},
            {"property": "og:image:alt", "content": title},
            {"name": "twitter:card", "content": "summary_large_image"},
            {"name": "twitter:image", "content": image_url},
        ]
    return tags


def social_meta_html(pathname: str, url: str, root: str) -> str:
    """`social_meta_tags` rendered as `<meta>` tags for the index `<head>`."""
    return "\n      ".join(
        "<meta " + " ".join(f'{name}="{html.escape(value)}"' for name, value in tag.items()) + ">"
        for tag in social_meta_tags(pathname, url, root)
    )

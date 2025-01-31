import json
from urllib.parse import quote_plus

from dash import html

DEFAULT_SEARCH_RADIUS_ARCSEC = 3


def _a_tag(text, url):
    return html.A(text, href=url)


def alerce_conesearch_url(ra, dec, radius_arcsec=DEFAULT_SEARCH_RADIUS_ARCSEC):
    return f"https://alerce.online/?ra={ra}&dec={dec}&radius={radius_arcsec}&page=1"


def alerce_tag(ra, dec, radius_arcsec=DEFAULT_SEARCH_RADIUS_ARCSEC):
    return _a_tag("ALeRCE", alerce_conesearch_url(ra, dec, radius_arcsec))


def antares_conesearch_url(ra, dec, radius_arcsec=DEFAULT_SEARCH_RADIUS_ARCSEC, *, oid):
    radius_deg = radius_arcsec / 3600.0
    query = {
        "filters": [
            {
                "type": "sky_distance",
                "field": {
                    "distance": f"{radius_deg} degree",
                    "htm16": {"center": f"{ra} {dec}"},
                },
                "text": f"Cone Search for ZTF DR {oid} {radius_arcsec}″",
            },
        ],
    }
    query_string = quote_plus(json.dumps(query))
    return f"https://antares.noirlab.edu/loci?query={query_string}"


def antares_tag(ra, dec, radius_arcsec=DEFAULT_SEARCH_RADIUS_ARCSEC, *, oid):
    return _a_tag("Antares", antares_conesearch_url(ra, dec, radius_arcsec, oid=oid))


def fink_conesearch_url(ra, dec, radius_arcsec=DEFAULT_SEARCH_RADIUS_ARCSEC):
    return f"https://fink-portal.org/?action=conesearch&ra={ra}&dec={dec}&radius={radius_arcsec}"


def fink_tag(ra, dec, radius_arcsec=DEFAULT_SEARCH_RADIUS_ARCSEC):
    return _a_tag("Fink", fink_conesearch_url(ra, dec, radius_arcsec))


def mars_conesearch_url(ra, dec, radius_arcsec=DEFAULT_SEARCH_RADIUS_ARCSEC):
    radius_deg = radius_arcsec / 3600.0
    cone = quote_plus(f"{ra},{dec},{radius_deg}")
    return f"https://mars.lco.global/?cone={cone}"


def mars_tag(ra, dec, radius_arcsec=DEFAULT_SEARCH_RADIUS_ARCSEC):
    return _a_tag("MARS", mars_conesearch_url(ra, dec, radius_arcsec))

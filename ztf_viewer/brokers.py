import json
from urllib.parse import quote_plus

def alerce_conesearch_url(ra, dec, radius_arcsec=1):
    return f'https://alerce.online/?ra={ra}&dec={dec}&radius={radius_arcsec}&page=1'


def antares_conesearch_url(ra, dec, radius_arcsec=1, *, oid):
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
    return f'https://antares.noirlab.edu/loci?query={query_string}'

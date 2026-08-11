from io import BytesIO

import astropy.io.ascii
from markupsafe import Markup, escape
from requests.exceptions import JSONDecodeError

from ztf_viewer.catalogs.conesearch._base import _BaseCatalogApiQuery
from ztf_viewer.util import safe_link


class AstrocatsQuery(_BaseCatalogApiQuery):
    id_column = "event"
    type_column = "claimedtype"
    redshift_column = "redshift"
    _table_ra = "ra"
    _ra_unit = "hour"
    _table_dec = "dec"
    columns = {
        "__link": "Event name",
        "separation": "Separation, arcsec",
        "claimedtype": "Claimed type",
        "stellarclass": "Stellar class",
        "spectraltype": "Spectral type",
        "redshift": "Redshift",
        "host": "Host",
        "references": "References",
    }
    __root_api_url = "https://api.astrocats.space"
    _base_api_url = f"{__root_api_url}/all"
    _declared_html_columns = frozenset({"references"})  # get_link() below returns plain text

    def _get_sources(self, id):
        response = self._api_session.get(f"{self.__root_api_url}/{id}/sources", timeout=10)
        self._raise_if_not_ok(response)
        data = response.json()
        return data[id]["sources"]

    @staticmethod
    def _format_source(source):
        name, url, bibcode = source["name"], source.get("url"), source.get("bibcode")
        ads_link = safe_link(f"//adsabs.harvard.edu/abs/{bibcode}", bibcode) if bibcode else None
        if url and bibcode:
            return safe_link(url, name) + " (" + ads_link + ")"
        if url:
            return safe_link(url, name)
        if bibcode:
            return ads_link if bibcode == name else escape(name) + " (" + ads_link + ")"
        return escape(name)

    def _api_query_region(self, ra, dec, radius_arcsec):
        query = {"ra": ra, "dec": dec, "radius": radius_arcsec, "format": "csv", "item": 0}
        response = self._api_session.get(self._get_api_url(query), timeout=10)
        self._raise_if_not_ok(response)
        # If nothing is found a single-line JSON response coming:
        # {"message": "No objects found within specified search region."}
        try:
            if len(response.json()) > 0:
                return None
        except JSONDecodeError:
            pass
        table = astropy.io.ascii.read(BytesIO(response.content), format="csv", guess=False)
        table["references"] = [
            Markup(", ").join(map(self._format_source, sources)) for sources in map(self._get_sources, table["event"])
        ]
        return table

    def get_link(self, id, name, row=None):
        return name

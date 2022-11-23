import numpy as np
from astropy.table import Table
from astropy.time import Time

from ztf_viewer.catalogs.conesearch._base import _BaseCatalogApiQuery
from ztf_viewer.exceptions import NotFound


class ColibriQuery(_BaseCatalogApiQuery):
    id_column = "source_name"
    type_column = "type"
    redshift_column = "redshift"
    _table_ra = "ra"
    _ra_unit = "deg"
    _table_dec = "dec"
    columns = {
        "__link": "Source name",
        "separation": "Separation, arcsec",
        "type": "Type",
        "mjd": "MJD",
        "date": "Date",
        "simbad_url": "Simbad page",
        "observatory": "Observatory",
    }
    __root_api_url = "https://astro-colibri.science"
    _base_api_url = f"{__root_api_url}/cone_search"

    def _api_query_region(self, ra, dec, radius_arcsec):
        radius_deg = radius_arcsec / 3600.0
        query = {"cone": f"[{ra},{dec},{radius_deg}]", "datemin": 0, "datemax": ((1 << 31) - 1) * 1000}
        response = self._api_session.get(self._get_api_url(query), timeout=10)
        self._raise_if_not_ok(response)
        data = response.json()
        vo_events = data["voevents"]

        if len(vo_events) == 0:
            raise NotFound
        for event in vo_events:
            for field, value in event.items():
                if value == "None":
                    event[field] = None
        table = Table(vo_events, masked=True)

        times = Time(table["timestamp"] / 1000.0, format="unix")
        table["mjd"] = times.mjd
        table["date"] = times.iso

        simbad_url = [f'<a href="{link}">Simbad</a>' if link else "" for link in table["simbad_link"]]
        table["simbad_url"] = np.ma.array(simbad_url, mask=simbad_url == "")
        return table

    def get_link(self, id, name, row=None):
        return name

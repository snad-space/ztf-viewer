import urllib.parse
from base64 import b64encode
from io import BytesIO
from typing import ClassVar

import astropy.io.ascii

from ztf_viewer.catalogs.conesearch._base import _BaseCatalogApiQuery
from ztf_viewer.config import OGLE_III_API_URL, TIMEOUT_CONESEARCH_API, TIMEOUT_OGLE_LIGHT_CURVE
from ztf_viewer.http import get_client
from ztf_viewer.util import anchor_form


class OgleQuery(_BaseCatalogApiQuery):
    id_column = "ID"
    type_column = "Type"
    period_column = "P_1"
    _table_ra = "RA"
    _ra_unit = "hour"
    _table_dec = "Decl"
    columns: ClassVar[dict] = {
        "__link": "Designation",
        "separation": "Separation, arcsec",
        "light_curve": "Light curve",
        "Type": "Type",
        "Subtype": "Subtype",
        "P_1": "Period, days",
        "A_1": "I-band amplitude, mag",
        "I": "Mean I-magnitude",
        "V": "Mean V-magnitude",
        "Remarks": "Remarks",
    }
    _declared_html_columns = frozenset({"__link", "light_curve"})
    _base_api_url = f"{OGLE_III_API_URL}/api/v1/circle"
    _base_light_curve_url = "https://ogledb.astrouw.edu.pl/~ogle/CVS/images/"
    _post_url = "https://ogledb.astrouw.edu.pl/~ogle/CVS/query.php?first=1&qtype=catalog"
    _post_data: ClassVar[dict] = {
        "db_target": "all",
        "sort": "id",
        "use_id": "on",
        "disp_field": "on",
        "disp_starid": "on",
        "disp_type": "1",
        "disp_subtype": "1",
        "disp_ra": "on",
        "disp_decl": "on",
        "disp_i": "on",
        "disp_v": "on",
        "disp_p1": "on",
        "disp_a1": "on",
        "disp_id_ogle_ii": "on",
        "disp_id_macho": "on",
        "disp_id_asas": "on",
        "disp_id_gcvs": "on",
        "disp_id_other": "on",
        "disp_remarks": "on",
        "sorting": "ASC",
        "hexout": "on",
        "pagelen": "50",
    }

    async def _download_light_curve(self, id):
        basepath = f"{id[-2:]}/{id}"
        paths = [basepath + ".png", basepath + "_1.png"]
        light_curve_urls = [urllib.parse.urljoin(self._base_light_curve_url, path) for path in paths]
        for url in light_curve_urls:
            response = await get_client().get(url, timeout=TIMEOUT_OGLE_LIGHT_CURVE)
            if response.status_code == 200:
                data = b64encode(response.content).decode()
                # JSX (used by dcc.Markdown's HTML renderer) needs attribute values quoted.
                return f'<a href="{url}"><img src="data:image/png;base64,{data}" width="200px" /></a>'
        return ""

    async def _api_query_region(self, ra, dec, radius_arcsec):
        query = {"ra": ra, "dec": dec, "radius_arcsec": radius_arcsec, "format": "tsv"}
        response = await get_client().get(self._get_api_url(query), timeout=TIMEOUT_CONESEARCH_API)
        self._raise_if_not_ok(response)
        table = astropy.io.ascii.read(BytesIO(response.content), format="tab", guess=False)
        table["light_curve"] = [await self._download_light_curve(row[self.id_column]) for row in table]
        return table

    def get_link(self, id, name, row=None):
        return anchor_form(self._post_url, dict(**self._post_data, val_id=id), name)

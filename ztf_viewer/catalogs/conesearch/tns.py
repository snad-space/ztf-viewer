from ztf_viewer.catalogs.conesearch._base import (
    _BaseCatalogApiQuery,
    _BaseNameResolverQuery,
)
from ztf_viewer.config import TNS_API_URL
from ztf_viewer.http import get_client


class TnsQuery(_BaseCatalogApiQuery, _BaseNameResolverQuery):
    id_column = "name"
    type_column = "type"
    redshift_column = "redshift"
    _name_column = "fullname"
    _table_ra = "ra"
    _ra_unit = "deg"
    _table_dec = "declination"
    columns = {
        "__link": "Name",
        "separation": "Separation, arcsec",
        "discoverydate": "Discovery date",
        "discoverymag": "Discovery mag",
        "type": "Type",
        "redshift": "Redshift",
        "internal_names": "Internal names",
    }

    _base_api_url = f"{TNS_API_URL}/api/v1/circle"

    def get_url(self, id, row=None):
        return f"//www.wis-tns.org/object/{id}"

    async def _api_query_region(self, ra, dec, radius_arcsec):
        table = await super()._api_query_region(ra, dec, radius_arcsec)
        table["fullname"] = [f'{row["name_prefix"] or ""}{row["name"]}' for row in table]
        return table

    _resolve_api_url = f"{TNS_API_URL}/api/v1/object"

    async def get_record_by_id(self, id):
        """id is something like 2018lwh, not AT2018lwh"""
        response = await get_client().get(self._resolve_api_url, params={"name": id}, timeout=1)
        self._raise_if_not_ok(response)
        return response.json()

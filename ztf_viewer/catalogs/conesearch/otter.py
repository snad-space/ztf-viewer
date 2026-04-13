import astropy.table
from requests.exceptions import RequestException

from ztf_viewer.catalogs.conesearch._base import _BaseCatalogApiQuery
from ztf_viewer.exceptions import CatalogUnavailable, NotFound


class OtterQuery(_BaseCatalogApiQuery):
    id_column = "default_name"
    type_column = "object_class"
    redshift_column = "redshift"
    _table_ra = "ra"
    _ra_unit = "deg"
    _table_dec = "dec"
    columns = {
        "__link": "Name",
        "separation": "Separation, arcsec",
        "object_class": "Type",
        "redshift": "Redshift",
        "discovery_date": "Discovery date",
    }
    _base_api_url = "https://otter.idies.jhu.edu/api/_db/otter/_api/cursor"
    _otter_web_url = "https://otter.idies.jhu.edu/transient"
    _api_auth = ("user-guest", "test")

    def _raise_if_not_ok(self, response):
        if not response.ok:
            raise CatalogUnavailable(response.text, catalog=self)

    def _api_query_region(self, ra, dec, radius_arcsec):
        radius_deg = radius_arcsec / 3600.0
        query = {
            "query": (
                "FOR t IN transients "
                "FILTER (ABS(((t._ra - @ra + 180) % 360) - 180) * COS(RADIANS(t._dec)) <= @sep "
                "AND ABS(t._dec - @dec) <= @sep) "
                "FILTER ASTRO::CONE_SEARCH(t._ra, t._dec, @ra, @dec, @sep) "
                "RETURN t"
            ),
            "count": True,
            "batchSize": 100,
            "bindVars": {"ra": ra, "dec": dec, "sep": radius_deg},
        }
        try:
            response = self._api_session.post(
                self._base_api_url,
                json=query,
                auth=self._api_auth,
                timeout=10,
            )
            self._raise_if_not_ok(response)
        except RequestException as e:
            raise CatalogUnavailable(str(e), catalog=self)

        results = response.json().get("result", [])
        if not results:
            raise NotFound

        rows = []
        for item in results:
            default_name = item.get("name", {}).get("default_name", "")

            object_class = None
            for cls in item.get("classification", {}).get("value", []):
                if cls.get("default", False):
                    object_class = cls.get("object_class")
                    break
            if object_class is None:
                clslist = item.get("classification", {}).get("value", [])
                if clslist:
                    object_class = clslist[0].get("object_class")

            redshift = None
            for dist in item.get("distance", []):
                if dist.get("distance_type") == "redshift":
                    if dist.get("default", False):
                        redshift = dist.get("value")
                        break
                    if redshift is None:
                        redshift = dist.get("value")
            try:
                redshift = float(redshift) if redshift is not None else None
            except (TypeError, ValueError):
                redshift = None

            discovery_date = None
            for date_ref in item.get("date_reference", []):
                if date_ref.get("date_type") == "discovery":
                    if date_ref.get("default", False):
                        discovery_date = (date_ref.get("value") or "").strip()
                        break
                    if discovery_date is None:
                        discovery_date = (date_ref.get("value") or "").strip()

            rows.append(
                {
                    "default_name": default_name,
                    "ra": item.get("_ra"),
                    "dec": item.get("_dec"),
                    "object_class": object_class or "",
                    "redshift": redshift,
                    "discovery_date": discovery_date or "",
                }
            )

        return astropy.table.Table(rows=rows)

    def get_url(self, id, row=None):
        return f"{self._otter_web_url}/{id}"

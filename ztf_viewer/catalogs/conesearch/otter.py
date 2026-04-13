import math

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
        # Exact maximum RA extent of a spherical cone: arcsin(sin(r) / cos(dec)).
        # When the ratio >= 1 the cone contains a pole and all RA values are possible.
        sin_ra_sep = math.sin(math.radians(radius_deg)) / math.cos(math.radians(dec))
        if sin_ra_sep >= 1.0:
            # Cone contains a pole — no RA constraint needed
            ra_filter = "true"
            bind_vars = {"ra": ra, "dec": dec, "sep": radius_deg}
        else:
            ra_sep = math.degrees(math.asin(sin_ra_sep))
            ra_min = ra - ra_sep
            ra_max = ra + ra_sep
            if ra_min < 0:
                # Box wraps past RA=0
                ra_filter = "(t._ra >= @ra_min_w OR t._ra <= @ra_max)"
                bind_vars = {"ra": ra, "dec": dec, "sep": radius_deg,
                             "ra_min_w": ra_min + 360.0, "ra_max": ra_max}
            elif ra_max > 360:
                # Box wraps past RA=360
                ra_filter = "(t._ra >= @ra_min OR t._ra <= @ra_max_w)"
                bind_vars = {"ra": ra, "dec": dec, "sep": radius_deg,
                             "ra_min": ra_min, "ra_max_w": ra_max - 360.0}
            else:
                ra_filter = "(t._ra >= @ra_min AND t._ra <= @ra_max)"
                bind_vars = {"ra": ra, "dec": dec, "sep": radius_deg,
                             "ra_min": ra_min, "ra_max": ra_max}
        query = {
            "query": (
                "FOR t IN transients "
                f"FILTER ({ra_filter} AND t._dec >= @dec - @sep AND t._dec <= @dec + @sep) "
                "FILTER ASTRO::CONE_SEARCH(t._ra, t._dec, @ra, @dec, @sep) "
                "RETURN t"
            ),
            "count": True,
            "batchSize": 100,
            "bindVars": bind_vars,
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

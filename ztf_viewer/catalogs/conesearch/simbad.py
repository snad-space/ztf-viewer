import urllib.parse

from astropy import units
from astroquery.simbad import Simbad

from ztf_viewer.catalogs.conesearch._base import _BaseCatalogQuery


class SimbadQuery(_BaseCatalogQuery):
    id_column = "main_id"
    type_column = "otype"
    _table_ra = "RA"
    _ra_unit = "hour"
    _table_dec = "DEC"
    columns = {
        "__link": "main_id",
        "separation": "Separation, arcsec",
        "otype": "Main type",
        "otype2": "Other type",
        "mesotype.otype": "Variable type",
        "mesdistance.dist": "Distance",
        "mesdistance.unit": "Distance unit",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._query = Simbad()
        self._query.add_votable_fields("mesdistance", "R", "V", "otype", "otypes")
        self._query_region = self._query.query_region

    def get_url(self, id, row=None):
        qid = urllib.parse.quote(id)
        return f"//simbad.u-strasbg.fr/simbad/sim-id?Ident={qid}"

    def add_distance_column(self, table):
        table["__distance"] = table["mesdistance.dist"] * [units.Unit(u) for u in table["mesdistance.unit"]]

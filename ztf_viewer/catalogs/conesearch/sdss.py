import urllib.parse
from typing import ClassVar

from markupsafe import Markup, escape

from ztf_viewer.cache import cache
from ztf_viewer.catalogs.conesearch._base import _BaseVizierQuery


class SdssQuasarsQuery(_BaseVizierQuery):
    id_column = "SDSS"
    type_column = "Class"
    redshift_column = "z"
    columns: ClassVar[dict] = {
        "__link": "SDSS",
        "separation": "Separation, arcsec",
        "Class": Markup("""
            <a href="https://vizier.iucaa.in/viz-bin/VizieR-n?-source=METAnot&amp;catid=7289&amp;notid=7&amp;-out=text">
                Source class
            </a>
        """),
        "QSO": "Quasars included",
        "z": "redshift",
        "r_z": "redshift source",
        "gmag": "g mag",
        "rmag": "r mag",
        "imag": "i mag",
    }

    _class_map: ClassVar[dict] = {
        0: "not inspected",
        1: "star",
        3: "quasar",
        4: "galaxy",
        30: "BAL quasar",
        50: "possible blazar",
    }

    # `r_z` (SOURCE_Z) codes, see note (3) of https://cdsarc.cds.unistra.fr/ftp/VII/289/ReadMe
    # The three catalog-borrowed codes link to the catalog the redshift was taken from.
    _redshift_source_map: ClassVar[dict] = {
        "PIPE": "SDSS pipeline redshift of this catalog",
        "VI": "visual inspection of this catalog",
        "DR6Q_HW": Markup("""
            <a href="https://vizier.cds.unistra.fr/viz-bin/VizieR-3?-source=J/MNRAS/405/2302">
                SDSS DR6Q, Hewett &amp; Wild (2010)
            </a>
        """),
        "DR7QV_SCH": Markup("""
            <a href="https://vizier.cds.unistra.fr/viz-bin/VizieR-3?-source=VII/260">
                SDSS DR7Q, Schneider et al. (2010)
            </a>
        """),
        "DR12QV": Markup("""
            <a href="https://vizier.cds.unistra.fr/viz-bin/VizieR-3?-source=VII/279">
                SDSS DR12Q, visual inspection
            </a>
        """),
    }

    # `r_z` cells are pre-built HTML, see `_redshift_source()`
    _declared_html_columns = frozenset({"__link", "r_z"})

    @classmethod
    def _redshift_source(cls, code) -> str:
        """Human-readable description of an `r_z` code, as an HTML string.

        Unknown codes are shown as-is: a new catalog release may add one, and that should not
        hide the rest of the row. They still have to be escaped, because the column as a whole
        is rendered unescaped.
        """
        code = str(code).strip()
        return cls._redshift_source_map.get(code) or escape(code)

    _vizier_columns: ClassVar[list] = [
        "SDSS",
        "Class",
        "z",
        "QSO",
        "r_z",
        "gmag",
        "rmag",
        "imag",
        "Plate",
        "MJD",
        "Fiber",
    ]
    _vizier_catalog = "VII/289/superset"

    @cache()
    async def find(self, ra, dec, radius_arcsec):
        table = await super().find(ra, dec, radius_arcsec)
        table["__type"] = table["Class"] = [self._class_map.get(c, f"unknown class {c}") for c in table["Class"]]
        table["r_z"] = [self._redshift_source(code) for code in table["r_z"]]
        return table

    def get_url(self, id, row=None):
        params = urllib.parse.urlencode({"plateid": row["Plate"], "mjd": row["MJD"], "fiberid": row["Fiber"]})
        return f"//dr16.sdss.org/optical/spectrum/view?{params}"

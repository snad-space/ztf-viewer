from typing import ClassVar

from markupsafe import Markup

from ztf_viewer.catalogs.conesearch._base import _BaseVizierQuery


class GcvsQuery(_BaseVizierQuery):
    id_column = "GCVS"
    type_column = "VarType"
    period_column = "Period"
    columns: ClassVar[dict] = {
        "__link": "Designation",
        "separation": "Separation, arcsec",
        "Period": "Period, days",
        "VarType": Markup("""
            <a href="http://cdsarc.u-strasbg.fr/viz-bin/getCatFile_Redirect/?-plus=-%2b&amp;B/gcvs/./vartype.txt">
                Type of variability
            </a>
        """),
        "SpType": "Spectral type",
    }

    _vizier_columns: ClassVar[list] = [
        "GCVS",
        "VarType",
        "magMax",
        "Period",
        "SpType",
        "VarTypeII",
        "VarName",
        "Simbad",
    ]
    _vizier_catalog = "B/gcvs/gcvs_cat"

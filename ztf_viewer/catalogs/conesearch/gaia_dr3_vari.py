from typing import ClassVar

from markupsafe import Markup

from ztf_viewer.catalogs.conesearch._base import _BaseVizierQuery


class GaiaDr3VariQuery(_BaseVizierQuery):
    """Gaia DR3 Part 4. Variability: the variability classifier result.

    https://vizier.cds.unistra.fr/viz-bin/VizieR-3?-source=I/358/vclassre

    VSX credits a Gaia-classified variable to Gaia rather than to whoever finds it next, so a hit
    here means the object is already a published variable, not a new one.
    """

    id_column = "Source"
    type_column = "Class"
    columns: ClassVar[dict] = {
        "__link": "Source ID",
        "separation": "Separation, arcsec",
        "Class": Markup("""
            <a href="https://vizier.cds.unistra.fr/viz-bin/VizieR-3?-source=I/358/vcclassd">
                Best variability class
            </a>
        """),
        "ClassSc": "Class score",
    }

    _vizier_columns: ClassVar[list] = ["Source", "Class", "ClassSc"]
    _vizier_catalog = "I/358/vclassre"

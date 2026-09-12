from typing import ClassVar

from ztf_viewer.catalogs.conesearch._base import (
    ValueWithIntervalColumn,
    _BaseVizierQuery,
)


class _BaseGaiaDr3ExtragalacticQuery(_BaseVizierQuery):
    """Gaia DR3 Part 2, extra-galactic candidates (Gaia Collaboration, 2023)

    https://ui.adsabs.harvard.edu/abs/2023A%26A...674A..41G

    `Class` is the variability class, blank for most candidates. The DSC probabilities are also
    in Gaia DR3 itself, so they are table columns here rather than summary classifications.
    """

    id_column = "Source"
    type_column = "Class"
    redshift_column = "z"

    _value_with_interval_columns: ClassVar[list] = [
        ValueWithIntervalColumn(value="z", lower="zlow", upper="zupp"),
    ]


class GaiaDr3QsoCandidates(_BaseGaiaDr3ExtragalacticQuery):
    columns: ClassVar[dict] = {
        "__link": "Source ID",
        "separation": "Separation, arcsec",
        "Class": "Variability class",
        "ClassSc": "Variability class score",
        "_z": "Redshift, QSOC",
        "PQSO": "Quasar prob",
        "PGal": "Galaxy prob",
    }

    _vizier_columns: ClassVar[list] = ["Source", "Class", "ClassSc", "z", "zlow", "zupp", "PQSO", "PGal"]
    _vizier_catalog = "I/356/qsocand"


class GaiaDr3GalaxyCandidates(_BaseGaiaDr3ExtragalacticQuery):
    columns: ClassVar[dict] = {
        "__link": "Source ID",
        "separation": "Separation, arcsec",
        "Class": "Variability class",
        "ClassSc": "Variability class score",
        "_z": "Redshift, UGC",
        "PGal": "Galaxy prob",
        "PQSO": "Quasar prob",
    }

    _vizier_columns: ClassVar[list] = ["Source", "Class", "ClassSc", "z", "zlow", "zupp", "PGal", "PQSO"]
    _vizier_catalog = "I/356/galcand"

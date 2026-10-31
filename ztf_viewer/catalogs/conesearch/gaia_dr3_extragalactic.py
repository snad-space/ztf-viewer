"""Gaia DR3 Part 2. Extra-galactic: the quasar and galaxy candidate tables.

https://vizier.cds.unistra.fr/viz-bin/VizieR-3?-source=I/356
"""

from typing import ClassVar

import numpy as np
from markupsafe import Markup

from ztf_viewer.catalogs.conesearch._base import ValueWithIntervalColumn, _BaseVizierQuery

_VARI_CLASS_COLUMN = Markup("""
    <a href="https://vizier.cds.unistra.fr/viz-bin/VizieR-3?-source=I/358/vcclassd">
        Best variability class
    </a>
""")

_DSC_CLASS_COLUMN = "DSC-Combmod class"

_OA_CLASS_COLUMN = "Outlier Analysis class"


class _BaseGaiaDr3ExtragalacticQuery(_BaseVizierQuery):
    id_column = "Source"
    # `Class` here is `vari_best_class_name`, the same variability class as in I/358/vclassre --
    # the extragalactic tables carry it so that a candidate's variability is visible without a
    # second cross-match.
    type_column = "Class"
    redshift_column = "z"

    # Both catalogs quote confidence limits a few times 1e-4 wide, which the default three
    # decimal digits round away to "+0.000 -0.000"
    _value_with_interval_columns: ClassVar[list] = [
        ValueWithIntervalColumn(value="z", lower="zlow", upper="zupp", float_decimal_digits=4),
    ]


class GaiaDr3QsoCandQuery(_BaseGaiaDr3ExtragalacticQuery):
    """Gaia DR3 quasar candidates, with the QSOC redshift."""

    columns: ClassVar[dict] = {
        "__link": "Source ID",
        "separation": "Separation, arcsec",
        "_z": "QSOC redshift",
        "PQSO": "Quasar prob",
        "PGal": "Galaxy prob",
        "Class": _VARI_CLASS_COLUMN,
        "VAGNMenSc": "AGN membership score",
        "ClassDSCC": _DSC_CLASS_COLUMN,
        "ClassOA": _OA_CLASS_COLUMN,
        "flagsQSOC": Markup("""
            <a href="https://cdsarc.cds.unistra.fr/ftp/I/356/ReadMe">QSOC flags</a>, 0 = no warning
        """),
    }

    _vizier_columns: ClassVar[list] = [
        "Source",
        "Class",
        "VAGNMenSc",
        "PQSO",
        "PGal",
        "ClassDSCC",
        "ClassOA",
        "z",
        "zlow",
        "zupp",
        "flagsQSOC",
    ]
    _vizier_catalog = "I/356/qsocand"

    def add_redshift_column(self, table):
        """Keep only the QSOC redshifts Gaia DR3 says are usable.

        `flags_qsoc` is non-zero when the QSOC analysis of the BP/RP spectrum hit a problem --
        an ambiguous cross-correlation peak, a missing emission line, a spectrum too faint to
        trust -- and the catalog's own note calls the flag "the simple way to filter out
        uncertain predictions". The column is what the summary turns into a distance and then
        into an absolute magnitude, where a wrong redshift is a several-magnitude error, so a
        flagged row gets no redshift at all rather than a bad one. The `_z` display column still
        shows it, flags and all.
        """
        super().add_redshift_column(table)
        table["__redshift"] = [
            None if np.ma.is_masked(flags) or flags != 0 else redshift
            for redshift, flags in zip(table["__redshift"], table["flagsQSOC"])
        ]


class GaiaDr3GalCandQuery(_BaseGaiaDr3ExtragalacticQuery):
    """Gaia DR3 galaxy candidates, with the UGC redshift."""

    columns: ClassVar[dict] = {
        "__link": "Source ID",
        "separation": "Separation, arcsec",
        "_z": "UGC redshift",
        "PGal": "Galaxy prob",
        "PQSO": "Quasar prob",
        "Class": _VARI_CLASS_COLUMN,
        "ClassDSCC": _DSC_CLASS_COLUMN,
        "ClassOA": _OA_CLASS_COLUMN,
        "RadS": "Sérsic radius, mas",
    }

    _vizier_columns: ClassVar[list] = [
        "Source",
        "Class",
        "PGal",
        "PQSO",
        "ClassDSCC",
        "ClassOA",
        "z",
        "zlow",
        "zupp",
        "RadS",
    ]
    _vizier_catalog = "I/356/galcand"

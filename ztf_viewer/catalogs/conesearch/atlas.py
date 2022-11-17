from ztf_viewer.catalogs.conesearch._base import _BaseVizierQuery


class AtlasQuery(_BaseVizierQuery):
    id_column = "ATOID"
    type_column = "Class"
    period_column = "fp-LSper"
    columns = {
        "__link": "Name",
        "separation": "Separation, arcsec",
        "fp-LSper": "Period, days",
        "Class": "Class",
    }
    _vizier_columns = ["ATOID", "fp-LSper", "Class"]
    _vizier_catalog = "J/AJ/156/241/table4"

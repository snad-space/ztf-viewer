from markupsafe import Markup

from ztf_viewer.catalogs.conesearch._base import _BaseVizierQuery


class SpicyQuery(_BaseVizierQuery):
    id_column = "SPICY"
    type_column = "class"
    columns = {
        "__link": "Name",
        "separation": "Separation, arcsec",
        "class": Markup(
            '<a href="https://vizier.cds.unistra.fr/viz-bin/VizieR-n?-source=METAnot&amp;catid=22540033&amp;notid=3&amp;-out'
            '=text">YSO class</a>'
        ),
        "Group": Markup(
            '<a href="https://vizier.cds.unistra.fr/viz-bin/VizieR-n?-source=METAnot&amp;catid=22540033&amp;notid=1&amp;-out'
            '=text">HDBSCAN group</a>'
        ),
        "var": Markup(
            '<a href="https://vizier.cds.unistra.fr/viz-bin/VizieR-n?-source=METAnot&amp;catid=22540033&amp;notid=6&amp;-out'
            '=text">ZTF variability flag</a>'
        ),
        "ZTFrmag": "ZTF mean r magnitude",
    }
    _vizier_columns = ["SPICY", "class", "Group", "ZTFrmag", "var"]
    _vizier_catalog = "J/ApJS/254/33/table1"

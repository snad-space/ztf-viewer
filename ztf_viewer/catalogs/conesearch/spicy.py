from ztf_viewer.catalogs.conesearch._base import _BaseVizierQuery


class SpicyQuery(_BaseVizierQuery):
    id_column = 'SPICY'
    type_column = 'class'
    columns = {
        '__link': 'Name',
        'separation': 'Separation, arcsec',
        'class': '<a href="https://vizier.cds.unistra.fr/viz-bin/VizieR-n?-source=METAnot&catid=22540033&notid=3&-out=text">YSO class</a>',
    }
    _vizier_columns=['SPICY', 'class']
    _vizier_catalog='J/ApJS/254/33/table1'


from ztf_viewer.catalogs.conesearch._base import _BaseVizierQuery


class SpicyQuery(_BaseVizierQuery):
    id_column = 'SPICY'
    type_column = 'class'
    columns = {
        '__link': 'Name',
        'separation': 'Separation, arcsec',
        'class': '<a href="https://vizier.cds.unistra.fr/viz-bin/VizieR-n?-source=METAnot&catid=22540033&notid=3&-out'
                 '=text">YSO class</a>',
        'Group': '<a href="https://vizier.cds.unistra.fr/viz-bin/VizieR-n?-source=METAnot&catid=22540033&notid=1&-out'
                 '=text">HDBSCAN group</a>',
        'var': '<a href="https://vizier.cds.unistra.fr/viz-bin/VizieR-n?-source=METAnot&catid=22540033&notid=6&-out'
               '=text">ZTF variability flag</a>',
        'ZTFrmag': 'ZTF mean r magnitude'
    }
    _vizier_columns=['SPICY', 'class', 'Group', 'ZTFrmag', 'var']
    _vizier_catalog='J/ApJS/254/33/table1'


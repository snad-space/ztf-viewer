from functools import partial

from astroquery.vizier import Vizier

from ztf_viewer.catalogs.conesearch._base import _BaseCatalogQuery


class AtlasQuery(_BaseCatalogQuery):
    id_column = 'ATOID'
    type_column = 'Class'
    period_column = 'fp-LSper'
    _table_ra = 'RAJ2000'
    _ra_unit = 'hour'
    _table_dec = 'DEJ2000'
    columns = {
        '__link': 'Name',
        'separation': 'Separation, arcsec',
        'fp-LSper': 'Period, days',
        'Class': 'Class',
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._query = Vizier(
            columns=['ATOID', 'RAJ2000', 'DEJ2000', 'fp-LSper', 'Class'],
        )
        self._query_region = partial(self._query.query_region, catalog='J/AJ/156/241/table4')

    def get_url(self, id):
        return f'//vizier.u-strasbg.fr/viz-bin/VizieR-6?-out.form=%2bH&-source=J/AJ/156/241/table4&Source={id}'

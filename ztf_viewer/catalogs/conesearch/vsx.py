from functools import partial

from astroquery.vizier import Vizier

from ztf_viewer.catalogs.conesearch._base import _BaseCatalogQuery


class VsxQuery(_BaseCatalogQuery):
    id_column = 'OID'
    type_column = 'Type'
    period_column = 'Period'
    _table_ra = 'RAJ2000'
    _ra_unit = 'hour'
    _table_dec = 'DEJ2000'
    columns = {
        '__link': 'Designation',
        'separation': 'Separation, arcsec',
        'Name': 'Name',
        'Period': 'Period, days',
        'Type': '<a href="https://aavso.org/vsx/help/VariableStarTypeDesignationsInVSX.pdf">Variability type</a>',
        'max': 'Maximum mag',
        'n_max': 'Band of max mag',
        'min': 'Minimum mag',
        'n_min': 'Band of min mag',
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._query = Vizier()
        self._query_region = partial(self._query.query_region, catalog='B/vsx/vsx')

    def get_url(self, id):
        return f'//www.aavso.org/vsx/index.php?view=detail.top&oid={id}'

from functools import partial

from astropy.units import mag
from astroquery.vizier import Vizier

from ztf_viewer.cache import cache
from ztf_viewer.catalogs.conesearch._base import _BaseCatalogQuery


class SdssQuasarsQuery(_BaseCatalogQuery):
    id_column = 'SDSS'
    type_column = 'Class'
    _table_ra = 'RAJ2000'
    _ra_unit = 'deg'
    _table_dec = 'DEJ2000'
    redshift_column = 'z'
    columns = {
        '__link': 'SDSS',
        'separation': 'Separation, arcsec',
        'Class': '<a href="https://vizier.iucaa.in/viz-bin/VizieR-n?-source=METAnot&catid=7289&notid=7&-out=text">Source class</a>',
        'QSO': 'Quasars included',
        'z': 'redshift',
        'r_z': 'redshift source',
        'gmag': 'g mag',
        'rmag': 'r mag',
        'imag': 'i mag',
    }

    _class_map = {
        0: 'not inspected',
        1: 'star',
        3: 'quasar',
        4: 'galaxy',
        30: 'BAL quasar',
        50: 'possible blazar',
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._query = Vizier(columns=['SDSS', 'Class', 'RAJ2000', 'DEJ2000', 'z', 'QSO', 'r_z', 'gmag', 'rmag', 'imag',
                                      'Plate', 'MJD', 'Fiber'])
        self._query_region = partial(self._query.query_region, catalog='VII/289/superset')

    @cache()
    def find(self, ra, dec, radius_arcsec):
        table = super().find(ra, dec, radius_arcsec)
        table['__type'] = table['Class'] = [self._class_map[c] for c in table['Class']]
        return table

    def get_url(self, id, row=None):
        print(row)
        return f'//dr16.sdss.org/optical/spectrum/view?plateid={row["Plate"]}&mjd={row["_tab2_6"]}&fiberid={row["Fiber"]}'
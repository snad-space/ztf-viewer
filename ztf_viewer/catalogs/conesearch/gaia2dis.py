from functools import partial

from astropy import units
from astroquery.vizier import Vizier

from ztf_viewer.catalogs.conesearch._base import _BaseCatalogQuery


class Gaia2Dis(_BaseCatalogQuery):
    """Gaia DR2 distances from Bailer-Jones et al 2018

    Estimating Distance from Parallaxes. IV. Distances to 1.33 Billion Stars
    in Gaia Data Release 2
    https://ui.adsabs.harvard.edu/abs/2018AJ....156...58B
    """
    id_column = 'Source'
    _table_ra = 'RA_ICRS'
    _ra_unit = 'deg'
    _table_dec = 'DE_ICRS'
    columns = {
        '__link': 'Source ID',
        'separation': 'Separation, arcsec',
        'rest': 'Distance, pc',
        'b_rest': 'Lower bound of conf. interval, pc',
        'B_rest': 'Upper bound of conf. interval, pc',
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._query = Vizier(
            columns=['Source', 'RA_ICRS', 'DE_ICRS', 'rest', 'b_rest', 'B_rest', 'rlen', 'ResFlag', 'ModFlag'],
        )
        self._query_region = partial(self._query.query_region, catalog='I/347/gaia2dis')

    def get_url(self, id, row=None):
        return f'//vizier.u-strasbg.fr/viz-bin/VizieR-6?-out.form=%2bH&-source=I/347/gaia2dis&Source={id}'

    def add_distance_column(self, table):
        table['__distance'] = [x * units.pc for x in table['rest']]

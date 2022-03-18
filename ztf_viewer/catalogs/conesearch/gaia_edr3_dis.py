from functools import partial

from astropy import units
from astroquery.vizier import Vizier

from ztf_viewer.catalogs.conesearch._base import _BaseCatalogQuery


class GaiaEdr3Dis(_BaseCatalogQuery):
    """Gaia DR2 distances from Bailer-Jones et al 2021

    https://ui.adsabs.harvard.edu/?#abs/2021AJ....161..147B
    """
    id_column = 'Source'
    _table_ra = 'RA_ICRS'
    _ra_unit = 'deg'
    _table_dec = 'DE_ICRS'
    columns = {
        '__link': 'Source ID',
        'separation': 'Separation, arcsec',
        'rgeo': 'Geometric distance, pc',
        'b_rgeo': 'Lower bound, pc',
        'B_rgeo': 'Upper bound, pc',
        'rpgeo': 'Photogeometric distance, pc',
        'b_rpgeo': 'Lower bound, pc',
        'B_rpgeo': 'Upper bound, pc'
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._query = Vizier(
            columns=['Source', 'RA_ICRS', 'DE_ICRS', 'rgeo', 'b_rgeo', 'B_rgeo', 'rpgeo', 'b_rpgeo', 'B_rpgeo', 'Flag'],
        )
        self._query_region = partial(self._query.query_region, catalog='I/352/gedr3dis')

    def get_url(self, id, row=None):
        return f'//vizier.u-strasbg.fr/viz-bin/VizieR-6?-out.form=%2bH&-source=I/352/gedr3dis&Source={id}'

    def add_distance_column(self, table):
        table['__distance'] = [x * units.pc for x in table['rgeo']]

from astropy import units

from ztf_viewer.catalogs.conesearch._base import _BaseVizierQuery


class GaiaEdr3Dis(_BaseVizierQuery):
    """Gaia eDR3 distances from Bailer-Jones et al 2021

    https://ui.adsabs.harvard.edu/?#abs/2021AJ....161..147B
    """
    id_column = 'Source'
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

    _vizier_columns=['Source', 'rgeo', 'b_rgeo', 'B_rgeo', 'rpgeo', 'b_rpgeo', 'B_rpgeo', 'Flag']
    _vizier_catalog='I/352/gedr3dis'

    def add_distance_column(self, table):
        table['__distance'] = [x * units.pc for x in table['rgeo']]

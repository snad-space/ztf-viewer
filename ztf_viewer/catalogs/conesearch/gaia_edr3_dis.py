from astropy import units

from ztf_viewer.catalogs.conesearch._base import _BaseVizierQuery, ValueWithIntervalColumn


class GaiaEdr3Dis(_BaseVizierQuery):
    """Gaia eDR3 distances from Bailer-Jones et al 2021

    https://ui.adsabs.harvard.edu/?#abs/2021AJ....161..147B
    """
    id_column = 'Source'
    columns = {
        '__link': 'Source ID',
        'separation': 'Separation, arcsec',
        '_rgeo': 'Geometric distance, pc',
        '_rpgeo': 'Photogeometric distance, pc',
    }

    _vizier_columns=['Source', 'rgeo', 'b_rgeo', 'B_rgeo', 'rpgeo', 'b_rpgeo', 'B_rpgeo', 'Flag']
    _vizier_catalog='I/352/gedr3dis'

    _value_with_interval_columns = [
        ValueWithIntervalColumn(value='rgeo'),
        ValueWithIntervalColumn(value='rpgeo'),
    ]

    def add_distance_column(self, table):
        table['__distance'] = [x * units.pc for x in table['rgeo']]

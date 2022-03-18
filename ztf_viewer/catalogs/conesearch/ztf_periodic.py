import pandas as pd
from astropy.table import Table

from ztf_viewer.catalogs.conesearch._base import _BaseCatalogApiQuery


class ZtfPeriodicQuery(_BaseCatalogApiQuery):
    id_column = 'SourceID'
    type_column = 'Type'
    period_column = 'Per'
    _name_column = 'ID'
    _table_ra = 'RAdeg'
    _ra_unit = 'deg'
    _table_dec = 'DEdeg'
    columns = {
        '__link': 'ZTF ID',
        'separation': 'Separation, arcsec',
        'Type': 'Type',
        'Per': 'Period, days',
        'Per_g': 'zg period, days',
        'Per_r': 'zr period, days',
        'Amp_g': 'zg amplitude',
        'Amp_r': 'zr amplitude',
    }
    _base_api_url = 'http://periodic.ztf.snad.space/api/v1/circle'

    def get_url(self, id, row=None):
        return f'http://variables.cn:88/lcz.php?SourceID={id}'

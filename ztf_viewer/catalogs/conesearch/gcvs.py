import urllib.parse
from functools import partial

from astroquery.vizier import Vizier

from ztf_viewer.catalogs.conesearch._base import _BaseCatalogQuery


class GcvsQuery(_BaseCatalogQuery):
    id_column = 'GCVS'
    type_column = 'VarType'
    period_column = 'Period'
    _table_ra = 'RAJ2000'
    _ra_unit = 'hour'
    _table_dec = 'DEJ2000'
    columns = {
        '__link': 'Designation',
        'separation': 'Separation, arcsec',
        'Period': 'Period, days',
        'VarType': '<a href="http://cdsarc.u-strasbg.fr/viz-bin/getCatFile_Redirect/?-plus=-%2b&B/gcvs/./vartype.txt">Type of variability</a>',
        'SpType': 'Spectral type',
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._query = Vizier(
            columns=['GCVS', 'RAJ2000', 'DEJ2000', 'VarType', 'magMax', 'Period', 'SpType', 'VarTypeII', 'VarName',
                     'Simbad'],
        )
        self._query_region = partial(self._query.query_region, catalog='B/gcvs/gcvs_cat')

    def get_url(self, id):
        qid = urllib.parse.quote_plus(id)
        return f'http://www.sai.msu.su/gcvs/cgi-bin/search.cgi?search={qid}'

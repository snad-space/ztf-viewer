from alerce.core import Alerce
from astropy.table import Table

from ztf_viewer.catalogs.conesearch._base import _BaseCatalogApiQuery


class AlerceQuery(_BaseCatalogApiQuery):
    id_column = 'oid'
    type_column = 'class'
    _table_ra = 'meanra'
    _ra_unit = 'deg'
    _table_dec = 'meandec'
    columns = {
        '__link': 'oid',
        'separation': 'Separation, arcsec',
        'class': 'Class',
        'classifier': 'Classifier',
        'probability': 'Class probability',
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._client = Alerce()

    def _query_region(self, coord, radius):
        ra = coord.ra.deg
        dec = coord.dec.deg
        if not (isinstance(radius, str) and radius.endswith('s')):
            raise ValueError('radius argument should be strings that ends with "s" letter')
        radius_arcsec = float(radius[:-1])
        df = self._client.query_objects(format='pandas', ra=ra, dec=dec, radius=radius_arcsec, page_size=128)
        table = Table.from_pandas(df)
        return table

    def get_url(self, id, row=None):
        return f'//alerce.online/object/{id}'

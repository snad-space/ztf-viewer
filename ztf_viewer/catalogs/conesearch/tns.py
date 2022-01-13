from ztf_viewer.catalogs.conesearch._base import _BaseCatalogApiQuery


class TnsQuery(_BaseCatalogApiQuery):
    id_column = 'name'
    type_column = 'type'
    redshift_column = 'redshift'
    _name_column = 'fullname'
    _table_ra = 'ra'
    _ra_unit = 'deg'
    _table_dec = 'declination'
    columns = {
        '__link': 'Name',
        'separation': 'Separation, arcsec',
        'discoverydate': 'Discovery date',
        'discoverymag': 'Discovery mag',
        'type': 'Type',
        'redshift': 'Redshift',
        'internal_names': 'Internal names',
    }

    _base_api_url = 'http://tns.snad.space/api/v1/circle'

    def get_url(self, id, row=None):
        return f'//www.wis-tns.org/object/{id}'

    def _api_query_region(self, ra, dec, radius_arcsec):
        table = super()._api_query_region(ra, dec, radius_arcsec)
        table['fullname'] = [f'{row["name_prefix"] or ""}{row["name"]}' for row in table]
        return table

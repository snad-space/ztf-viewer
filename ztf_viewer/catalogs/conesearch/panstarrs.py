from itertools import count

import numpy as np
from astropy.coordinates import Angle, SkyCoord
from astropy.table import Table
from astroquery.mast import Catalogs

from ztf_viewer.cache import cache
from ztf_viewer.catalogs.conesearch._base import _BaseCatalogQuery, _BaseLightCurveQuery
from ztf_viewer.exceptions import NotFound


class PanstarrsDr2StackedQuery(_BaseCatalogQuery, _BaseLightCurveQuery):
    # https://outerspace.stsci.edu/display/PANSTARRS/PS1+FAQ+-+Frequently+asked+questions
    id_column = 'objName'
    _table_ra = 'raMean'
    _ra_unit = 'deg'
    _table_dec = 'decMean'
    columns = {
        '__link': 'Name',
        'objID': 'ID',
        'separation': 'Separation, arcsec',
        'gPSFMag': 'g PSF mag',
        'gPSFMagErr': 'err',
        'rPSFMag': 'r mag',
        'rPSFMagErr': 'err',
        'iPSFMag': 'i mag',
        'iPSFMagErr': 'err',
        'zPSFMag': 'z mag',
        'zPSFMagErr': 'err',
        'yPSFMag': 'y mag',
        'yPSFMagErr': 'err',
    }

    _detection_url = 'https://catalogs.mast.stsci.edu/panstarrs/detections.html'

    _bands = 'grizy'
    _band_ids = dict(zip(count(1), _bands))
    _phot_types = ('Ap', 'PSF')

    def __init__(self, query_name):
        super().__init__(query_name)
        self._catalogs = Catalogs()

    def __apply_groups(self, df):
        """Averaging stacked objects

        Due to sky cells overlapping we can have multiple rows per a single
        object
        """
        row = df.iloc[0].copy()

        if df.shape[0] == 1:
            return row

        for band in self._bands:
            for phot_type in self._phot_types:
                mag_column = f'{band}{phot_type}Mag'
                err_column = f'{band}{phot_type}MagErr'
                idx = (df[mag_column] >= 0) & (df[err_column] >= 0)
                valid = df[idx]
                w_ = 1.0 / np.square(valid[err_column])
                row[mag_column] = np.average(valid[mag_column], weights=w_)
                row[err_column] = 1.0 / np.sqrt(np.mean(w_))

        return row

    def _query_region(self, coord, radius):
        table = self._catalogs.query_region(coord, radius=radius, catalog='Panstarrs', data_release='dr2',
                                            table='stacked')
        df = table.to_pandas()
        df = df[df['primaryDetection'] == 1]
        df = df.groupby('objID', sort=False).apply(self.__apply_groups)
        table = Table.from_pandas(df)
        return table

    def get_url(self, id, row=None):
        return f'{self._detection_url}?objID={row["objID"]}'

    def _table_to_light_curve(self, table):
        table = table[table['psfFlux'] > 0.0]

        table['mag'] = -2.5 * np.log10(table['psfFlux']) + 8.9
        table['magErr'] = 0.4 / np.log(10.0) * table['psfFluxErr'] / table['psfFlux']

        return [
            {
               'oid': row['objID'],
               'mjd': row['obsTime'],
               'mag': row['mag'],
               'magerr': row['magErr'],
               'filter': f'ps_{self._band_ids[row["filterID"]]}',
            }
            for row in table
        ]

    def light_curve(self, id, row=None):
        table = self._catalogs.query_criteria(objID=row['objID'], catalog='Panstarrs', data_release='dr2',
                                              table='detection')
        if len(table) == 0:
            raise NotFound
        return self._table_to_light_curve(table)

import logging
from itertools import count

import numpy as np
from astropy.table import Table
from astroquery.mast import Catalogs
from requests import RequestException

from ztf_viewer.catalogs.conesearch._base import _BaseCatalogQuery, _BaseLightCurveQuery, ValueWithIntervalColumn, ValueWithUncertaintyColumn
from ztf_viewer.exceptions import NotFound, CatalogUnavailable
from ztf_viewer.util import ABZPMAG_JY, LGE_25


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
        '_gPSFMag': 'g PSF mag',
        '_rPSFMag': 'r mag',
        '_iPSFMag': 'i mag',
        '_zPSFMag': 'z mag',
        '_yPSFMag': 'y mag',
    }

    _detection_url = 'https://catalogs.mast.stsci.edu/panstarrs/detections.html'

    _bands = 'grizy'
    _band_ids = dict(zip(count(1), _bands))
    _phot_types = ('Ap', 'PSF')

    _value_wirh_uncertanty_columns = [ ValueWithUncertaintyColumn(value=f'{b}PSFMag', uncertainty=f'{b}PSFMagErr') for b in _bands]

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
                if len(valid) == 0:
                    row[mag_column] = np.nan
                    row[err_column] = np.nan
                else:
                    w_ = 1.0 / np.square(valid[err_column])
                    row[mag_column] = np.average(valid[mag_column], weights=w_)
                    row[err_column] = 1.0 / np.sqrt(np.mean(w_))

        return row

    def _query_region(self, coord, radius):
        try:
            table = self._catalogs.query_region(coord, radius=radius, catalog='Panstarrs', data_release='dr2',
                                                table='stacked')
        except RequestException as e:
            logging.warning(e)
            raise CatalogUnavailable
        df = table.to_pandas()
        df = df[df['primaryDetection'] == 1]
        df = df.groupby('objID', sort=False).apply(self.__apply_groups)
        table = Table.from_pandas(df)
        return table

    def get_url(self, id, row=None):
        return f'{self._detection_url}?objID={row["objID"]}'

    def _table_to_light_curve(self, table):
        table = table[table['psfFlux'] > 0.0]

        table['mag'] = ABZPMAG_JY - 2.5 * np.log10(table['psfFlux'])
        table['magErr'] = LGE_25 * table['psfFluxErr'] / table['psfFlux']

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
        try:
            table = self._catalogs.query_criteria(objID=row['objID'], catalog='Panstarrs', data_release='dr2',
                                                  table='detection')
        except RequestException as e:
            logging.info(str(e))
            raise CatalogUnavailable
        if len(table) == 0:
            raise NotFound
        return self._table_to_light_curve(table)

import logging
from itertools import chain
from typing import Dict, Tuple

import pandas as pd
from alerce.core import Alerce
from astropy.table import Table
from requests import RequestException

from ztf_viewer.catalogs.conesearch._base import _BaseCatalogApiQuery


class AlerceQuery(_BaseCatalogApiQuery):
    _classifiers = ['stamp_classifier', 'lc_classifier']

    id_column = 'oid'
    type_column = 'class_stamp_classifier'
    _table_ra = 'meanra'
    _ra_unit = 'deg'
    _table_dec = 'meandec'
    columns = {
        '__link': 'oid',
        'separation': 'Separation, arcsec',
    } | dict(chain.from_iterable(
            [(f'class_{classifier}', f'Class by {classifier}'), (f'probability_{classifier}', 'Probability')]
            for classifier in _classifiers
        ))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._client = Alerce()

    def _get_classifications(self, id) -> Dict[str, Tuple[str, float]]:
        df = self._client.query_probabilities(id, format='pandas')
        df = df[df['ranking'] == 1]
        return {classifier: (df[df['classifier_name'] == classifier]['class_name'].iloc[0],
                             df[df['classifier_name'] == classifier]['probability'].iloc[0])
                for classifier in self._classifiers}


    def _query_region(self, coord, radius):
        ra = coord.ra.deg
        dec = coord.dec.deg
        if not (isinstance(radius, str) and radius.endswith('s')):
            raise ValueError('radius argument should be strings that ends with "s" letter')
        radius_arcsec = float(radius[:-1])
        df = self._client.query_objects(format='pandas', ra=ra, dec=dec, radius=radius_arcsec, page_size=128)
        for id in df['oid']:
            try:
                classifications = self._get_classifications(id)
            except RequestException as e:
                logging.warning(f'Failed to get classifications for {id}: {e}')
                continue
            except IndexError as e:
                logging.warning(f'Failed to get classifications from some classifier for {id}: {e}')
                continue
            for classifier, (class_, prob) in classifications.items():
                df.loc[df['oid'] == id, f'class_{classifier}'] = class_
                df.loc[df['oid'] == id, f'probability_{classifier}'] = prob
        table = Table.from_pandas(df)
        return table

    def get_url(self, id, row=None):
        return f'//alerce.online/object/{id}'

import logging
import packaging.version
from itertools import chain
from typing import Dict, Tuple

import pandas as pd
from alerce.core import Alerce
from astropy.table import Table
from requests import RequestException

from ztf_viewer.cache import cache
from ztf_viewer.catalogs.conesearch._base import _BaseCatalogApiQuery
from ztf_viewer.exceptions import NotFound


class AlerceQuery(_BaseCatalogApiQuery):
    _classifiers = {'Stamp': 'stamp_classifier', 'Light curve': 'lc_classifier'}

    id_column = 'oid'
    _table_ra = 'meanra'
    _ra_unit = 'deg'
    _table_dec = 'meandec'
    columns = {
        '__link': 'oid',
        'separation': 'Separation, arcsec',
    } | dict(chain.from_iterable(
            [(f'class_{classifier}', f'Class by {classifier}'), (f'probability_{classifier}', 'Probability')]
            for classifier in _classifiers.values()
        ))
    _prob_class_columns = {k: f'{v}_classifications' for k, v in _classifiers.items()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._client = Alerce()

    @staticmethod
    def __parse_classifier_version(s):
        # s is like 'stamp_classifier_1.0.4'
        _, s = s.rsplit('_', 1)
        return packaging.version.parse(s)

    @staticmethod
    def __aggregate_max_classifier_version(column):
        return max(column, key=AlerceQuery.__parse_classifier_version)

    @cache()
    def _get_classifications(self, alerce_id) -> pd.DataFrame:
        df = self._client.query_probabilities(alerce_id, format='pandas')
        # Get the highest versions of classifiers only
        highest_versions = df.groupby('classifier_name').aggregate(
            {'classifier_version': self.__aggregate_max_classifier_version},
        )
        highest_versions = highest_versions.set_index(['classifier_version'], append=True)
        df = df.join(highest_versions, on=['classifier_name', 'classifier_version'], how='inner')
        print(df)
        return df

    def _get_best_classifications(self, alerce_id) -> Dict[str, Tuple[str, float]]:
        df = self._get_classifications(alerce_id)
        df = df[df['ranking'] == 1]
        classifications = {}
        for classifier in self._classifiers.values():
            results = df[df['classifier_name'] == classifier]
            if results.empty:
                continue
            if results.shape[0] > 1:
                raise IndexError(f'More than one best classification for {alerce_id} from {classifier}')
            classifications[classifier] = (results['class_name'].iloc[0], results['probability'].iloc[0])
        return classifications

    def _query_region(self, coord, radius):
        ra = coord.ra.deg
        dec = coord.dec.deg
        if not (isinstance(radius, str) and radius.endswith('s')):
            raise ValueError('radius argument should be strings that ends with "s" letter')
        radius_arcsec = float(radius[:-1])
        df = self._client.query_objects(format='pandas', ra=ra, dec=dec, radius=radius_arcsec, page_size=128)
        if df.empty:
            raise NotFound
        for classifier in self._classifiers.values():
            df[f'class_{classifier}'] = ''
            df[f'probability_{classifier}'] = float('nan')
        for alerce_id in df['oid']:
            try:
                classifications = self._get_best_classifications(alerce_id)
            except RequestException as e:
                logging.warning(f'Failed to get classifications for {alerce_id}: {e}')
                continue
            except IndexError as e:
                logging.warning(f'Failed to get classifications from some classifier for {alerce_id}: {e}')
                continue
            for classifier, (class_, prob) in classifications.items():
                df.loc[df['oid'] == alerce_id, f'class_{classifier}'] = class_
                df.loc[df['oid'] == alerce_id, f'probability_{classifier}'] = prob
        table = Table.from_pandas(df)
        return table

    def add_prob_class_columns(self, table):
        for column in self._prob_class_columns.values():
            table[column] = [{} for _ in range(len(table))]
        for row in table:
            alerce_id = row['oid']
            try:
                df = self._get_classifications(alerce_id)
            except RequestException as e:
                logging.warning(f'Failed to get classifications for {alerce_id}: {e}')
                continue
            for pretty_name, classifier in self._classifiers.items():
                column = self._prob_class_columns[pretty_name]
                classifications = df[df['classifier_name'] == classifier][['class_name', 'probability']]
                row[column] = dict(row.to_list() for _index, row in classifications.iterrows())

    def get_url(self, id, row=None):
        return f'//alerce.online/object/{id}'

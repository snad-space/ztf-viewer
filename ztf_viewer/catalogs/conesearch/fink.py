from io import BytesIO
from urllib.parse import urljoin

import pandas as pd
from astropy.table import Table

from ztf_viewer.catalogs.conesearch._base import _BaseCatalogApiQuery


class FinkQuery(_BaseCatalogApiQuery):
    id_column = "i:objectId"
    _table_ra = "i:ra"
    _ra_unit = "deg"
    _table_dec = "i:dec"
    columns = {
        "__link": "Name",
        "separation": "Separation, arcsec",
        "v:classification": "Class",
        "d:mulens": "Prob to be a μLens",
        "d:rf_kn_vs_nonkn": "Prob of KN vs all",
        "d:rf_snia_vs_nonia": "Prob of SN Ia vs all",
        "d:snn_sn_vs_all": "Prob of SN vs all",
        "d:snn_snia_vs_nonia": "Prob of SN Ia vs CC SN",
    }

    _classifiers = {
        "μLens prob": "d:mulens",
        "RF KN vs all": "d:rf_kn_vs_nonkn",
        # 'RF SN Ia vs all': 'd:rf_snia_vs_nonia',             <- disabled because we decided to not show it
        "SuperNNova SN vs all": "d:snn_sn_vs_all",
        # 'SuperNNova SN Ia vs CC SN': 'd:snn_snia_vs_nonia',  <- disabled because we decided to not show it
    }
    _class_names = {
        "μLens prob": "μLens",
        "RF KN vs all": "KN",
        "SuperNNova SN vs all": "SN",
    }
    _prob_class_columns = {k: f"{v}_classifications" for k, v in _classifiers.items()}

    _base_url = "https://fink-portal.org/"
    _api_url = urljoin(_base_url, "/api/v1/explorer")

    def _api_query_region(self, ra, dec, radius_arcsec):
        params = {"ra": ra, "dec": dec, "radius": radius_arcsec}
        response = self._api_session.get(self._api_url, params=params, timeout=10)
        self._raise_if_not_ok(response)
        table = Table.from_pandas(pd.read_json(BytesIO(response.content)))
        return table

    def add_prob_class_columns(self, table):
        for column in self._prob_class_columns.values():
            table[column] = [{} for _ in range(len(table))]
        for row in table:
            for pretty_name, classifier in self._classifiers.items():
                column = self._prob_class_columns[pretty_name]
                class_name = self._class_names[pretty_name]
                if (prob := row[classifier]) is None:
                    continue
                row[column][class_name] = prob

    def get_url(self, id, row=None):
        return urljoin(self._base_url, id)

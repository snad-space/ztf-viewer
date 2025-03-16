from io import BytesIO
from urllib.parse import urljoin

import pandas as pd
from astropy.table import Table

from ztf_viewer.catalogs.conesearch._base import _BaseCatalogApiQuery
from ztf_viewer.exceptions import NotFound


class FinkQuery(_BaseCatalogApiQuery):
    id_column = "i:objectId"
    _table_ra = "i:ra"
    _ra_unit = "deg"
    _table_dec = "i:dec"
    columns = {
        "__link": "Name",
        "separation": "Separation, arcsec",
        "d:classification": "Class",
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
    _api_url = urljoin(_base_url, "/api/v1/conesearch")
    _api_url_objects = urljoin(_base_url, "/api/v1/objects")

    def _get_classifications(self, object_ids) -> pd.DataFrame:
        time_column = "i:jd"
        columns = [time_column, self.id_column] + list(c for c in self.columns if c.startswith("d:"))
        json_dict = {
            "objectId": ",".join(object_ids),
            "columns": ",".join(columns),
            "output-format": "json",
        }
        response = self._api_session.post(self._api_url_objects, json=json_dict, timeout=10)
        self._raise_if_not_ok(response)
        df = pd.read_json(BytesIO(response.content))
        # Select the latest classification for each object
        df = df.loc[df.groupby(self.id_column)[time_column].idxmin()]
        del df[time_column]
        return df.reset_index(drop=True)

    def _api_query_region(self, ra, dec, radius_arcsec):
        json_dict = {
            "ra": ra,
            "dec": dec,
            "radius": radius_arcsec,
            "output-format": "json",
        }
        response = self._api_session.post(self._api_url, json=json_dict, timeout=10)
        self._raise_if_not_ok(response)
        df = pd.read_json(BytesIO(response.content))
        if len(df) == 0:
            raise NotFound
        classifications = self._get_classifications(df[self.id_column])
        df = df.join(
            classifications.reset_index(drop=True).set_index(self.id_column),
            on=self.id_column,
            how="left",
        )
        return Table.from_pandas(df)

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

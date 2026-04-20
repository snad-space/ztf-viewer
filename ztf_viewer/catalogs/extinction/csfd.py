from dustmaps.csfd import CSFDQuery

from ztf_viewer.catalogs.extinction._base import _BaseExtinctionQuery
from ztf_viewer.exceptions import CatalogUnavailable


class CsfdQuery(_BaseExtinctionQuery):
    def __init__(self):
        super().__init__()
        self._query = None

    def _get_query(self):
        if self._query is None:
            try:
                self._query = CSFDQuery()
            except OSError as e:
                raise CatalogUnavailable(str(e)) from e
        return self._query

    def ebv(self, coord):
        return self._get_query()(coord)


csfd = CsfdQuery()

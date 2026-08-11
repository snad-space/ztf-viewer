from dustmaps.csfd import CSFDQuery

from ztf_viewer.catalogs.extinction._base import _BaseLocalExtinctionQuery


class CsfdQuery(_BaseLocalExtinctionQuery):
    def new_local_query(self):
        return CSFDQuery()

    def ebv(self, coord):
        return self.query(coord)


csfd = CsfdQuery()

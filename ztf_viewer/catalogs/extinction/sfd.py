from dustmaps.sfd import SFDQuery as LocalQuery
from dustmaps.sfd import SFDWebQuery as WebQuery

from ztf_viewer.catalogs.extinction._base import _BaseLocalRemoteExtinctionQuery


class SfdQuery(_BaseLocalRemoteExtinctionQuery):
    def __init__(self):
        super().__init__()
        self._web_query = WebQuery()

    def web_query(self, coord):
        return self._web_query(coord)

    def new_local_query(self):
        return LocalQuery()

    def ebv(self, coord):
        return self.query(coord)


sfd = SfdQuery()

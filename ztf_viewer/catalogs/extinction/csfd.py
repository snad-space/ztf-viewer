from ztf_viewer.catalogs.extinction._base import _BaseApiExtinctionQuery
from ztf_viewer.config import DUSTMAPS_API_URL


class CsfdQuery(_BaseApiExtinctionQuery):
    # CSFD (Chiang 2023)
    url = f"{DUSTMAPS_API_URL}/api/v1/csfd"

    async def ebv(self, coord):
        icrs = coord.icrs
        return await self.query({"ra": icrs.ra.deg, "dec": icrs.dec.deg})


csfd = CsfdQuery()

from abc import ABC, abstractmethod
from typing import ClassVar

import httpx

from ztf_viewer import config
from ztf_viewer.exceptions import CatalogUnavailable
from ztf_viewer.http import get_client


class _BaseExtinctionQuery(ABC):
    # http://svo2.cab.inta-csic.es/svo/theory/fps3/index.php?mode=browse&gname=Palomar&gname2=ZTF&asttype=
    af2av: ClassVar = {
        "zg": 1.21,
        "zr": 0.848,
        "zi": 0.622,
    }
    r = 3.1

    async def __call__(self, coord):
        av = self.r * await self.ebv(coord)
        return {band: av * af2av for band, af2av in self.af2av.items()}

    @abstractmethod
    async def ebv(self, coord):
        raise NotImplementedError


class _BaseApiExtinctionQuery(_BaseExtinctionQuery):
    # https://dustmaps.snad.space
    url: str

    async def query(self, params):
        client = get_client()
        try:
            response = await client.get(self.url, params=params, timeout=config.TIMEOUT_EXTINCTION)
            response.raise_for_status()
            ebv = response.json()["ebv"]
        except httpx.HTTPError as e:
            raise CatalogUnavailable(str(e)) from e
        if ebv is None:
            raise CatalogUnavailable(f"{self.url} has no data for the given coordinates")
        return ebv

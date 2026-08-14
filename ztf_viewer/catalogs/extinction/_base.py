from abc import ABC, abstractmethod
from typing import ClassVar

import requests

from ztf_viewer.exceptions import CatalogUnavailable


class _BaseExtinctionQuery(ABC):
    # http://svo2.cab.inta-csic.es/svo/theory/fps3/index.php?mode=browse&gname=Palomar&gname2=ZTF&asttype=
    af2av: ClassVar = {
        "zg": 1.21,
        "zr": 0.848,
        "zi": 0.622,
    }
    r = 3.1

    def __call__(self, coord):
        av = self.r * self.ebv(coord)
        return {band: av * af2av for band, af2av in self.af2av.items()}

    @abstractmethod
    def ebv(self, coord):
        raise NotImplementedError


class _BaseApiExtinctionQuery(_BaseExtinctionQuery):
    # https://dustmaps.snad.space
    url: str

    def __init__(self):
        self._api_session = requests.Session()

    def query(self, params):
        try:
            response = self._api_session.get(self.url, params=params, timeout=10)
            response.raise_for_status()
            ebv = response.json()["ebv"]
        except requests.RequestException as e:
            raise CatalogUnavailable(str(e)) from e
        if ebv is None:
            raise CatalogUnavailable(f"{self.url} has no data for the given coordinates")
        return ebv

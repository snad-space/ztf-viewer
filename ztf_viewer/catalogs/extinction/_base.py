from abc import ABC, abstractmethod

import requests


class _BaseExtinctionQuery(ABC):
    # http://svo2.cab.inta-csic.es/svo/theory/fps3/index.php?mode=browse&gname=Palomar&gname2=ZTF&asttype=
    af2av = {
        'zg': 1.21,
        'zr': 0.848,
        'zi': 0.622,
    }
    r = 3.1

    def __call__(self, coord):
        av = self.r * self.ebv(coord).item()
        return {band: av * af2av for band, af2av in self.af2av.items()}

    @abstractmethod
    def ebv(self, coord):
        raise NotImplemented


class _BaseLocalRemoteExtinctionQuery(_BaseExtinctionQuery):
    def __init__(self):
        super().__init__()
        self.local_query = None

    @abstractmethod
    def new_local_query(self):
        raise NotImplemented

    @abstractmethod
    def web_query(self, coord):
        raise NotImplemented

    def query(self, coord):
        if self.local_query is None:
            try:
                return self.web_query(coord)
            except requests.exceptions.RequestException:
                self.local_query = self.new_local_query()
        return self.local_query(coord)

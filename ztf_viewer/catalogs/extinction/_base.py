from abc import ABC, abstractmethod

from ztf_viewer.exceptions import CatalogUnavailable


class _BaseExtinctionQuery(ABC):
    # http://svo2.cab.inta-csic.es/svo/theory/fps3/index.php?mode=browse&gname=Palomar&gname2=ZTF&asttype=
    af2av = {
        "zg": 1.21,
        "zr": 0.848,
        "zi": 0.622,
    }
    r = 3.1

    def __call__(self, coord):
        av = self.r * self.ebv(coord).item()
        return {band: av * af2av for band, af2av in self.af2av.items()}

    @abstractmethod
    def ebv(self, coord):
        raise NotImplementedError


class _BaseLocalExtinctionQuery(_BaseExtinctionQuery):
    # We used to fall back to web queries, but argonaut.skymaps.info is gone
    def __init__(self):
        super().__init__()
        self.local_query = None

    @abstractmethod
    def new_local_query(self):
        raise NotImplementedError

    def query(self, coord):
        if self.local_query is None:
            try:
                self.local_query = self.new_local_query()
            except OSError as e:
                raise CatalogUnavailable(str(e)) from e
        return self.local_query(coord)

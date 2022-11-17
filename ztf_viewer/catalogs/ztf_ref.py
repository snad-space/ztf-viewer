import logging
from pathlib import Path

import numpy as np
import requests
from astropy.io import fits

from ztf_viewer.cache import cache
from ztf_viewer.catalogs import find_ztf_oid
from ztf_viewer.config import ZTF_FITS_PROXY_URL
from ztf_viewer.exceptions import NotFound
from ztf_viewer.util import ccdid_from_rcid, qid_from_rcid


class ZTFRef:
    _base_fits_url = f"{ZTF_FITS_PROXY_URL}"
    _base_path = "/products/ref/"

    def __init__(self):
        self._api_session = requests.Session()

    def fits_url(self, oid, dr):
        meta = find_ztf_oid.get_meta(oid, dr)
        if meta["fieldid"] < 1000:
            root = "000"
        else:
            root = "001"
        ccdid = ccdid_from_rcid(meta["rcid"])
        qid = qid_from_rcid(meta["rcid"])
        path = Path(self._base_path).joinpath(
            root,
            f'field{meta["fieldid"]:06d}',
            meta["filter"],
            f"ccd{ccdid:02d}",
            f"q{qid}",
            f'ztf_{meta["fieldid"]:06d}_{meta["filter"]}_c{ccdid:02d}_q{qid}_refpsfcat.fits',
        )
        return f"{self._base_fits_url}{path}"

    @cache()
    def get(self, oid, dr):
        url = self.fits_url(oid, dr)
        sourceid = int(oid) % 10_000_000
        with fits.open(url) as f:
            header = f[0].header
            data = f[1].data
            where = np.where(data["sourceid"] == sourceid)[0]
            if where.size == 0:
                logging.warning(f"Object {oid} is not found in the reference catalog file {url}")
                raise NotFound
            idx = where.item()
            record = dict(zip(data.names, data[idx]))
            record["magzp"] = header["MAGZP"]
            record["magzp_rms"] = header["MAGZPRMS"]
            record["infobits"] = header["INFOBITS"]

        return record


ztf_ref = ZTFRef()

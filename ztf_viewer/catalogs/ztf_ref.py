import asyncio
import logging

logger = logging.getLogger(__name__)
from io import BytesIO
from pathlib import Path

import httpx
import numpy as np
from astropy.io import fits

from ztf_viewer.cache import cache
from ztf_viewer.catalogs import find_ztf_oid
from ztf_viewer.config import TIMEOUT_ZTF_FITS_PROXY, ZTF_FITS_PROXY_URL
from ztf_viewer.exceptions import CatalogUnavailable, NotFound
from ztf_viewer.http import get_client
from ztf_viewer.util import ccdid_from_rcid, qid_from_rcid


def _parse_fits(data: bytes, url: str, sourceid: int) -> dict:
    """Parse the reference-catalog FITS payload and pull out the row for `sourceid`."""
    with fits.open(BytesIO(data)) as f:
        header = f[0].header
        table = f[1].data
        where = np.where(table["sourceid"] == sourceid)[0]
        if where.size == 0:
            logger.warning(f"Object with sourceid={sourceid} is not found in the reference catalog file {url}")
            raise NotFound
        idx = where.item()
        record = dict(zip(table.names, table[idx]))
        record["magzp"] = header["MAGZP"]
        record["magzp_rms"] = header["MAGZPRMS"]
        record["infobits"] = header["INFOBITS"]
    return record


class ZTFRef:
    _base_fits_url = f"{ZTF_FITS_PROXY_URL}"
    _base_path = "/products/ref/"

    async def fits_url(self, oid, dr):
        meta = await find_ztf_oid.get_meta(oid, dr)
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
    async def get(self, oid, dr):
        url = await self.fits_url(oid, dr)
        sourceid = int(oid) % 10_000_000
        client = get_client()
        try:
            response = await client.get(url, timeout=TIMEOUT_ZTF_FITS_PROXY)
            response.raise_for_status()
        except httpx.HTTPStatusError:
            raise NotFound
        except httpx.RequestError:
            raise CatalogUnavailable
        return await asyncio.to_thread(_parse_fits, response.content, url, sourceid)


ztf_ref = ZTFRef()

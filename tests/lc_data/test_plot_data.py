"""`get_plot_data`'s fan-out over the current OID, neighbour OIDs and external light curves.

The three groups of upstream calls (the current OID's ZTF light curve, each neighbour OID's, and
each external source's -- antares/gaia/panstarrs) are independent of one another and are now
gathered concurrently. These tests pin that the fan-out actually overlaps in wall time and that a
failure in one upstream still propagates (nothing here swallows exceptions).
"""

import asyncio
import time
from unittest.mock import patch

import pytest

from ztf_viewer.lc_data import plot_data as plot_data_module

DELAY = 0.2


async def test_get_plot_data_fanout_is_concurrent():
    other_oids = frozenset(["2", "3", "4"])

    async def fake_ztf_dr_lc(oid, dr):
        await asyncio.sleep(DELAY)
        return [{"mjd": 58000.0, "mag": 18.0, "magerr": 0.05, "filter": "zg", "oid": oid}]

    async def fake_external(oid, dr, **kwargs):
        await asyncio.sleep(DELAY)
        return [{"mjd": 58000.0, "mag": 18.0, "magerr": 0.05, "filter": "zg", "oid": oid}]

    with (
        patch.object(plot_data_module, "ztf_dr_lc", fake_ztf_dr_lc),
        patch.dict(plot_data_module.EXTERNAL_LC_DATA, {"antares": fake_external}, clear=True),
    ):
        start = time.perf_counter()
        await plot_data_module.get_plot_data.__wrapped__(
            "1", "dr24", other_oids=other_oids, external_data={"antares": {}}
        )
        elapsed = time.perf_counter() - start
    # Serial (1 current + 3 neighbours + 1 external) would take 5 * DELAY.
    assert elapsed < 5 * DELAY / 2


async def test_get_plot_data_propagates_upstream_failure():
    async def fake_ztf_dr_lc(oid, dr):
        if oid == "2":
            raise ValueError("neighbour upstream boom")
        return [{"mjd": 58000.0, "mag": 18.0, "magerr": 0.05, "filter": "zg", "oid": oid}]

    with patch.object(plot_data_module, "ztf_dr_lc", fake_ztf_dr_lc):
        with pytest.raises(ValueError, match="neighbour upstream boom"):
            await plot_data_module.get_plot_data.__wrapped__("1", "dr24", other_oids=frozenset(["2"]))

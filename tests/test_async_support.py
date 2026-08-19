"""That ``async def test_`` runs at all — the floor the rest of the async migration stands on.

The ``network`` marker's behaviour under coroutines is covered in ``test_network_marker.py``.
"""

import asyncio

import pytest

_OID = 633207400004730
_DR = "dr24"


async def test_async_tests_are_collected_and_awaited():
    """No marker, no fixture, no event-loop boilerplate — ``asyncio_mode = "auto"`` does it."""
    await asyncio.sleep(0)
    assert asyncio.get_running_loop() is not None


@pytest.mark.network
async def test_ztf_dr_find_is_awaited():
    """A plain first-party network call, awaited directly."""
    from ztf_viewer.catalogs.ztf_dr import find_ztf_oid

    meta = await find_ztf_oid.find(_OID, _DR)

    assert "lc" in meta
    assert "meta" in meta

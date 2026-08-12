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
def test_ztf_dr_find_sync():
    """The sync half of the pair: a plain first-party network call."""
    from ztf_viewer.catalogs.ztf_dr import find_ztf_oid

    meta = find_ztf_oid.find(_OID, _DR)

    assert "lc" in meta
    assert "meta" in meta


@pytest.mark.network
async def test_ztf_dr_find_async_matches_sync():
    """`to_thread` is the shim the async migration leans on — assert it agrees."""
    from ztf_viewer.catalogs.ztf_dr import find_ztf_oid

    from_sync = find_ztf_oid.find(_OID, _DR)
    from_async = await asyncio.to_thread(find_ztf_oid.find, _OID, _DR)

    assert from_async == from_sync

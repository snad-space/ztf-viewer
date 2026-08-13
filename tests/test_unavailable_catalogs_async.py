"""The async accessor added to `unavailable_catalogs.py`.

Inert: nothing in the app calls `unavailable_catalogs_async` yet, so this only checks the
accessor is wired up and, for the memory backend, that it shares state with the sync one.

``ztf_viewer.catalogs.unavailable_catalogs`` connects to Redis eagerly at import time (see
``tests/test_golden_http.py``'s ``dash_app`` fixture docstring for the same wart), so the module
must not be imported until ``pytest_runtest_setup`` has forced ``UNAVAILABLE_CATALOGS_CACHE_TYPE``
to ``"memory"`` — hence the import is inside the test rather than at module level.
"""

from ztf_viewer.ttl_set import AsyncLocalTTLSet


async def test_memory_backend_shares_state_with_the_sync_accessor() -> None:
    from ztf_viewer.catalogs.unavailable_catalogs import unavailable_catalogs, unavailable_catalogs_async

    assert isinstance(unavailable_catalogs_async, AsyncLocalTTLSet), "test config forces the memory backend"
    unavailable_catalogs.add("some-catalog")
    assert await unavailable_catalogs_async.contains("some-catalog")
    unavailable_catalogs.discard("some-catalog")

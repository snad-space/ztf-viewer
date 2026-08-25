"""`_size_thread_pools` sizes BOTH the loop's default executor and anyio's sync-route limiter
from `THREAD_POOL_SIZE`, not just one of them.

They are two independent pools reached by two different code paths -- `asyncio.to_thread` hits
the executor, Starlette's sync route handlers hit the limiter -- so sizing only one is an easy
way for them to silently drift apart, one left at a stdlib default while config says otherwise.
This does not assert anything about what the size should be, only that both pools actually track
the one configured value.
"""

import asyncio

import anyio.to_thread

from tests.conftest import reset_shared_thread_pool


async def test_size_thread_pools_installs_the_configured_pool_and_limiter() -> None:
    reset_shared_thread_pool()

    import ztf_viewer.__main__ as main_module

    await main_module._size_thread_pools()

    loop = asyncio.get_running_loop()
    assert loop._default_executor is main_module._thread_pool
    assert main_module._thread_pool._max_workers == main_module.THREAD_POOL_SIZE
    assert anyio.to_thread.current_default_thread_limiter().total_tokens == main_module.THREAD_POOL_SIZE

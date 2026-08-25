"""The event loop's default executor and anyio's sync-route limiter are actually sized from
`THREAD_POOL_SIZE`.

`ztf_viewer/__main__.py`'s `_size_thread_pools` startup hook is the one place the plan's
threading rule says pool sizes get decided (`plans/001_async_dash.md`, "Shape of the work"). This
pins that it really does what it claims -- both `asyncio.to_thread` and anyio's sync-route
threads reach a pool sized from config, not a stdlib default -- rather than asserting anything
about what that size *should be*, which is the open question `plans/misc/pool_width_bench.py`
explores instead.
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

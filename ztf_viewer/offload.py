"""Bounded thread offload for third-party clients that stay synchronous by design.

`astroquery` (Vizier, Simbad, MOCServer, Skybot, Gaia), `alerce.core.Alerce` and
`antares_client.search` are not being ported to async I/O. They still have to run off the event
loop, via `asyncio.to_thread`, but a bare `asyncio.to_thread` call shares one pool
(`config.THREAD_POOL_SIZE`) with every other offloaded call in the process. One slow or hanging
upstream could fill that whole pool and stall catalogs that have nothing to do with it. Each
upstream therefore gets its own `asyncio.Semaphore`, sized from `config.UPSTREAM_THREAD_LIMITS`,
bounding how many of the shared pool's slots it can hold at once.

The semaphore is loop-affine like every other `asyncio.Semaphore` in this app, so it is obtained
through `LoopRegistry` rather than as a module-level singleton.
"""

import asyncio
import threading
from typing import Callable, Optional, TypeVar

from ztf_viewer import config
from ztf_viewer.loop_registry import LoopRegistry

_T = TypeVar("_T")

_registries: dict[str, LoopRegistry[asyncio.Semaphore]] = {}
_registries_lock = threading.Lock()


def _semaphore_registry(upstream: str) -> LoopRegistry[asyncio.Semaphore]:
    """One `LoopRegistry` per upstream name, built on first use and kept for the process.

    The registry itself lives for the process; the semaphore it hands out is per-loop, and its
    size is read from `config.UPSTREAM_THREAD_LIMITS` at the moment a given loop first asks for
    one, not cached any earlier -- so changing the config before a fresh loop starts changes the
    limit that loop gets.
    """
    with _registries_lock:
        registry = _registries.get(upstream)
        if registry is None:
            registry = _registries[upstream] = LoopRegistry(
                lambda upstream=upstream: asyncio.Semaphore(config.UPSTREAM_THREAD_LIMITS[upstream])
            )
        return registry


async def to_thread(upstream: Optional[str], func: Callable[..., _T], *args, **kwargs) -> _T:
    """Run `func` in a thread, bounded by `upstream`'s semaphore.

    `upstream=None` falls back to a bare `asyncio.to_thread`: nothing in this app calls it that
    way today, but it keeps `_ensure_coroutine`'s old behaviour available for a call site that
    has not been sorted into an upstream bucket yet.
    """
    if upstream is None:
        return await asyncio.to_thread(func, *args, **kwargs)
    semaphore = _semaphore_registry(upstream).get()
    async with semaphore:
        return await asyncio.to_thread(func, *args, **kwargs)

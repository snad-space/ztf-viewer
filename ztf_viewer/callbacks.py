"""Registration-layer shim: every callback registered here is a coroutine function.

Dash's FastAPI backend runs a synchronous callback inline on the event loop with no
threadpool hop, so leaving any callback as a plain ``def`` would serialize the whole app onto
one loop per worker. Dash only checks ``inspect.iscoroutinefunction`` at registration time, so
wrapping here is enough to satisfy that constraint without touching a single callback body.
"""

import asyncio
import functools
import inspect
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ztf_viewer.app import app

#: Matches gunicorn's ``--threads=8`` (Dockerfile) so the offload pool can't outgrow prod.
MAX_WORKERS = 8

_executor = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="callback-offload")


def _to_coroutine_function(func: Callable[..., Any]) -> Callable[..., Any]:
    """Return `func` unchanged if it is already a coroutine function, else offload it to a thread."""
    if inspect.iscoroutinefunction(func):
        return func

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        # Idempotent, and the only reliable hook: Flask gives each request a fresh loop.
        asyncio.get_running_loop().set_default_executor(_executor)
        return await asyncio.to_thread(func, *args, **kwargs)

    return wrapper


def callback(*args: Any, **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Drop-in replacement for ``app.callback`` that always registers a coroutine function."""

    def register(func: Callable[..., Any]) -> Callable[..., Any]:
        return app.callback(*args, **kwargs)(_to_coroutine_function(func))

    return register

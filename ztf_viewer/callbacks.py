"""Registration-layer shim: every callback registered here is a coroutine function.

Dash's FastAPI backend runs a synchronous callback inline on the event loop with no threadpool
hop, so leaving any callback as a plain ``def`` would serialize the whole app onto one loop per
worker. Dash only checks ``inspect.iscoroutinefunction`` at registration time, so wrapping here
is enough to satisfy that constraint without touching a single callback body.

The wrapper runs the callback **inline**, on the thread that awaits it — today the gunicorn
worker thread, exactly as before this shim existed. Offloading it to a thread pool is what the
FastAPI backend will need, and it is deliberately not done here: a pool needs a size, a size
needs one configured home, and neither exists until the backend flip introduces them together.
"""

import functools
import inspect
from collections.abc import Callable
from typing import Any

from ztf_viewer.app import app


def _to_coroutine_function(func: Callable[..., Any]) -> Callable[..., Any]:
    """Return `func` unchanged if it is already a coroutine function, else wrap it into one."""
    if inspect.iscoroutinefunction(func):
        return func

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    return wrapper


def callback(*args: Any, **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Drop-in replacement for ``app.callback`` that always registers a coroutine function."""

    def register(func: Callable[..., Any]) -> Callable[..., Any]:
        return app.callback(*args, **kwargs)(_to_coroutine_function(func))

    return register

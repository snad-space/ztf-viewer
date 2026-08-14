"""A registry for loop-affine resources — clients, pools, locks — bound to whichever
asyncio event loop is running when they are first requested.

Flask's async callback dispatch runs each request through its own fresh event loop
(``asgiref.async_to_sync``); FastAPI keeps one loop per worker for its whole lifetime. Anything
bound to a loop at construction time — a ``redis.asyncio`` pool, an ``httpx.AsyncClient``, an
``asyncio.Lock`` — breaks the moment it is reused from a different loop. The fix is to build such
resources lazily, keyed by ``asyncio.get_running_loop()``, one instance per loop.

Keying on ``id(loop)`` would be a bug: ids are recycled once a loop is garbage collected, so a
brand-new loop can silently inherit a dead loop's entry. Keying the table on the loop object
itself, held only weakly, sidesteps this: identity, not a reused integer, decides equality, and
the entry disappears on its own once nothing else holds the loop — which is exactly when Flask
drops it after a request. ``discard()`` exists for callers that want that deterministic rather
than GC-timed.

No lock is needed around the body that runs after ``get()`` returns: only one task runs at a
time per loop, so two tasks on the *same* loop can never race to create two resources for that
loop. But the table is shared across loops that may live on different threads (Flask spins up
its per-request loop on a gunicorn worker thread), so mutating the shared dict itself still
needs a plain ``threading.Lock`` — an ``asyncio.Lock`` would itself be loop-affine and defeat
the purpose.
"""

import asyncio
import threading
import weakref
from typing import Callable, Generic, Optional, TypeVar

_T = TypeVar("_T")


class LoopRegistry(Generic[_T]):
    """One instance of a loop-affine resource per running event loop.

    ``factory`` is called with no arguments to build a fresh resource; it must not do anything
    that only makes sense on a particular loop until :meth:`get` actually calls it.
    """

    def __init__(self, factory: Callable[[], _T]):
        self._factory = factory
        self._entries: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, _T]" = weakref.WeakKeyDictionary()
        self._registry_lock = threading.Lock()

    def get(self) -> _T:
        loop = asyncio.get_running_loop()
        with self._registry_lock:
            resource = self._entries.get(loop)
            if resource is None:
                resource = self._entries[loop] = self._factory()
        return resource

    def discard(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        """Drop the entry for `loop` (the running loop by default), if any."""
        if loop is None:
            loop = asyncio.get_running_loop()
        with self._registry_lock:
            self._entries.pop(loop, None)

    def __len__(self) -> int:
        return len(self._entries)

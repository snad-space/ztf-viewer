"""A registry for loop-affine resources — clients, pools, locks — bound to whichever
asyncio event loop is running when they are first requested.

Flask's async callback dispatch runs each request through its own fresh event loop
(``asgiref.async_to_sync``); FastAPI keeps one loop per worker for its whole lifetime. Anything
bound to a loop at construction time — a ``redis.asyncio`` pool, an ``httpx.AsyncClient``, an
``asyncio.Lock`` — breaks the moment it is reused from a different loop. The fix is to build such
resources lazily, keyed by ``asyncio.get_running_loop()``, one instance per loop.

Keying on ``id(loop)`` would be a bug: ids are recycled once a loop is garbage collected, so a
brand-new loop can silently inherit a dead loop's entry. Keying the table on the loop object
itself, held only weakly, sidesteps this — identity, not a reused integer, decides equality.

**Weak keys alone do not reclaim entries, which is why :meth:`get` sweeps.** A
``WeakKeyDictionary`` holds its values strongly, so any value that references its own loop keeps
its own key alive: a connected ``redis.asyncio`` client reaches its loop through
``transport._loop``, and that entry then survives every collection — five successive
``asyncio.run`` calls left five entries before the sweep existed. Values that hold nothing, an
``asyncio.Lock`` or a plain ``dict``, were reclaimed even without it. A closed loop is never
coming back, so dropping its entry on the next lookup bounds the table by the number of live
loops, whatever the value happens to reference. ``discard()`` drops one entry immediately.

Cleaning up *after* a loop is gone is not an option worth designing toward: ``aclose()`` needs a
live loop, ``transport.close()`` raises ``RuntimeError: Event loop is closed``, and a
``weakref.finalize`` on the loop cannot help either — holding the resource to close it later is
exactly what keeps the loop alive, so the finalizer never runs until interpreter exit. A resource
is closed on its own loop, while that loop still runs, or it is left to the garbage collector.

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
            self._sweep()
            resource = self._entries.get(loop)
            if resource is None:
                resource = self._entries[loop] = self._factory()
        return resource

    def _sweep(self) -> None:
        """Drop entries whose loop is closed. Call with the lock held.

        A value that references its own loop keeps its key alive, so weak keys alone never
        reclaim it. Closedness is the signal weakness cannot provide.
        """
        for loop in [loop for loop in list(self._entries) if loop.is_closed()]:
            del self._entries[loop]

    def discard(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        """Drop the entry for `loop` (the running loop by default), if any."""
        if loop is None:
            loop = asyncio.get_running_loop()
        with self._registry_lock:
            self._entries.pop(loop, None)

    def __len__(self) -> int:
        return len(self._entries)

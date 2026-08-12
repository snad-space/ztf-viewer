"""Single-flight dedupe: N concurrent identical cache misses become one call to the wrapped
function, not N.

Both implementations are the same shape — the leader resolves a future, the followers read it —
over the two kinds of concurrency: threads (``concurrent.futures.Future``) and tasks within one
event loop (``asyncio.Future``). Asyncio futures are loop-affine, so a leader in one loop can
never share its future with a waiter in another; that table is keyed by loop, a stand-in for a
per-loop registry a later change will retrofit onto this (as with the async cache backends).

In both implementations a leader that raises propagates that same exception object to every
waiter — including a leader whose own task was cancelled: cancellation is just the leader's
exception in this scheme, never a reason to leave the followers hanging.
"""

import asyncio
import threading
import weakref
from concurrent.futures import Future


class SingleFlight:
    """Coalesce concurrent calls under the same key onto one thread's call."""

    def __init__(self):
        self._lock = threading.Lock()
        self._inflight = {}

    def run(self, key, compute):
        owner = threading.get_ident()
        with self._lock:
            entry = self._inflight.get(key)
            leader = entry is None
            if leader:
                fut = Future()
                self._inflight[key] = (fut, owner)
            else:
                fut, leader_owner = entry
                if leader_owner == owner:
                    raise RuntimeError("cached call re-entered itself under the same key; this would deadlock")

        if not leader:
            # Blocks until the leader resolves it, then returns its value or raises its exception.
            return fut.result()

        try:
            value = compute()
        # BaseException, not Exception: a KeyboardInterrupt here must still release the waiters.
        except BaseException as e:
            fut.set_exception(e)
            raise
        else:
            fut.set_result(value)
            return value
        finally:
            with self._lock:
                del self._inflight[key]


class AsyncSingleFlight:
    """Coalesce concurrent calls under the same key onto one task's call, within one loop."""

    def __init__(self):
        self._tables = weakref.WeakKeyDictionary()
        self._registry_lock = threading.Lock()

    def _table(self) -> dict:
        loop = asyncio.get_running_loop()
        # threading.Lock, not asyncio: the WeakKeyDictionary itself is shared across threads, one loop each.
        with self._registry_lock:
            table = self._tables.get(loop)
            if table is None:
                table = self._tables[loop] = {}
        return table

    async def run(self, key, compute):
        table = self._table()
        task = asyncio.current_task()
        entry = table.get(key)
        if entry is not None:
            fut, owner = entry
            if task is not None and owner is task:
                raise RuntimeError("cached call re-entered itself under the same key; this would deadlock")
            # shield: a *waiter's* own cancellation must not reach the shared future and take
            # the leader (and every other waiter) down with it.
            return await asyncio.shield(fut)

        # No `await` between the lookup above and this insert, so — one task runs at a time per
        # loop — nothing else can race to become leader for this key.
        fut = asyncio.get_running_loop().create_future()
        table[key] = (fut, task)
        try:
            value = await compute()
        # BaseException, not Exception: CancelledError is one, and waiters would hang without it.
        except BaseException as e:
            fut.set_exception(e)
            fut.exception()  # mark retrieved: a leader with no waiters must not warn on gc
            raise
        else:
            fut.set_result(value)
            return value
        finally:
            del table[key]

"""Rate limiters that keep outbound queries to a single upstream inside its published policy.

Two shapes, because upstreams publish two different kinds of limit:

* :class:`AsyncRateLimiter` — a **pace**: at most ``max_calls`` per ``period``, spread evenly.
  For a policy worded as a rate ("no more than 8 queries in the same second"), where the window
  is short and going over it is what gets a client blacklisted.
* :class:`AsyncCallQuota` — a **budget**: at most ``max_calls`` per rolling ``period``, spent in
  whatever pattern the traffic happens to take. For a policy worded as an allowance ("100
  requests per day"), where the window is far longer than any request can wait.

Both raise :class:`RateLimitTimeout` for a caller that would have to wait longer than its budget
allows, and :meth:`ztf_viewer.catalogs.conesearch._base._BaseCatalogQuery._wait_for_rate_limit`
turns that into a shed query. Which of the two a catalog wants is a property of the upstream's
policy, so the choice lives next to that catalog — see ``conesearch/simbad.py`` (a pace) and
``conesearch/colibri.py`` (a budget).

Some upstreams publish a query-rate policy and blacklist callers who ignore it. SIMBAD asks for
no more than 8 queries in the same second and answers an over-eager client with an HTML page
saying it is (temporarily) blacklisted, which arrives as a parse failure rather than as anything
recognisable — see http://simbad.u-strasbg.fr/guide/sim-url.htx. A cap we impose on ourselves is
cheaper than that.

**Even spacing, not a burst allowance.** A limiter that admits ``max_calls`` at once and then
waits out the period does keep to the cap by our own clock, but it sends the whole allowance in
a single millisecond: measured here, a 20-call burst went out as 8 requests at once, 8 more a
second later, and 4 after that. Two such bursts either side of a one-second boundary are only a
few milliseconds of network jitter away from arriving inside one second on SIMBAD's clock, which
is the clock that matters. Admitting one call every ``period / max_calls`` instead keeps any
window of ``period`` to ``max_calls`` calls however the two clocks are aligned, and never opens
``max_calls`` connections to the upstream at the same instant. It costs nothing in the case that
actually happens: a viewer page makes *one* cone search per catalog, so a lone user never waits
at all, and only concurrent users pace each other.

**Slots are reserved at arrival, not polled for.** :meth:`AsyncRateLimiter.acquire` computes the
instant its caller may go, claims it under the lock, and sleeps until then. So callers are served
strictly in arrival order and each one sleeps exactly once, where a retry-until-free loop would
instead wake every waiter on every freed slot and hand the slot to whichever one the event loop
happened to resume first.

**One limiter per upstream per process, not per event loop.** Unlike an ``httpx.AsyncClient`` or
an ``asyncio.Lock`` (see :mod:`ztf_viewer.loop_registry`), nothing here is loop-affine: the state
is a single ``float`` guarded by a ``threading.Lock``, and the waiting happens with
``asyncio.sleep`` on whichever loop the caller is already running. A process-wide limiter is
therefore both correct from any loop and strictly closer to the upstream's real limit than one
limiter per loop would be.

That correctness stops at the process boundary. The deployed entrypoint runs uvicorn with
``--workers 1``, so one process is the whole deployment today; scaling to N workers would allow N
times the rate and would need the schedule in shared storage (Redis) instead.
"""

import asyncio
import threading
import time
from collections import deque


class RateLimitTimeout(Exception):
    """The next free slot is further away than the caller is willing to wait."""


class AsyncRateLimiter:
    """Admits at most ``max_calls`` acquisitions per ``period``, spaced evenly.

    Args:
        max_calls: how many acquisitions one ``period`` may contain.
        period: length of that window, in seconds.
        max_wait: how long :meth:`acquire` may put a caller to sleep before giving up with
            :class:`RateLimitTimeout` instead. ``None`` waits however long the queue demands,
            which only suits a caller with no deadline of its own — a web request has one, so its
            call site should pass a budget.
    """

    def __init__(self, max_calls: int, period: float = 1.0, max_wait: float | None = None):
        if max_calls < 1:
            raise ValueError("max_calls must be at least 1")
        if period <= 0:
            raise ValueError("period must be positive")
        self._max_calls = max_calls
        self._period = period
        self._max_wait = max_wait
        self._min_interval = period / max_calls
        # When the next call may go out. `-inf` rather than the current time so that a limiter
        # nobody has used yet never delays its first caller, however long ago it was built.
        self._next_slot = float("-inf")
        # A plain threading.Lock, not an asyncio one: an asyncio.Lock belongs to the loop that
        # created it, and this limiter is shared across every loop in the process. The critical
        # section contains no await, so it can never be held across a suspension point.
        self._lock = threading.Lock()

    @property
    def max_calls(self) -> int:
        return self._max_calls

    @property
    def period(self) -> float:
        return self._period

    @property
    def min_interval(self) -> float:
        """Shortest gap between two consecutive calls, in seconds."""
        return self._min_interval

    async def acquire(self, max_wait: float | None = None) -> float:
        """Wait for this call's slot, and return how long that took, in seconds.

        ``max_wait`` overrides the constructor's budget for this one call. A caller that would go
        over budget raises :class:`RateLimitTimeout` *without* claiming a slot, so shedding it
        costs the callers behind it nothing. A caller cancelled while waiting gives its slot back
        the same way — see :meth:`_release`.
        """
        if max_wait is None:
            max_wait = self._max_wait

        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next_slot)
            wait = slot - now
            if max_wait is not None and wait > max_wait:
                raise RateLimitTimeout(
                    f"next slot is {wait:.1f}s away, over the {max_wait:.1f}s budget "
                    f"({self._max_calls} calls per {self._period:.1f}s)"
                )
            self._next_slot = slot + self._min_interval

        if wait > 0:
            try:
                await asyncio.sleep(wait)
            except asyncio.CancelledError:
                self._release(slot)
                raise
        return wait

    def _release(self, slot):
        """Give back a slot reserved by a caller that never used it.

        Cancellation here is routine, not exceptional: `get_summary` cancels every catalog query
        still in flight when a viewer's websocket goes away, which is what happens each time
        someone navigates off a page. Without this, each of those abandoned queries would leave
        its reservation standing, and the schedule would run further and further ahead of the
        queries actually being sent — until a genuine request is told the queue is deeper than
        its budget and shed, on behalf of users who left.

        Only the *last* reservation can be given back. Once a later caller has taken its slot
        relative to ours, ours is load-bearing: moving the schedule back under it would let the
        two go out closer together than the rate allows. Leaving that one standing is safe in the
        direction that matters — the upstream sees fewer queries than the cap, never more.
        """
        with self._lock:
            if self._next_slot == slot + self._min_interval:
                self._next_slot = slot


class AsyncCallQuota:
    """Admits at most ``max_calls`` acquisitions in any window of ``period``, in any pattern.

    A budget rather than a pace. Astro-COLIBRI grants each registered user 100 cone searches a
    day (https://astro-colibri.science/apidoc), which is not a statement about how fast queries
    may be sent: spacing them evenly would put every call 864 seconds behind the last and leave a
    lone user waiting a quarter of an hour for a catalog nobody else asked for that day, while
    still spending exactly the same 100 calls. So this one lets traffic spend the allowance at
    whatever rate it arrives, and refuses only once the allowance is actually gone.

    That refusal, not a wait, is the point. ``max_wait`` therefore defaults to ``0.0`` here where
    :class:`AsyncRateLimiter` defaults to no limit: the next free slot in a day-long window is
    typically hours away, and a web request that waited for it would be answering a user who
    left long ago. Shedding immediately at least tells the page the catalog is unavailable while
    someone is still there to read it.

    The window is a rolling one — the slot spent by the first call of the day comes back exactly
    ``period`` after that call, not at a fixed daily reset the upstream never promised.

    Shares :class:`AsyncRateLimiter`'s process-wide scope and its threading lock, for the reasons
    in this module's docstring; the same caveat about multiple worker processes applies, plus one
    of its own. A quota is spent per *account*, and a restart forgets what this process spent:
    both are cases of the upstream's counter running ahead of ours, so ``max_calls`` is better
    read as our own ceiling than as a guarantee about the upstream's ledger.

    Args:
        max_calls: how many acquisitions one rolling ``period`` may contain.
        period: length of that window, in seconds.
        max_wait: how long :meth:`acquire` may put a caller to sleep before giving up with
            :class:`RateLimitTimeout` instead. ``None`` waits however long the window demands.
    """

    def __init__(self, max_calls: int, period: float, max_wait: float | None = 0.0):
        if max_calls < 1:
            raise ValueError("max_calls must be at least 1")
        if period <= 0:
            raise ValueError("period must be positive")
        self._max_calls = max_calls
        self._period = period
        self._max_wait = max_wait
        # When each admitted call is considered sent, oldest first. Entries older than one period
        # are dropped on the next acquisition, so this holds `max_calls` of them plus one per
        # caller currently asleep waiting for a slot.
        self._slots: deque[float] = deque()
        self._lock = threading.Lock()

    @property
    def max_calls(self) -> int:
        return self._max_calls

    @property
    def period(self) -> float:
        return self._period

    async def acquire(self, max_wait: float | None = None) -> float:
        """Spend one call from the budget, and return how long that took, in seconds.

        Returns ``0.0`` while the allowance holds, which is the whole of the normal case. Once it
        is gone, the wait is until the oldest call in the window falls out of it, and with the
        default ``max_wait`` that raises :class:`RateLimitTimeout` rather than sleeping.
        """
        if max_wait is None:
            max_wait = self._max_wait

        with self._lock:
            now = time.monotonic()
            # Calls that have fallen out of the window no longer count against it. Only ever
            # from the left: `_slots` is sorted (see below), so the first entry still inside the
            # window ends the pruning.
            while self._slots and self._slots[0] <= now - self._period:
                self._slots.popleft()

            if len(self._slots) < self._max_calls:
                slot = now
            else:
                # The window is full, so this call has to wait for the oldest of the `max_calls`
                # most recent ones to leave it. Counted from the right rather than taking
                # `_slots[0]`, because entries reserved by callers already asleep are in here
                # too, and they are what the next slot has to be measured against.
                slot = self._slots[-self._max_calls] + self._period
            wait = slot - now
            if max_wait is not None and wait > max_wait:
                raise RateLimitTimeout(
                    f"the {self._max_calls}-call budget for the last {self._period:.0f}s is spent; "
                    f"the next slot is {wait:.0f}s away, over the {max_wait:.0f}s budget"
                )
            # `slot` is never earlier than `_slots[-1]`, so appending keeps the deque sorted:
            # it is either `now` (which only grows) or a full window's worth after an entry that
            # is itself no earlier than the one `max_calls` before the end.
            self._slots.append(slot)

        if wait > 0:
            try:
                await asyncio.sleep(wait)
            except asyncio.CancelledError:
                self._release(slot)
                raise
        return wait

    def _release(self, slot: float) -> None:
        """Give back a slot reserved by a caller that never sent its query.

        Unlike :meth:`AsyncRateLimiter._release`, this is unconditional: dropping an entry can
        only ever let a later call go *earlier*, never sooner than the window allows, because
        every remaining entry keeps the position it was given. Only the last entry can be ours —
        a later caller would have appended after it.
        """
        with self._lock:
            if self._slots and self._slots[-1] == slot:
                self._slots.pop()

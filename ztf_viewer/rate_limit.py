"""A rate limiter that paces outbound queries to a single upstream.

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
        costs the callers behind it nothing.
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
            await asyncio.sleep(wait)
        return wait

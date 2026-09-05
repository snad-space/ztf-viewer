"""Coverage for :mod:`ztf_viewer.rate_limit` and its one call site in the cone-search base class.

A rate limiter is awkward to test without either sleeping for a realistic period or reaching
into its internals, so every timing assertion here is written as a **lower bound on elapsed
time** (``asyncio.sleep`` may overshoot, never undershoot) or as an assertion about the
``wait`` value :meth:`AsyncRateLimiter.acquire` computes and returns, which is exact. Nothing
asserts that an operation finished *quickly*, which is what would make these flaky on a loaded
CI runner.

Periods here are a fraction of a second rather than SIMBAD's one second: the limiter has no
notion of what its period means, and the whole file then runs in well under a second.

Anything under ``ztf_viewer.catalogs`` is imported inside the test that needs it, never at module
level: importing that package pulls in ``catalogs.unavailable_catalogs``, which connects to Redis
eagerly at import time, and at collection time ``pytest_runtest_setup`` has not yet forced the
memory backend. See ``tests/test_unavailable_catalogs_async.py`` for the same wart.
"""

import asyncio
import importlib
import time

import pytest

from ztf_viewer.config import SIMBAD_MAX_QUERIES_PER_SECOND
from ztf_viewer.exceptions import CatalogUnavailable
from ztf_viewer.rate_limit import AsyncRateLimiter, RateLimitTimeout

PERIOD = 0.2


async def test_an_idle_limiter_does_not_delay_its_first_caller():
    """The case that actually happens: one page, one cone search, nobody else querying."""
    limiter = AsyncRateLimiter(max_calls=3, period=PERIOD)

    assert await limiter.acquire() == 0.0


async def test_no_window_holds_more_than_max_calls():
    """The property the SIMBAD policy is worded as: a count per unit time.

    Calls are spaced by ``period / max_calls``, so call ``k`` cannot come back before
    ``k * period / max_calls`` has elapsed — which is exactly ``max_calls`` calls per period, and
    keeps to that in *every* window rather than only in windows aligned to a burst. It is a lower
    bound on elapsed time, so a loaded runner can only overshoot it.
    """
    max_calls = 3
    limiter = AsyncRateLimiter(max_calls=max_calls, period=PERIOD)

    start = time.monotonic()
    elapsed = []
    for _ in range(2 * max_calls):
        await limiter.acquire()
        elapsed.append(time.monotonic() - start)

    for k, seconds in enumerate(elapsed):
        assert seconds >= k * PERIOD / max_calls, f"call {k} was let through too early"


async def test_calls_are_spread_rather_than_sent_as_one_burst():
    """The whole allowance leaving at once is what a burst-tolerant window would do.

    That keeps to the cap by our clock while still putting two full bursts a few milliseconds of
    jitter away from sharing one second on the upstream's clock.
    """
    limiter = AsyncRateLimiter(max_calls=4, period=PERIOD)

    waits = [await limiter.acquire() for _ in range(4)]

    assert waits[0] == 0.0
    assert all(wait > 0 for wait in waits[1:]), "every call after the first must be paced"


async def test_waiters_are_served_in_arrival_order():
    """Slots are reserved when a caller arrives, so a burst keeps its order.

    A retry-until-free limiter would instead wake every waiter whenever a slot frees up and hand
    it to whichever one the loop resumed first, starving an unlucky caller under sustained load.
    """
    limiter = AsyncRateLimiter(max_calls=2, period=PERIOD)
    served = []

    async def call(n):
        await limiter.acquire()
        served.append(n)

    # Tasks start in creation order, and `acquire` reserves its slot before its first await.
    await asyncio.gather(*(asyncio.create_task(call(n)) for n in range(6)))

    assert served == list(range(6))


async def test_over_budget_call_is_shed():
    limiter = AsyncRateLimiter(max_calls=1, period=PERIOD)

    await limiter.acquire()

    with pytest.raises(RateLimitTimeout):
        await limiter.acquire(max_wait=0.0)


async def test_constructor_budget_applies_when_acquire_gets_none():
    limiter = AsyncRateLimiter(max_calls=1, period=PERIOD, max_wait=0.0)

    await limiter.acquire()

    with pytest.raises(RateLimitTimeout):
        await limiter.acquire()


async def test_shed_call_does_not_reserve_a_slot():
    """Shedding a caller must cost the callers behind it nothing.

    Had the timed-out call kept its reservation, the next one would be scheduled a further
    period out — so a wait no longer than one period is what proves the slot was released.
    """
    limiter = AsyncRateLimiter(max_calls=1, period=PERIOD)
    await limiter.acquire()

    for _ in range(3):
        with pytest.raises(RateLimitTimeout):
            await limiter.acquire(max_wait=0.0)

    wait = await limiter.acquire()
    assert 0.0 < wait <= PERIOD


def test_window_is_shared_across_event_loops():
    """One limiter per upstream per process — not per loop, unlike a loop-affine resource.

    Flask's async dispatch runs each request on its own fresh loop (see
    :mod:`ztf_viewer.loop_registry`), which would give a per-loop limiter a fresh, empty window
    for every request and no limiting at all.

    A long period with a zero budget keeps this deterministic: the second loop is refused
    whatever it did with the wall clock between the two runs, and nothing sleeps.
    """
    limiter = AsyncRateLimiter(max_calls=1, period=60.0)

    asyncio.run(limiter.acquire())

    with pytest.raises(RateLimitTimeout):
        asyncio.run(limiter.acquire(max_wait=0.0))


@pytest.mark.parametrize(("max_calls", "period"), [(0, 1.0), (-1, 1.0), (1, 0.0), (1, -1.0)])
def test_rejects_a_limit_that_admits_nothing(max_calls, period):
    with pytest.raises(ValueError):
        AsyncRateLimiter(max_calls=max_calls, period=period)


def test_simbad_is_the_catalog_that_is_limited():
    """SIMBAD is the only upstream with a published policy today (issue #51).

    The period matters as much as the count: the policy is "8 queries in the same second", so a
    limiter of 8 over anything but one second would not be that policy.
    """
    from ztf_viewer.catalogs.conesearch import SIMBAD_QUERY

    assert SIMBAD_QUERY._rate_limiter is not None
    assert SIMBAD_QUERY._rate_limiter.max_calls == SIMBAD_MAX_QUERIES_PER_SECOND
    assert SIMBAD_QUERY._rate_limiter.period == 1.0


@pytest.fixture
def make_catalog():
    """Build throwaway `_BaseCatalogQuery` subclasses, and take them back out of the registry.

    ``_BaseCatalogQuery.__new__`` files every instance ever built under its query name in a
    class-level dict, and that dict *is* the catalog list: `catalog_query_objects()` walks it to
    decide what a viewer page cross-matches against. A test catalog left behind there shows up
    in another test's summary section, so this hands the names back at teardown.
    """
    from ztf_viewer.catalogs.conesearch._base import _BaseCatalogQuery

    registry = _BaseCatalogQuery._BaseCatalogQuery__objects
    created = []

    def make(name, rate_limiter=None):
        class Query(_BaseCatalogQuery):
            _rate_limiter = rate_limiter

        Query.__name__ = Query.__qualname__ = name
        created.append(_BaseCatalogQuery._normalize_name(name))
        return Query(name)

    yield make

    for name in created:
        registry.pop(name, None)


async def test_catalog_without_a_rate_limiter_never_waits(make_catalog):
    """Every catalog but SIMBAD, and the reason `find()` may call this unconditionally."""
    catalog = make_catalog("test-catalog-unlimited")

    assert await catalog._wait_for_rate_limit() is None


async def test_catalog_query_waits_for_its_slot(make_catalog):
    catalog = make_catalog("test-catalog-limited", AsyncRateLimiter(max_calls=1, period=PERIOD))

    start = time.monotonic()
    await catalog._wait_for_rate_limit()
    await catalog._wait_for_rate_limit()

    assert time.monotonic() - start >= PERIOD


async def test_shed_query_is_unavailable_but_not_prolongated(make_catalog, monkeypatch):
    """A queue too deep to join says nothing about whether the upstream is healthy.

    ``prolongate=True`` would add the catalog to the shared unavailable set for five minutes, so
    one burst of traffic would take SIMBAD off every page — including the pages that would have
    hit the cache instead of the upstream.
    """
    added = []
    # By module object, not by dotted string: `ztf_viewer.catalogs` re-exports the *set* under
    # the module's own name, and monkeypatch's string form resolves that attribute first.
    module = importlib.import_module("ztf_viewer.catalogs.unavailable_catalogs")
    monkeypatch.setattr(module, "unavailable_catalogs", type("FakeSet", (), {"add": added.append})())
    catalog = make_catalog("test-catalog-shedding", AsyncRateLimiter(max_calls=1, period=PERIOD, max_wait=0.0))
    await catalog._wait_for_rate_limit()

    with pytest.raises(CatalogUnavailable):
        await catalog._wait_for_rate_limit()

    assert added == []

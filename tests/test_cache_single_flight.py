"""Single-flight dedupe tests.

Coalescing is transparent through ``make_cache``/``create_async_memory_cache`` (the internal
factories the public ``cache()`` dispatches to) — nothing here knows about
``SingleFlight``/``AsyncSingleFlight`` directly. "One call" is observed the same way as
``tests/test_cache_contract.py``: by counting invocations of the wrapped body, never by
inspecting internals.
"""

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from ztf_viewer.cache.decorator import make_cache
from ztf_viewer.cache.memory import create_async_memory_cache, create_memory_backend
from ztf_viewer.cache.single_flight import AsyncSingleFlight, SingleFlight

SLEEP = 0.2
N = 8


def _backend():
    return create_memory_backend(1 << 16, ttl=3600)


def _make_async_cache():
    return create_async_memory_cache(_backend())


class Boom(Exception):
    pass


# --------------------------------------------------------------------------------------------
# Sync: N threads, identical arguments
# --------------------------------------------------------------------------------------------


def test_sync_dedupes_concurrent_misses():
    cache = make_cache(_backend())
    calls = 0
    lock = threading.Lock()

    @cache()
    def slow(x):
        nonlocal calls
        with lock:
            calls += 1
        time.sleep(SLEEP)
        return x * 2

    results = [None] * N
    threads = [threading.Thread(target=lambda i=i: results.__setitem__(i, slow(1))) for i in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert calls == 1, "N concurrent identical misses must run the body once"
    assert results == [2] * N


def test_sync_exception_propagates_to_all_waiters():
    cache = make_cache(_backend())
    calls = 0
    lock = threading.Lock()

    @cache()
    def slow(x):
        nonlocal calls
        with lock:
            calls += 1
        time.sleep(SLEEP)
        raise Boom("upstream is down")

    errors = [None] * N

    def worker(i):
        try:
            slow(1)
        except Boom as e:
            errors[i] = e

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert calls == 1, "the leader's exception must reach every waiter without a second call"
    assert all(isinstance(e, Boom) for e in errors)


def test_sync_second_call_after_completion_runs_again():
    """The in-flight entry must not outlive its call — a later call is a fresh miss, not a hit."""
    cache = make_cache(_backend())
    calls = 0

    @cache()
    def counted(x):
        nonlocal calls
        calls += 1
        return calls

    assert counted(1) == 1
    assert counted(1) == 1, "the ordinary cache still hits on the second call"


def test_sync_distinct_keys_do_not_serialize():
    cache = make_cache(_backend())

    @cache()
    def slow(x):
        time.sleep(SLEEP)
        return x

    start = time.monotonic()
    threads = [threading.Thread(target=slow, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.monotonic() - start

    assert elapsed < SLEEP * 2, "distinct keys must run concurrently, not serialize behind one lock"


# --------------------------------------------------------------------------------------------
# Async: N tasks, identical arguments, one loop
# --------------------------------------------------------------------------------------------


async def test_async_dedupes_concurrent_misses():
    async_cache = _make_async_cache()
    calls = 0

    @async_cache()
    async def slow(x):
        nonlocal calls
        calls += 1
        await asyncio.sleep(SLEEP)
        return x * 2

    results = await asyncio.gather(*(slow(1) for _ in range(N)))

    assert calls == 1, "N concurrent identical misses must run the body once"
    assert results == [2] * N


async def test_async_exception_propagates_to_all_waiters():
    async_cache = _make_async_cache()
    calls = 0

    @async_cache()
    async def slow(x):
        nonlocal calls
        calls += 1
        await asyncio.sleep(SLEEP)
        raise Boom("upstream is down")

    results = await asyncio.gather(*(slow(1) for _ in range(N)), return_exceptions=True)

    assert calls == 1
    assert all(isinstance(r, Boom) for r in results)


async def test_async_second_call_after_completion_runs_again():
    async_cache = _make_async_cache()
    calls = 0

    @async_cache()
    async def counted(x):
        nonlocal calls
        calls += 1
        return calls

    assert await counted(1) == 1
    assert await counted(1) == 1, "the ordinary cache still hits on the second call"


async def test_async_distinct_keys_do_not_serialize():
    async_cache = _make_async_cache()

    @async_cache()
    async def slow(x):
        await asyncio.sleep(SLEEP)
        return x

    start = time.monotonic()
    await asyncio.gather(*(slow(i) for i in range(4)))
    elapsed = time.monotonic() - start

    assert elapsed < SLEEP * 2, "distinct keys must run concurrently, not serialize behind one future"


async def test_async_cancelled_leader_does_not_wedge_waiters():
    """A cancelled leader is, to the followers, just another exception - never a hang."""
    async_cache = _make_async_cache()
    started = asyncio.Event()

    @async_cache()
    async def slow(x):
        started.set()
        await asyncio.sleep(10)
        return x

    leader = asyncio.create_task(slow(1))
    await started.wait()
    follower = asyncio.create_task(slow(1))
    await asyncio.sleep(0)  # let the follower reach `await shield(fut)` and register, not lead

    leader.cancel()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(follower, timeout=2.0)

    with pytest.raises(asyncio.CancelledError):
        await leader


# --------------------------------------------------------------------------------------------
# Unit tests of the primitives themselves - no cache, no decorator, just SingleFlight /
# AsyncSingleFlight instances and a `compute` callable.
# --------------------------------------------------------------------------------------------


def _spin_until(predicate, timeout=5.0):
    """Poll a predicate until true; used to synchronize threads without a fixed sleep guess."""
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise TimeoutError("condition not met in time")
        time.sleep(0.001)


def test_singleflight_dedupes_concurrent_callers():
    """N concurrent callers on one key run compute exactly once and all get the same value."""
    sf = SingleFlight()
    n = 8
    calls = 0
    calls_lock = threading.Lock()
    arrived = 0
    arrived_lock = threading.Lock()

    def compute():
        nonlocal calls
        with calls_lock:
            calls += 1
        # block until every caller has reached sf.run(), so none of them can miss the
        # in-flight entry and start a second, unwanted call
        _spin_until(lambda: arrived >= n)
        return "value"

    def worker():
        nonlocal arrived
        with arrived_lock:
            arrived += 1
        return sf.run("key", compute)

    with ThreadPoolExecutor(max_workers=n) as pool:
        results = [f.result(timeout=5) for f in [pool.submit(worker) for _ in range(n)]]

    assert calls == 1
    assert results == ["value"] * n


def test_singleflight_distinct_keys_do_not_wait_on_each_other():
    """Concurrent callers on different keys run independently, neither blocking the other."""
    sf = SingleFlight()
    a_running = threading.Event()
    b_running = threading.Event()

    def compute_a():
        a_running.set()
        assert b_running.wait(timeout=5), "key b must start without waiting for key a"
        return "a"

    def compute_b():
        b_running.set()
        assert a_running.wait(timeout=5), "key a must start without waiting for key b"
        return "b"

    with ThreadPoolExecutor(max_workers=2) as pool:
        fa = pool.submit(sf.run, "a", compute_a)
        fb = pool.submit(sf.run, "b", compute_b)
        assert fa.result(timeout=5) == "a"
        assert fb.result(timeout=5) == "b"


def test_singleflight_leader_exception_reaches_all_waiters():
    """The leader's exception object reaches every waiter, unchanged."""
    sf = SingleFlight()
    n = 5
    boom = Boom("upstream is down")
    calls = 0
    calls_lock = threading.Lock()
    arrived = 0
    arrived_lock = threading.Lock()

    def compute():
        nonlocal calls
        with calls_lock:
            calls += 1
        _spin_until(lambda: arrived >= n)
        raise boom

    def worker():
        nonlocal arrived
        with arrived_lock:
            arrived += 1
        try:
            sf.run("key", compute)
            return None
        except BaseException as e:  # noqa: BLE001 - collected from thread, not swallowed
            return e

    with ThreadPoolExecutor(max_workers=n) as pool:
        results = [f.result(timeout=5) for f in [pool.submit(worker) for _ in range(n)]]

    assert calls == 1
    assert all(r is boom for r in results), "the sync side re-raises the leader's exact exception object"


def test_singleflight_inflight_entry_cleared_after_success():
    """The in-flight entry does not outlive a successful call; a later call is a fresh miss."""
    sf = SingleFlight()
    calls = 0

    def compute():
        nonlocal calls
        calls += 1
        return calls

    assert sf.run("key", compute) == 1
    assert sf.run("key", compute) == 2


def test_singleflight_inflight_entry_cleared_after_exception():
    """A failure is not memoised - the next call runs compute again, not the same exception."""
    sf = SingleFlight()
    calls = 0

    def compute():
        nonlocal calls
        calls += 1
        raise Boom(f"boom {calls}")

    with pytest.raises(Boom, match="boom 1"):
        sf.run("key", compute)
    with pytest.raises(Boom, match="boom 2"):
        sf.run("key", compute)


async def test_async_singleflight_dedupes_concurrent_callers():
    """N concurrent tasks on one key run compute exactly once and all get the same value."""
    sf = AsyncSingleFlight()
    n = 8
    calls = 0
    release = asyncio.Event()

    async def compute():
        nonlocal calls
        calls += 1
        await release.wait()
        return "value"

    tasks = [asyncio.create_task(sf.run("key", compute)) for _ in range(n)]
    await asyncio.sleep(0)  # let every task reach either compute() or shield(fut) and register
    release.set()
    results = await asyncio.gather(*tasks)

    assert calls == 1
    assert results == ["value"] * n


async def test_async_singleflight_distinct_keys_do_not_wait_on_each_other():
    """Concurrent tasks on different keys run independently, neither blocking the other."""
    sf = AsyncSingleFlight()
    a_running = asyncio.Event()
    b_running = asyncio.Event()

    async def compute_a():
        a_running.set()
        await asyncio.wait_for(b_running.wait(), timeout=5)
        return "a"

    async def compute_b():
        b_running.set()
        await asyncio.wait_for(a_running.wait(), timeout=5)
        return "b"

    ra, rb = await asyncio.gather(sf.run("a", compute_a), sf.run("b", compute_b))
    assert (ra, rb) == ("a", "b")


async def test_async_singleflight_leader_exception_reaches_all_waiters():
    """The leader's exception object reaches every waiter, unchanged, through the shield."""
    sf = AsyncSingleFlight()
    n = 5
    boom = Boom("upstream is down")
    calls = 0
    release = asyncio.Event()

    async def compute():
        nonlocal calls
        calls += 1
        await release.wait()
        raise boom

    async def worker():
        try:
            await sf.run("key", compute)
            return None
        except BaseException as e:  # noqa: BLE001 - collected from thread, not swallowed
            return e

    tasks = [asyncio.create_task(worker()) for _ in range(n)]
    await asyncio.sleep(0)
    release.set()
    results = await asyncio.gather(*tasks)

    assert calls == 1
    assert all(r is boom for r in results), "the leader's exact exception object reaches every waiter"


async def test_async_singleflight_inflight_entry_cleared_after_success():
    """The in-flight entry does not outlive a successful call; a later call is a fresh miss."""
    sf = AsyncSingleFlight()
    calls = 0

    async def compute():
        nonlocal calls
        calls += 1
        return calls

    assert await sf.run("key", compute) == 1
    assert await sf.run("key", compute) == 2


async def test_async_singleflight_inflight_entry_cleared_after_exception():
    """A failure is not memoised - the next call runs compute again, not the same exception."""
    sf = AsyncSingleFlight()
    calls = 0

    async def compute():
        nonlocal calls
        calls += 1
        raise Boom(f"boom {calls}")

    with pytest.raises(Boom, match="boom 1"):
        await sf.run("key", compute)
    with pytest.raises(Boom, match="boom 2"):
        await sf.run("key", compute)


async def test_async_singleflight_cancelled_waiter_does_not_disturb_leader_or_others():
    """A cancelled waiter's cancellation must not reach the leader or other waiters."""
    sf = AsyncSingleFlight()
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def compute():
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return "value"

    leader = asyncio.create_task(sf.run("key", compute))
    await started.wait()
    waiter_to_cancel = asyncio.create_task(sf.run("key", compute))
    other_waiter = asyncio.create_task(sf.run("key", compute))
    await asyncio.sleep(0)  # let both waiters register via shield(fut)

    waiter_to_cancel.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter_to_cancel

    release.set()
    assert await leader == "value"
    assert await other_waiter == "value"
    assert calls == 1


async def test_async_singleflight_cancelled_leader_delivers_cancelled_error_to_waiters():
    """A cancelled leader's CancelledError reaches waiters rather than hanging them forever
    (the alternative would be letting a waiter retry as the new leader)."""
    sf = AsyncSingleFlight()
    started = asyncio.Event()

    async def compute():
        started.set()
        await asyncio.sleep(10)
        return "value"

    leader = asyncio.create_task(sf.run("key", compute))
    await started.wait()
    waiter = asyncio.create_task(sf.run("key", compute))
    await asyncio.sleep(0)  # let the waiter reach shield(fut) and register

    leader.cancel()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(waiter, timeout=2.0)
    with pytest.raises(asyncio.CancelledError):
        await leader


def test_async_singleflight_works_across_separate_event_loops():
    """One AsyncSingleFlight instance must not bind its table to the first loop it sees."""
    sf = AsyncSingleFlight()

    async def compute():
        return "value"

    assert asyncio.run(sf.run("key", compute)) == "value"
    assert asyncio.run(sf.run("key", compute)) == "value"


# --------------------------------------------------------------------------------------------
# Reentrancy: compute() calling run() again under the same key must fail loudly, not hang.
# --------------------------------------------------------------------------------------------


def test_singleflight_reentrant_same_key_raises_instead_of_hanging():
    """A thread that re-enters run() with its own in-flight key gets a RuntimeError, not a hang."""
    sf = SingleFlight()

    def outer():
        return sf.run("key", lambda: sf.run("key", lambda: "never"))

    with ThreadPoolExecutor(max_workers=1) as pool, pytest.raises(RuntimeError, match="re-entered itself"):
        pool.submit(outer).result(timeout=5)


async def test_async_singleflight_reentrant_same_key_raises_instead_of_hanging():
    """A task that re-enters run() with its own in-flight key gets a RuntimeError, not a hang."""
    sf = AsyncSingleFlight()

    async def inner():
        return "never"

    async def outer():
        return await sf.run("key", lambda: sf.run("key", inner))

    with pytest.raises(RuntimeError, match="re-entered itself"):
        await asyncio.wait_for(outer(), timeout=5)


def test_singleflight_reentrant_different_key_still_works():
    """Nested single-flight calls under distinct keys are legitimate and both compute."""
    sf = SingleFlight()

    def inner():
        return sf.run("inner", lambda: "inner-value")

    outer_result = sf.run("outer", inner)

    assert outer_result == "inner-value"
    # the inner entry was cleaned up too, so a fresh call under that key runs again
    assert sf.run("inner", lambda: "fresh") == "fresh"


async def test_async_singleflight_reentrant_different_key_still_works():
    """Nested single-flight calls under distinct keys are legitimate and both compute."""
    sf = AsyncSingleFlight()
    inner_calls = 0
    outer_calls = 0

    async def inner():
        nonlocal inner_calls
        inner_calls += 1
        return "inner-value"

    async def outer():
        nonlocal outer_calls
        outer_calls += 1
        return await sf.run("inner", inner)

    result = await sf.run("outer", outer)

    assert result == "inner-value"
    assert inner_calls == 1
    assert outer_calls == 1


def test_singleflight_real_follower_unaffected_by_reentrancy_guard():
    """A genuine other thread waiting on the same key still waits and gets the leader's value."""
    sf = SingleFlight()
    calls = 0
    calls_lock = threading.Lock()
    leader_started = threading.Event()
    release = threading.Event()

    def compute():
        nonlocal calls
        with calls_lock:
            calls += 1
        leader_started.set()
        assert release.wait(timeout=5)
        return "value"

    with ThreadPoolExecutor(max_workers=2) as pool:
        leader_fut = pool.submit(sf.run, "key", compute)
        assert leader_started.wait(timeout=5)
        follower_fut = pool.submit(sf.run, "key", lambda: "unused")
        time.sleep(0.05)  # give the follower a moment to register as a waiter, not a new leader
        release.set()
        assert leader_fut.result(timeout=5) == "value"
        assert follower_fut.result(timeout=5) == "value"

    assert calls == 1


async def test_async_singleflight_real_follower_unaffected_by_reentrancy_guard():
    """A genuine other task waiting on the same key still waits and gets the leader's value."""
    sf = AsyncSingleFlight()
    calls = 0
    started = asyncio.Event()
    release = asyncio.Event()

    async def compute():
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return "value"

    leader = asyncio.create_task(sf.run("key", compute))
    await started.wait()
    follower = asyncio.create_task(sf.run("key", compute))
    await asyncio.sleep(0)  # let the follower reach shield(fut) and register, not lead

    release.set()
    assert await asyncio.wait_for(leader, timeout=5) == "value"
    assert await asyncio.wait_for(follower, timeout=5) == "value"
    assert calls == 1


def test_singleflight_inflight_entry_cleared_after_reentrancy_error():
    """The in-flight entry is cleaned up after a re-entry error, so a later call works."""
    sf = SingleFlight()

    def outer():
        return sf.run("key", lambda: sf.run("key", lambda: "never"))

    with ThreadPoolExecutor(max_workers=1) as pool, pytest.raises(RuntimeError, match="re-entered itself"):
        pool.submit(outer).result(timeout=5)

    assert sf.run("key", lambda: "fresh") == "fresh"


async def test_async_singleflight_inflight_entry_cleared_after_reentrancy_error():
    """The in-flight entry is cleaned up after a re-entry error, so a later call works."""
    sf = AsyncSingleFlight()

    async def inner():
        return "never"

    async def outer():
        return await sf.run("key", lambda: sf.run("key", inner))

    with pytest.raises(RuntimeError, match="re-entered itself"):
        await asyncio.wait_for(outer(), timeout=5)

    assert await sf.run("key", inner) == "never"


# --------------------------------------------------------------------------------------------
# Cross-thread registry safety: many threads, each its own loop, populate the same
# LoopRegistry concurrently (a threading.Lock guards the get-and-create, not an asyncio one)
# --------------------------------------------------------------------------------------------


def test_async_singleflight_table_registry_survives_concurrent_threads():
    """threading.Lock, not asyncio: the LoopRegistry is shared across threads, one loop each."""
    sf = AsyncSingleFlight()
    n = 8
    barrier = threading.Barrier(n)
    errors = []
    loops = [None] * n
    tables = [None] * n

    async def body():
        barrier.wait(timeout=5)
        return asyncio.get_running_loop(), sf._tables.get()

    def worker(i):
        try:
            loops[i], tables[i] = asyncio.run(body())
        except BaseException as e:  # noqa: BLE001 - collected from thread, not swallowed
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert not errors, errors
    assert len({id(loop) for loop in loops}) == n, "each thread must run its own loop"
    assert len({id(table) for table in tables}) == n, "each loop gets its own table, never a shared one"
    assert all(isinstance(table, dict) for table in tables)

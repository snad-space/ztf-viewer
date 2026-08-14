"""Tests for the per-loop resource registry."""

import asyncio
import gc

from ztf_viewer.loop_registry import LoopRegistry


def test_not_created_at_construction() -> None:
    """Building the registry must not call the factory."""
    calls = []
    LoopRegistry(lambda: calls.append(1))
    assert calls == []


def test_two_successive_asyncio_run_calls_both_get_a_resource() -> None:
    """Simulates Flask's per-request event loop: each `asyncio.run()` call gets a fresh
    resource, and using it does not raise even though the first loop is long closed."""
    registry = LoopRegistry(object)

    async def body():
        resource = registry.get()
        assert resource is registry.get()  # same loop, same call: reused within the request
        return resource

    first = asyncio.run(body())
    second = asyncio.run(body())
    assert first is not second


def test_single_long_lived_loop_reuses_one_instance() -> None:
    """Simulates FastAPI's one-loop-per-worker model: repeated `get()` calls on the same
    running loop return the same instance."""
    registry = LoopRegistry(object)

    async def body():
        return registry.get(), registry.get()

    first, second = asyncio.run(body())
    assert first is second


def test_cleanup_drops_entries_via_gc() -> None:
    """When nothing else holds the loop, the weak entry disappears on its own."""
    registry = LoopRegistry(object)

    async def body():
        registry.get()

    asyncio.run(body())
    gc.collect()
    assert len(registry) == 0


def test_discard_drops_the_entry_immediately() -> None:
    """`discard()` is the deterministic counterpart to relying on garbage collection."""
    registry = LoopRegistry(object)

    async def body():
        registry.get()
        assert len(registry) == 1
        registry.discard()
        assert len(registry) == 0

    asyncio.run(body())


def test_concurrent_tasks_on_the_same_loop_share_one_resource() -> None:
    """Two tasks on the same loop calling `get()` concurrently must not create two resources."""
    calls = []

    def factory():
        calls.append(1)
        return object()

    registry = LoopRegistry(factory)

    async def worker():
        return registry.get()

    async def body():
        first, second = await asyncio.gather(worker(), worker())
        return first, second

    first, second = asyncio.run(body())
    assert first is second
    assert calls == [1]

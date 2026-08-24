"""Tests for the process-wide CPU-bound offload pool.

Kept small and self-contained: `_small_pool` caps `PROCESS_POOL_SIZE` and resets the module's
singleton around every test, so tests do not see each other's pool and spawn is not asked to
build more workers than each test actually needs.
"""

import multiprocessing
import os
from concurrent.futures.process import BrokenProcessPool

import pytest

from tests import _procpool_workers as workers
from ztf_viewer import procpool


@pytest.fixture(autouse=True)
def _small_pool(monkeypatch):
    procpool.shutdown_pool()
    monkeypatch.setattr(procpool, "PROCESS_POOL_SIZE", 2)
    yield
    procpool.shutdown_pool()


async def test_run_in_process_executes_in_a_different_process() -> None:
    pid = await procpool.run_in_process(workers.get_pid)
    assert pid != os.getpid()


async def test_exception_in_child_propagates_to_the_awaiter() -> None:
    with pytest.raises(ValueError, match="boom from child"):
        await procpool.run_in_process(workers.raise_value_error)


async def test_get_pool_returns_the_same_instance() -> None:
    assert procpool.get_pool() is procpool.get_pool()


async def test_crash_surfaces_as_broken_process_pool_and_the_pool_recovers() -> None:
    """A killed child must raise here rather than hang, and must not poison later calls."""
    with pytest.raises(BrokenProcessPool):
        await procpool.run_in_process(workers.die_hard)

    pid = await procpool.run_in_process(workers.get_pid)
    assert pid != os.getpid()


async def test_shutdown_is_idempotent_and_leaves_no_children() -> None:
    await procpool.run_in_process(workers.get_pid)  # forces a worker to actually spawn
    procpool.shutdown_pool()
    procpool.shutdown_pool()  # must not raise
    assert multiprocessing.active_children() == []

"""Tests for the process-wide CPU-bound offload pool.

`run_in_process`/`_pool` exercise the real, module-level singleton -- it is never shut down here,
since that would be irreversible for the rest of the session. The crash/shutdown tests build
their own throwaway `_ProcessPool` instances instead, both to keep spawn counts small and to
avoid touching shared state other tests rely on.

Because the real singleton's own workers stay alive for the session, `multiprocessing
.active_children()` is never asserted to be empty outright -- only that a test's own throwaway
pool added nothing that is still there once it is shut down.
"""

import multiprocessing
import os
from concurrent.futures.process import BrokenProcessPool

import pytest

from tests import _procpool_workers as workers
from ztf_viewer import procpool
from ztf_viewer.procpool import _ProcessPool


def _child_pids() -> set:
    return {p.pid for p in multiprocessing.active_children()}


async def test_run_in_process_executes_in_a_different_process() -> None:
    pid = await procpool.run_in_process(workers.get_pid)
    assert pid != os.getpid()


async def test_exception_in_child_propagates_to_the_awaiter() -> None:
    with pytest.raises(ValueError, match="boom from child"):
        await procpool.run_in_process(workers.raise_value_error)


def test_constructing_a_pool_builds_nothing() -> None:
    before = _child_pids()
    pool = _ProcessPool(max_workers=2)
    try:
        assert pool._executor is None
        assert _child_pids() == before
    finally:
        pool.shutdown()


async def test_a_child_importing_procpool_does_not_build_its_own_pool() -> None:
    """`_procpool_workers` imports this module, so every worker re-imports it under spawn."""
    assert await procpool.run_in_process(workers.procpool_executor_is_built) is False


async def test_crash_surfaces_as_broken_process_pool_and_the_pool_recovers() -> None:
    """A killed child must raise here rather than hang, and must not poison later calls."""
    before = _child_pids()
    pool = _ProcessPool(max_workers=2)
    try:
        with pytest.raises(BrokenProcessPool):
            await pool.run(workers.die_hard)

        pid = await pool.run(workers.get_pid)
        assert pid != os.getpid()
    finally:
        pool.shutdown()
        assert _child_pids() == before


async def test_shutdown_is_idempotent_and_leaves_no_children() -> None:
    before = _child_pids()
    pool = _ProcessPool(max_workers=2)
    await pool.run(workers.get_pid)  # forces a worker to actually spawn
    pool.shutdown()
    pool.shutdown()  # must not raise
    assert _child_pids() == before

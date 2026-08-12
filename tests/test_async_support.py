"""Async test support: that ``async def test_`` runs, and that #632's skip covers coroutines.

The hook tests run pytest inside pytest (``pytester``) against a copy of the real
``tests/conftest.py``, so they exercise the shipped hook rather than a restatement of it.
"""

import asyncio
import pathlib

import pytest

CONFTEST = (pathlib.Path(__file__).parent / "conftest.py").read_text(encoding="utf-8")

_OID = 633207400004730
_DR = "dr24"


# ---------------------------------------------------------------------------
# 1. asyncio_mode = "auto"
# ---------------------------------------------------------------------------


async def test_async_tests_are_collected_and_awaited():
    """No marker, no fixture, no event-loop boilerplate — the mode does it."""
    await asyncio.sleep(0)
    assert asyncio.get_running_loop() is not None


@pytest.mark.upstream
def test_ztf_dr_find_sync():
    """The sync half of the pair: a plain first-party upstream call."""
    from ztf_viewer.catalogs.ztf_dr import find_ztf_oid

    meta = find_ztf_oid.find(_OID, _DR)

    assert "lc" in meta
    assert "meta" in meta


@pytest.mark.upstream
async def test_ztf_dr_find_async_matches_sync():
    """`to_thread` is the shim the migration leans on (plan 001, F1a) — assert it agrees."""
    from ztf_viewer.catalogs.ztf_dr import find_ztf_oid

    from_sync = find_ztf_oid.find(_OID, _DR)
    from_async = await asyncio.to_thread(find_ztf_oid.find, _OID, _DR)

    assert from_async == from_sync


# ---------------------------------------------------------------------------
# 2. The upstream skip, for coroutines
# ---------------------------------------------------------------------------


@pytest.fixture
def upstream_pytester(pytester):
    """A pytest run configured like ours: our conftest, ``asyncio_mode=auto``."""
    pytester.makeconftest(CONFTEST)
    pytester.makeini("[pytest]\nasyncio_mode = auto\nasyncio_default_fixture_loop_scope = function\n")
    return pytester


def test_async_upstream_transport_error_becomes_a_skip(upstream_pytester):
    upstream_pytester.makepyfile("""
        import pytest

        @pytest.mark.upstream
        async def test_timeout():
            raise ConnectionError("upstream is down")
        """)
    result = upstream_pytester.runpytest()
    result.assert_outcomes(skipped=1)


def test_async_upstream_assertion_failure_still_fails(upstream_pytester):
    """Only transport failures become skips: if the upstream answered and we got the wrong
    result, that is our bug and the test must still fail."""
    upstream_pytester.makepyfile("""
        import pytest

        @pytest.mark.upstream
        async def test_wrong():
            assert 1 == 2
        """)
    result = upstream_pytester.runpytest()
    result.assert_outcomes(failed=1)


def test_async_transport_error_without_the_marker_still_fails(upstream_pytester):
    """The conversion is opt-in per marker; nothing here weakens unmarked tests."""
    upstream_pytester.makepyfile("""
        async def test_timeout():
            raise ConnectionError("upstream is down")
        """)
    result = upstream_pytester.runpytest()
    result.assert_outcomes(failed=1)


def test_httpx_transport_error_is_classified_as_upstream():
    """Skipped until httpx becomes a dependency; written ahead so no async test predates it."""
    httpx = pytest.importorskip("httpx")

    from tests.conftest import _is_upstream_error

    assert _is_upstream_error(httpx.ConnectTimeout("timed out"))
    assert _is_upstream_error(httpx.ConnectError("refused"))
    # Not an outage: a malformed URL is our bug.
    assert not _is_upstream_error(httpx.InvalidURL("nonsense"))

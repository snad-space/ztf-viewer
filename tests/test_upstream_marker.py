"""Coverage for the ``upstream`` marker implemented in ``tests/conftest.py`` (#632).

That hook rewrites a test's outcome — an ``upstream``-marked test that fails with a transport
error is reported as a skip instead of a failure — and an outcome is not observable from inside
the test it belongs to: by the time the hook runs, the test has stopped, and a skipped test
cannot assert that it was skipped. So the only way to check the rule is to run a second pytest
over a throwaway test file and inspect *its* results, which is what pytest's ``pytester``
fixture is for.

The nested run gets a copy of the real ``tests/conftest.py``, so these tests exercise the hook
we ship rather than a restatement of it.
"""

import pathlib

import pytest

CONFTEST = (pathlib.Path(__file__).parent / "conftest.py").read_text(encoding="utf-8")


@pytest.fixture
def upstream_pytester(pytester):
    """A pytest run configured like ours: our conftest, ``asyncio_mode=auto``."""
    pytester.makeconftest(CONFTEST)
    pytester.makeini("[pytest]\nasyncio_mode = auto\nasyncio_default_fixture_loop_scope = function\n")
    return pytester


def test_async_upstream_transport_error_becomes_a_skip(upstream_pytester):
    """The hook is transport-agnostic, but it had never run against a coroutine before."""
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

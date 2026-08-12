"""Shared test configuration.

The catalog tests query real services. That is deliberate — they exercise our
parsing against what the upstreams really return, which is the part worth
testing — but it means a test can fail for reasons that have nothing to do with
this repository: a read timeout, a dropped connection, an upstream 500, or a
service that is simply down.

Those failures are noise. They are not actionable, they land on whoever happens
to open the next pull request, and after a few of them people stop reading CI.
So a test marked ``upstream`` that fails with a transport-level error is turned
into a **skip with a warning** rather than a failure: the run stays green, and
the reason is printed in the summary (``-ra`` is on by default in addopts).

What is deliberately *not* converted:

* assertion failures — if the service answered and we parsed it wrong, that is
  our bug and it must fail;
* :class:`~ztf_viewer.exceptions.NotFound` — a real answer about the data;
* anything in a test not marked ``upstream``.

The marker is applied automatically to everything under ``tests/catalogs/``;
add it by hand elsewhere with ``@pytest.mark.upstream``.
"""

import http.client
import socket
import urllib.error
import warnings

import pytest

UPSTREAM_MARKER = "upstream"

#: Errors that mean "the service did not answer properly", never "our code is wrong".
#: ``OSError`` is the base of ``ConnectionError``, ``socket.timeout`` and
#: ``http.client.RemoteDisconnected``, so it covers the transport layer broadly — which is
#: safe here only because this conversion is opt-in per marker.
UPSTREAM_ERRORS: tuple[type[BaseException], ...] = (
    OSError,
    socket.timeout,
    urllib.error.URLError,
    http.client.HTTPException,
)


def _extra_upstream_errors() -> tuple[type[BaseException], ...]:
    """Third-party transport exceptions, imported lazily so conftest never hard-depends on them."""
    extra: list[type[BaseException]] = []
    try:
        from requests import RequestException

        extra.append(RequestException)
    except ImportError:
        pass
    try:
        from ztf_viewer.exceptions import CatalogUnavailable

        extra.append(CatalogUnavailable)
    except ImportError:
        pass
    return tuple(extra)


def _is_upstream_error(exc: BaseException) -> bool:
    if isinstance(exc, AssertionError):
        return False
    if isinstance(exc, UPSTREAM_ERRORS + _extra_upstream_errors()):
        return True
    # astroquery and friends wrap transport errors; walk the __cause__/__context__ chain.
    cause = exc.__cause__ or exc.__context__
    return cause is not None and _is_upstream_error(cause)


def setup_config(item):
    from ztf_viewer import config

    config.CACHE_TYPE = "memory"
    config.UNAVAILABLE_CATALOGS_CACHE_TYPE = "memory"


def setup_cache(item):
    from ztf_viewer import cache

    cache.cache = cache._get_cache()


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        f"{UPSTREAM_MARKER}: test queries a real upstream service; transport failures "
        "become skips instead of failures",
    )


def pytest_collection_modifyitems(items):
    """Mark every catalog test as ``upstream`` — they all talk to real services."""
    for item in items:
        if "tests/catalogs/" in item.nodeid or item.nodeid.startswith("catalogs/"):
            item.add_marker(UPSTREAM_MARKER)


def pytest_runtest_setup(item):
    setup_config(item)
    setup_cache(item)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    report = yield

    if report.outcome != "failed" or call.excinfo is None:
        return report
    if item.get_closest_marker(UPSTREAM_MARKER) is None:
        return report
    if not _is_upstream_error(call.excinfo.value):
        return report

    reason = f"upstream unavailable ({type(call.excinfo.value).__name__}: {call.excinfo.value})"
    warnings.warn(f"{item.nodeid}: {reason}", UpstreamUnavailableWarning, stacklevel=1)
    report.outcome = "skipped"
    report.longrepr = (item.location[0], item.location[1], reason)
    return report


class UpstreamUnavailableWarning(UserWarning):
    """An upstream service failed to answer, so a test was skipped instead of failed."""

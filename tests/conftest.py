"""Shared test configuration.

The catalog tests query real services. That is deliberate — they exercise our
parsing against what the services really return, which is the part worth
testing — but it means a test can fail for reasons that have nothing to do with
this repository: a read timeout, a dropped connection, a service 500, or a
service that is simply down.

Those failures are noise. They are not actionable, they land on whoever happens
to open the next pull request, and after a few of them people stop reading CI.
So a test marked ``network`` that fails with a transport-level error is turned
into a **skip with a warning** rather than a failure: the run stays green, and
the reason is printed in the summary (``-ra`` is on by default in addopts).

What is deliberately *not* converted:

* assertion failures — if the service answered and we parsed it wrong, that is
  our bug and it must fail;
* :class:`~ztf_viewer.exceptions.NotFound` — a real answer about the data;
* anything in a test not marked ``network``.

The marker is applied automatically to everything under ``tests/catalogs/``;
add it by hand elsewhere with ``@pytest.mark.network``.

Pass ``--no-net-skip`` to turn the conversion off and see the real errors.
"""

import http.client
import socket
import urllib.error
import warnings

import pytest

NETWORK_MARKER = "network"

#: Errors that mean "the service did not answer properly", never "our code is wrong".
#: ``OSError`` is the base of ``ConnectionError``, ``socket.timeout`` and
#: ``http.client.RemoteDisconnected``, so it covers the transport layer broadly — which is
#: safe here only because this conversion is opt-in per marker.
NETWORK_ERRORS: tuple[type[BaseException], ...] = (
    OSError,
    socket.timeout,
    urllib.error.URLError,
    http.client.HTTPException,
)


def _extra_network_errors() -> tuple[type[BaseException], ...]:
    """Third-party transport exceptions, imported lazily so conftest never hard-depends on them."""
    extra: list[type[BaseException]] = []
    try:
        from requests import RequestException

        extra.append(RequestException)
    except ImportError:
        pass
    try:
        # httpx inherits from neither OSError nor requests. Not InvalidURL/StreamError: our bugs.
        from httpx import HTTPError

        extra.append(HTTPError)
    except ImportError:
        pass
    try:
        from ztf_viewer.exceptions import CatalogUnavailable

        extra.append(CatalogUnavailable)
    except ImportError:
        pass
    return tuple(extra)


def _is_network_error(exc: BaseException) -> bool:
    if isinstance(exc, AssertionError):
        return False
    if isinstance(exc, NETWORK_ERRORS + _extra_network_errors()):
        return True
    # astroquery and friends wrap transport errors; walk the __cause__/__context__ chain.
    cause = exc.__cause__ or exc.__context__
    return cause is not None and _is_network_error(cause)


def setup_config(item):
    from ztf_viewer import config

    config.CACHE_TYPE = "memory"
    config.UNAVAILABLE_CATALOGS_CACHE_TYPE = "memory"


def setup_cache(item):
    from ztf_viewer import cache

    cache.cache = cache._get_cache()
    # Rebinding `cache.cache` only affects functions decorated *after* this point, and all 19
    # `@cache()` sites were decorated when their module was first imported.  Emptying the
    # backends is what actually gives a test an empty cache.
    cache.clear_memory_caches()


def reset_shared_thread_pool():
    """Give ``ztf_viewer.__main__``'s module-level thread pool a fresh executor.

    That pool is a single object shared by every event loop in the process — correct for
    production, where the entrypoint starts exactly one loop. This suite instead builds several
    independent ``TestClient``s, each driving its own ``asyncio.run`` lifespan, and
    ``asyncio.run``'s teardown shuts down whatever object was set as *that* loop's default
    executor — the object itself, not just that loop's use of it. Since every lifespan points at
    the same shared pool, the first one to finish would otherwise leave it dead for every
    ``TestClient`` built afterwards.

    Call this before constructing a ``TestClient`` around ``ztf_viewer.app.app`` (or anything that
    imports it), never from application code — the app itself only ever sees one startup.
    """
    import sys

    if "ztf_viewer.__main__" not in sys.modules:
        # Nothing registered `_size_thread_pools` as a startup handler yet, so there is nothing
        # to reset; importing `ztf_viewer.__main__` just to reset it would be its own bug source.
        return

    from concurrent.futures import ThreadPoolExecutor

    import ztf_viewer.__main__ as main_module

    main_module._thread_pool = ThreadPoolExecutor(
        max_workers=main_module.THREAD_POOL_SIZE, thread_name_prefix="ztf-viewer-test"
    )


def reset_shared_process_pool():
    """Give ``ztf_viewer.procpool``'s module-level process pool a fresh instance.

    Same reasoning as :func:`reset_shared_thread_pool`: the pool is a singleton built once for
    the life of the process, and this suite's several ``TestClient``s each drive their own
    lifespan, so the first one to shut down would otherwise leave it dead for every
    ``TestClient`` built afterwards.

    Call this before constructing a ``TestClient`` around ``ztf_viewer.app.app``, never from
    application code.
    """
    import sys

    if "ztf_viewer.procpool" not in sys.modules:
        return

    import ztf_viewer.procpool as procpool_module

    procpool_module._pool = procpool_module._ProcessPool(procpool_module.PROCESS_POOL_SIZE)


def pytest_addoption(parser):
    parser.addoption(
        "--no-net-skip",
        action="store_true",
        help="Let network-marked tests fail on transport errors instead of skipping them.",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        f"{NETWORK_MARKER}: test queries a real network service; transport failures "
        "become skips instead of failures",
    )


def pytest_collection_modifyitems(items):
    """Mark every catalog test as ``network`` — they all talk to real services."""
    for item in items:
        if "tests/catalogs/" in item.nodeid or item.nodeid.startswith("catalogs/"):
            item.add_marker(NETWORK_MARKER)


def pytest_runtest_setup(item):
    setup_config(item)
    setup_cache(item)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    report = yield

    if item.config.getoption("--no-net-skip"):
        return report
    if report.outcome != "failed" or call.excinfo is None:
        return report
    if item.get_closest_marker(NETWORK_MARKER) is None:
        return report
    if not _is_network_error(call.excinfo.value):
        return report

    reason = f"network unavailable ({type(call.excinfo.value).__name__}: {call.excinfo.value})"
    warnings.warn(f"{item.nodeid}: {reason}", NetworkUnavailableWarning, stacklevel=1)
    report.outcome = "skipped"
    report.longrepr = (item.location[0], item.location[1], reason)
    return report


class NetworkUnavailableWarning(UserWarning):
    """A network service failed to answer, so a test was skipped instead of failed."""

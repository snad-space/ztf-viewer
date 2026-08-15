"""A shared, per-loop ``httpx.AsyncClient`` for first-party outbound HTTP calls.

Built lazily through :class:`~ztf_viewer.loop_registry.LoopRegistry` rather than as a
module-level singleton: an ``httpx.AsyncClient`` opens its connection pool against whichever
event loop is running when it is first used, and reusing it from a different loop breaks. One
client per loop, sized from ``config.py``, sidesteps that.

Nothing in the app calls :func:`get_client` yet — this module only builds the client and wires
its shutdown, ready for callers to adopt incrementally.
"""

import asyncio

import httpx

from ztf_viewer import config
from ztf_viewer.loop_registry import LoopRegistry


def _build_client() -> httpx.AsyncClient:
    limits = httpx.Limits(
        max_connections=config.HTTP_MAX_CONNECTIONS,
        max_keepalive_connections=config.HTTP_MAX_KEEPALIVE_CONNECTIONS,
    )
    timeout = httpx.Timeout(config.HTTP_TIMEOUT_SECONDS)
    # `retries` only covers connection failures (DNS, refused/reset connections) before a
    # request reaches the server. It does not retry timeouts on an established connection, and
    # it never retries a request that got any response, including a 5xx one.
    transport = httpx.AsyncHTTPTransport(retries=config.HTTP_CONNECT_RETRIES)
    return httpx.AsyncClient(limits=limits, timeout=timeout, transport=transport)


_CLIENT_REGISTRY: LoopRegistry[httpx.AsyncClient] = LoopRegistry(_build_client)


def get_client() -> httpx.AsyncClient:
    """Return the ``httpx.AsyncClient`` for the running event loop, building it on first use."""
    return _CLIENT_REGISTRY.get()


async def aclose_client() -> None:
    """Close the running loop's client, if one was built, and drop its registry entry.

    Meant for a Starlette ``"shutdown"`` handler: a client can only be closed on the loop that
    owns it, so this must run before that loop stops, not after.
    """
    loop = asyncio.get_running_loop()
    client = get_client()
    await client.aclose()
    _CLIENT_REGISTRY.discard(loop)

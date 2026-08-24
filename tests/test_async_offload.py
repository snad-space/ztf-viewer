"""Guards that a callback converted to ``async def`` this cycle doesn't leave a blocking call
directly in its body.

Once a callback is a coroutine function, the registration shim (``ztf_viewer/callbacks.py``)
returns it unchanged rather than wrapping it in a thread offload — that's the whole point of the
shim, but it means anything still synchronous inside the body now runs inline on the event loop.
Every callback below still reaches a client that stayed synchronous on purpose (an unconverted
conesearch ``find``, an astroquery client, or a still-sync extinction lookup); this test pins
that each such call is routed through ``asyncio.to_thread`` rather than called bare.

A fully general static check (walk every ``async def`` in the app and flag any call that isn't
either awaited or wrapped) is impractical here — it would need to know which callables are safe
to call inline (pure computation) versus which are blocking I/O, and that distinction isn't
recoverable from the AST alone. So this only covers the specific call sites this change touches.
"""

import inspect

import pytest

from ztf_viewer import config

config.CACHE_TYPE = "memory"
config.UNAVAILABLE_CATALOGS_CACHE_TYPE = "memory"

from ztf_viewer.pages import viewer

# function (or unbound method) -> a substring of the sync call it must route through a thread
CALLBACKS_WITH_REMAINING_BLOCKING_CALLS = {
    viewer.fit_lc: "csfd.ebv",
    viewer.update_skybot_for_graph_clicked: "SKYBOT_QUERY.find",
    viewer.set_vizier_list: "find_vizier.find",
}


@pytest.mark.parametrize("func", list(CALLBACKS_WITH_REMAINING_BLOCKING_CALLS), ids=lambda f: f.__qualname__)
def test_async_callback_is_a_coroutine_function(func):
    assert inspect.iscoroutinefunction(inspect.unwrap(func))


@pytest.mark.parametrize(
    "func,blocking_call",
    CALLBACKS_WITH_REMAINING_BLOCKING_CALLS.items(),
    ids=[f.__qualname__ for f in CALLBACKS_WITH_REMAINING_BLOCKING_CALLS],
)
def test_remaining_blocking_call_goes_through_to_thread(func, blocking_call):
    source = inspect.getsource(inspect.unwrap(func))
    assert blocking_call in source, f"expected {func.__qualname__} to still call {blocking_call}"
    assert "asyncio.to_thread" in source, f"{func.__qualname__} calls {blocking_call} without asyncio.to_thread"

"""Mechanics tests for the natively-async pilot callbacks in ``ztf_viewer.pages.viewer``.

These callbacks are unchanged in behaviour from their shim-wrapped ``def`` form; the point of
these tests is proving the registration and dispatch mechanics work, not re-testing business
logic already covered elsewhere (or, for ``get_summary``, not covered at all yet).
"""

import functools
import inspect

import pytest
from dash.exceptions import PreventUpdate

from ztf_viewer.pages import viewer


def test_set_figure_link_partial_registrations_are_coroutines_in_callback_map():
    """19 `set_table` aside, this is the shape most registrations take: `partial` of a shared body."""
    png_entry = viewer.app.callback_map["figure-png-link.href"]
    pdf_entry = viewer.app.callback_map["figure-pdf-link.href"]
    assert inspect.iscoroutinefunction(png_entry["callback"])
    assert inspect.iscoroutinefunction(pdf_entry["callback"])


async def test_partial_of_set_figure_link_is_a_coroutine_the_shim_does_not_need_to_wrap():
    """`inspect.iscoroutinefunction` sees through `functools.partial` of an `async def`, so the
    shim's `_to_coroutine_function` passes it through untouched."""
    bound = functools.partial(viewer.set_figure_link, fmt="png")
    assert inspect.iscoroutinefunction(bound)

    href = await bound(
        cur_oid="123",
        dr="dr8",
        title="t",
        different_filter=None,
        different_field=None,
        min_mjd=None,
        max_mjd=None,
        lc_type="full",
        period=None,
        phase0=None,
    )

    assert href == "/dr8/figure/123?title=t&format=png"


def test_get_summary_is_registered_as_a_coroutine():
    entry = viewer.app.callback_map["summary.children"]
    assert inspect.iscoroutinefunction(entry["callback"])


async def test_get_summary_await_propagates_prevent_update_from_the_fan_out_callback():
    """A fan-out callback's early-exit `raise PreventUpdate` must still surface through `await`
    exactly as it did as a synchronous exception."""
    assert inspect.iscoroutinefunction(viewer.get_summary)

    with pytest.raises(PreventUpdate):
        await viewer.get_summary(
            oid="1",
            dr="dr8",
            different_filter=None,
            different_field=None,
            radius_ids=[{"index": "some_catalog"}],
            radius_values=[None],
        )

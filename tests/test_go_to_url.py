"""`go_to_url` -- the header's OID and coordinate/name boxes.

It drives `dcc.Location`, which is configured with `refresh=True`. In that mode the component
force-assigns every part of `window.location` that differs from its own props, in order, and the
last assignment wins. The light-curve page keeps the query string in step with its controls
through `history.replaceState`, which the component does not observe, so its `search` prop stays
at the value the page loaded with. Navigating by `pathname` therefore also re-applied that stale
`search`, sending the browser back to the current page with an empty query instead of to the
page asked for -- no search could be started from an object page whose URL had picked up a
`?min_mjd=`, `?lc=` or `?fits=`. Navigating by `href` moves the whole URL at once.
"""

import pytest
from dash.exceptions import PreventUpdate

from ztf_viewer import config

config.CACHE_TYPE = "memory"
config.UNAVAILABLE_CATALOGS_CACHE_TYPE = "memory"

import ztf_viewer.__main__ as main_module

_VIEW_PATH = "/dr24/view/680113300005170"


async def _go(**kwargs):
    """`go_to_url` as the header's callback calls it: every input at its layout default."""
    call = {
        "n_clicks_oid": 0,
        "n_submit_oid": 0,
        "n_clicks_search": 0,
        "n_submit_coord_or_name": 0,
        "n_submit_radius": 0,
        "oid": None,
        "coord_or_name": None,
        "radius_arcsec": 1,
        "current_pathname": _VIEW_PATH,
        "dr": "dr24",
    }
    return await main_module.go_to_url(**(call | kwargs))


async def test_the_search_button_navigates_to_the_search_page():
    assert await _go(n_clicks_search=1, coord_or_name="M31", radius_arcsec=10) == "/dr24/search/M31/10"


async def test_submitting_the_coordinate_box_navigates_to_the_search_page():
    assert await _go(n_submit_coord_or_name=1, coord_or_name="M31") == "/dr24/search/M31/1"


async def test_the_target_carries_no_query_string():
    """What is navigated to is the whole URL, so a query left over from the object page -- its
    MJD range, its external light curves -- must not be carried onto the page being opened."""
    target = await _go(n_clicks_search=1, coord_or_name="M31")
    assert "?" not in target


async def test_a_name_with_a_space_is_quoted():
    assert await _go(n_clicks_search=1, coord_or_name="NGC 7331") == "/dr24/search/NGC%207331/1"


async def test_nothing_submitted_does_not_navigate():
    """The initial call. Returning the current location would navigate to it stripped of its
    query string, throwing away the `?min_mjd=`/`?lc=`/`?fits=` an incoming link asked for."""
    with pytest.raises(PreventUpdate):
        await _go()


def test_the_callback_drives_the_whole_url():
    """`pathname` alone leaves `dcc.Location` free to re-apply its stale `search` afterwards."""
    outputs = [
        str(output)
        for key in main_module.app.callback_map
        for output in str(key).split("...")
        if output.startswith("url.")
    ]
    assert outputs == ["url.href"]

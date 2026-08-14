"""Regression test for the new-tag State inputs on the /tags page.

`new-tag-priority-input`, `new-tag-name-input` and `new-tag-description-input`
are only rendered when logged in, so their States use ALL-wildcard pattern
matching ids: Dash returns an empty list rather than erroring when the
matching component is absent from the current layout. `set_save_status` must
unpack those single-element (or empty) lists back into scalars.
"""

import inspect
import types
from unittest.mock import patch

from dash._callback_context import context_value

from ztf_viewer.pages import tags

# Callback registration may wrap the function; the body under test is the innermost one.
set_save_status = inspect.unwrap(tags.set_save_status)


def test_set_save_status_unpacks_pattern_matched_new_tag_state():
    with patch("ztf_viewer.pages.tags.akb") as mock_akb:
        mock_akb.is_token_valid.return_value = True
        set_save_status(
            n_clicks=1,
            tags=[],
            priorities=[],
            new_priority=[5],
            new_name=["foo"],
            new_description=["bar"],
        )
    mock_akb.post_tags.assert_called_once_with([dict(name="foo", priority=5, description="bar")])


def test_set_save_status_tolerates_empty_new_tag_state():
    with patch("ztf_viewer.pages.tags.akb") as mock_akb:
        mock_akb.is_token_valid.return_value = True
        set_save_status(
            n_clicks=1,
            tags=[],
            priorities=[],
            new_priority=[],
            new_name=[],
            new_description=[],
        )
    mock_akb.post_tags.assert_called_once_with([])


async def test_show_tags_is_a_native_coroutine_that_reads_ctx_cookies():
    """``show_tags`` is ``async def`` directly, not shim-wrapped; ``dash.ctx.cookies`` must
    still resolve to the token from the current callback context."""
    assert inspect.iscoroutinefunction(tags.show_tags)

    token = context_value.set(types.SimpleNamespace(cookies={"akb_token": "abc123"}))
    try:
        with (
            patch.object(tags.akb, "_is_token_valid") as mock_is_token_valid,
            patch.object(tags.akb, "get_tags", return_value=[]),
        ):
            mock_is_token_valid.return_value = True
            result = await tags.show_tags(None, None, None)
    finally:
        context_value.reset(token)

    # The mock is only reachable through `is_token_valid` -> `_token_from_cookies`, so this
    # also proves the cookie set above is the value that made it through.
    mock_is_token_valid.assert_called_once_with(token="abc123")
    assert isinstance(result, list)

"""Tests for `ztf_viewer.pages.search.get_layout`.

`get_layout` reaches exactly one upstream, `find_ztf_circle.find`, so both of its branches are
reachable with a stub and no network.
"""

from unittest.mock import patch

from astropy.coordinates import SkyCoord

from ztf_viewer import config

# See the note in `tests/pages/test_viewer.py`: `ztf_viewer.catalogs` connects to Redis at import
# time when configured for it, which is before `tests/conftest.py` gets a chance to intervene.
config.CACHE_TYPE = "memory"
config.UNAVAILABLE_CATALOGS_CACHE_TYPE = "memory"

from ztf_viewer.exceptions import NotFound
from ztf_viewer.pages import search

COORD = SkyCoord(10.0, 20.0, unit="deg", frame="icrs")

_STUB_CIRCLE = {
    "700207400012345": {
        "separation": 0.12,
        "meta": {"filter": "zr", "ngoodobs": 300, "duration": 1500.0},
    },
    "700207300054321": {
        "separation": 0.31,
        "meta": {"filter": "zg", "ngoodobs": 250, "duration": 1450.0},
    },
}


def _leaves(component):
    """The component tree flattened to its leaf children, in render order."""
    children = getattr(component, "children", component)
    if not isinstance(children, list):
        return [children]
    return [leaf for child in children for leaf in _leaves(child)]


async def test_get_layout_explains_multiple_oids_above_the_table():
    async def fake_find(ra, dec, radius_arcsec, dr):
        return dict(_STUB_CIRCLE)

    with patch.object(search.find_ztf_circle, "find", fake_find):
        layout = await search.get_layout(COORD, 1.0, "dr24")

    _heading, note, table = _leaves(layout)
    assert note == search.MULTIPLE_OIDS_NOTE
    # The note is only useful next to the rows it explains, and only if it precedes them.
    assert "700207400012345" in table


async def test_get_layout_single_result_has_no_note():
    async def fake_find(ra, dec, radius_arcsec, dr):
        return {"700207400012345": dict(_STUB_CIRCLE["700207400012345"])}

    with patch.object(search.find_ztf_circle, "find", fake_find):
        layout = await search.get_layout(COORD, 1.0, "dr24")

    heading, table = _leaves(layout)
    assert heading.startswith("Objects inside cone")
    assert "700207400012345" in table


async def test_get_layout_404_has_no_note():
    async def fake_find(ra, dec, radius_arcsec, dr):
        raise NotFound

    with patch.object(search.find_ztf_circle, "find", fake_find):
        layout = await search.get_layout(COORD, 1.0, "dr24")

    assert search.MULTIPLE_OIDS_NOTE not in _leaves(layout)

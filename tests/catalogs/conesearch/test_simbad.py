"""Live Simbad cone search — an astroquery/pyvo TAP path, not a plain requests call.

Kept mainly so ``--record-http`` captures the TAP exchange that the offline suite
replays (``tests/test_replayed_catalogs.py::test_simbad_cone_search``).
"""

import pytest
from astropy.coordinates import SkyCoord


@pytest.mark.live
def test_cone_search():
    from ztf_viewer.catalogs.conesearch.simbad import SimbadQuery

    query = SimbadQuery("Test Simbad")
    # M31 core: dense enough that the mesdistance/otypes joins still return rows
    coord = SkyCoord(ra=10.6847, dec=41.2687, unit="deg")
    table = query._query_region(coord, "10s")
    assert table is not None
    assert len(table) > 0

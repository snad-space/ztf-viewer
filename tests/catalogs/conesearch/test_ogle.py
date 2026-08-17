from xml.etree import ElementTree as ET

from numpy.testing import assert_allclose


async def test_cone_search():
    """Regression test against the real OGLE-III mirror server.

    OGLE-BLG-RRLYR-04010 is a known RR Lyrae star (coordinates from the OGLE-III
    catalog, https://ogle3.snad.space), also present in ZTF DR as oid 281213300185594
    at essentially the same position, which is how this coincidence was found.
    """
    from ztf_viewer.catalogs.conesearch.ogle import OgleQuery

    ogle_query = OgleQuery("Test OGLE")
    # 17:50:17.82 -22:12:52.2, converted to decimal degrees
    ra, dec = 267.574250, -22.214500
    table = await ogle_query._api_query_region(ra, dec, radius_arcsec=5.0)

    assert table is not None
    assert len(table) > 0

    for col in ("ID", "RA", "Decl", "Type", "Subtype", "P_1", "light_curve"):
        assert col in table.colnames, f"Missing column: {col}"

    ids = list(table["ID"])
    assert "OGLE-BLG-RRLYR-04010" in ids, f"Expected object not found; got: {ids}"

    idx = ids.index("OGLE-BLG-RRLYR-04010")
    assert table["Type"][idx] == "RRLyr"
    assert table["Subtype"][idx] == "RRab"
    assert_allclose(table["P_1"][idx], 0.4774, atol=1e-3)

    # The light curve image should have downloaded successfully: an <a><img> tag with an
    # embedded base64 PNG, not the "" fallback used when the image isn't found.
    light_curve_html = table["light_curve"][idx]
    assert light_curve_html.startswith('<a href="'), f"Light curve image missing: {light_curve_html!r}"
    assert "data:image/png;base64," in light_curve_html


async def test_rendered_html_is_well_formed():
    """Regression test for two real bugs found in this exact rendering path.

    OGLE's table cells are the only ones in the app built from a <form>+<input> (the
    "Designation" cell, via anchor_form) and an <img> with an unquoted attribute (the
    "Light curve" cell, before this test existed). The catalog table HTML is rendered client
    side via dcc.Markdown(dangerously_allow_html=True), which - unlike a plain browser HTML5
    parser - parses raw HTML as JSX: an unclosed void element (e.g. `<input ...>` without
    `/>`) or an unquoted attribute value (e.g. `width=200px` instead of `width="200px"`)
    silently breaks rendering of the *entire* surrounding table, not just that cell. XML
    well-formedness (balanced/self-closed tags, quoted attributes) is essentially the same
    requirement JSX imposes, so parsing the rendered HTML as XML is a direct proxy for "will
    this actually render in the browser."
    """
    from ztf_viewer.catalogs.conesearch.ogle import OgleQuery
    from ztf_viewer.util import html_from_astropy_table

    ogle_query = OgleQuery("Test OGLE 3")
    ra, dec = 267.574250, -22.214500
    table = await ogle_query.find(ra, dec, radius_arcsec=5.0)

    html = html_from_astropy_table(table, ogle_query.columns, html_columns=ogle_query.html_columns)
    try:
        ET.fromstring(f"<root>{html}</root>")
    except ET.ParseError as e:
        raise AssertionError(f"Rendered OGLE table is not well-formed HTML/JSX: {e}\n{html}") from e


async def test_cone_search_not_found():
    """Non-detection: a tiny radius far from any known OGLE-III field returns nothing."""
    import pytest
    from ztf_viewer.catalogs.conesearch.ogle import OgleQuery
    from ztf_viewer.exceptions import NotFound

    ogle_query = OgleQuery("Test OGLE 2")
    with pytest.raises(NotFound):
        await ogle_query.find(ra=0.0, dec=60.0, radius_arcsec=1.0)

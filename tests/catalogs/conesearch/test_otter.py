from numpy.testing import assert_allclose


def test_cone_search():
    """Regression test against the real Otter server.

    Coordinates taken from the example in
    https://github.com/astro-otter/otter/issues/45#issuecomment-4092184705
    (ra=185.0, dec=12.0, sep=1.0 deg → radius_arcsec=3600).
    """
    from ztf_viewer.catalogs.conesearch.otter import OtterQuery

    otter_query = OtterQuery("Test Otter")
    # 1-degree cone around the example coordinates
    table = otter_query._api_query_region(ra=185.0, dec=12.0, radius_arcsec=3600.0)

    assert table is not None
    assert len(table) > 0

    # Expected columns
    for col in ("default_name", "ra", "dec", "object_class", "redshift", "discovery_date"):
        assert col in table.colnames, f"Missing column: {col}"

    # One known object in this field
    names = list(table["default_name"])
    assert "CSS071216:122109+125434" in names, f"Expected object not found; got: {names}"

    idx = names.index("CSS071216:122109+125434")
    assert_allclose(table["ra"][idx], 185.2865, atol=0.01)
    assert_allclose(table["dec"][idx], 12.9095, atol=0.01)


def test_get_url():
    from ztf_viewer.catalogs.conesearch.otter import OtterQuery

    otter_query = OtterQuery("Test Otter 2")
    url = otter_query.get_url("CSS071216:122109+125434")
    assert url == "https://otter.idies.jhu.edu/transient/CSS071216:122109+125434"

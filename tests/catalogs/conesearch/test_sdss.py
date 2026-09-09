import pickle

import pytest

from ztf_viewer.catalogs.conesearch.sdss import SdssQuasarsQuery

# A patch of the SDSS Stripe 82 / COSMOS area densely covered by DR16Q spectroscopy, so a
# 600 arcsec cone returns quasars with several different `r_z` (SOURCE_Z) codes.
_RA = 150.0
_DEC = 2.0
_RADIUS_ARCSEC = 600.0


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("PIPE", "SDSS pipeline redshift of this catalog"),
        ("VI", "visual inspection of this catalog"),
    ],
)
def test_redshift_source_plain_codes(code, expected):
    assert SdssQuasarsQuery._redshift_source(code) == expected


@pytest.mark.parametrize(
    ("code", "vizier_source"),
    [
        ("DR6Q_HW", "J/MNRAS/405/2302"),
        ("DR7QV_SCH", "VII/260"),
        ("DR12QV", "VII/279"),
    ],
)
def test_redshift_source_links_to_the_original_catalog(code, vizier_source):
    html = SdssQuasarsQuery._redshift_source(code)
    assert f"-source={vizier_source}" in html


def test_redshift_source_unknown_code_is_escaped():
    """A future catalog release may add a code; it should still render, and safely.

    The column is rendered unescaped (see `_declared_html_columns`), so anything passed
    through untranslated has to be escaped here.
    """
    assert SdssQuasarsQuery._redshift_source("<b>NEW</b>") == "&lt;b&gt;NEW&lt;/b&gt;"


async def test_find_translates_redshift_source():
    """Regression test for https://github.com/snad-space/ztf-viewer/issues/375

    The raw catalog gives `r_z` as a short code like "DR6Q_HW", which means nothing to a user.
    """
    table = await SdssQuasarsQuery("Test SDSS DR16 Quasars").find(_RA, _DEC, _RADIUS_ARCSEC)

    assert len(table) > 0
    codes = set(SdssQuasarsQuery._redshift_source_map)
    values = {str(value) for value in table["r_z"]}
    assert values, "no redshift source values returned"
    assert not (values & codes), f"untranslated r_z codes left in the table: {values & codes}"

    # `find` is `@cache()`-decorated, and the Redis backend pickles what it stores
    assert pickle.loads(pickle.dumps(table)) is not None

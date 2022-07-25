from functools import partial

from ztf_viewer.catalogs.conesearch import ANTARES_QUERY, GAIA_DR3, PANSTARRS_DR2_QUERY

EXTERNAL_LC_DATA = {
    'antares': partial(ANTARES_QUERY.closest_light_curve_by_oid, fail_on_empty=False, fail_on_unavailable=False),
    'gaia': partial(GAIA_DR3.closest_light_curve_by_oid, fail_on_empty=False, fail_on_unavailable=False),
    'panstarrs': partial(PANSTARRS_DR2_QUERY.closest_light_curve_by_oid, fail_on_empty=False,
                         fail_on_unavailable=False),
}

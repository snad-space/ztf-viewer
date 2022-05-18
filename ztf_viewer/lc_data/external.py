from ztf_viewer.catalogs.conesearch import ANTARES_QUERY, PANSTARRS_DR2_QUERY

EXTERNAL_LC_DATA = {
    'antares': ANTARES_QUERY.closest_light_curve_by_oid,
    'panstarrs': PANSTARRS_DR2_QUERY.closest_light_curve_by_oid
}

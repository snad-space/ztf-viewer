from functools import partial

from immutabledict import immutabledict

from ztf_viewer.catalogs.conesearch import ANTARES_QUERY, GAIA_DR3, PANSTARRS_DR2_QUERY

EXTERNAL_LC_DATA = {
    "antares": partial(ANTARES_QUERY.closest_light_curve_by_oid, fail_on_empty=False, fail_on_unavailable=False),
    "gaia": partial(GAIA_DR3.closest_light_curve_by_oid, fail_on_empty=False, fail_on_unavailable=False),
    "panstarrs": partial(
        PANSTARRS_DR2_QUERY.closest_light_curve_by_oid, fail_on_empty=False, fail_on_unavailable=False
    ),
}

ADDITIONAL_LC_SEARCH_RADIUS_ARCSEC = 5.0


def parse_external_lc_names(values: list[str]) -> list[str]:
    """External light-curve names asked for by a repeated `lc=` query parameter.

    Both `lc=antares&lc=gaia` and `lc=antares,gaia` are accepted, and unknown names are dropped
    rather than raising, exactly as the page's own `?lc=` parameter does.
    """
    requested = {name.strip().lower() for value in values for name in value.split(",")}
    return [name for name in EXTERNAL_LC_DATA if name in requested]


def external_lc_data(names) -> immutabledict:
    """The `external_data` mapping `get_plot_data` takes for the named light curves."""
    return immutabledict({name: immutabledict({"radius_arcsec": ADDITIONAL_LC_SEARCH_RADIUS_ARCSEC}) for name in names})

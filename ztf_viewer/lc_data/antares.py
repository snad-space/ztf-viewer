import numpy as np

from ztf_viewer.catalogs import find_ztf_oid
from ztf_viewer.catalogs.conesearch.antares import AntaresQuery


def get_antares_lc(oid, dr, radius):
    coord = find_ztf_oid.get_sky_coord(oid, dr)
    _, locus = AntaresQuery.query_region_closest_locus(coord, radius)
    lc = locus.lightcurve[~np.isnan(locus.lightcurve['ant_mag'])]
    return [
        {
            'oid': locus.locus_id,
            'mjd': obs.ant_mjd,
            'mag': obs.ant_mag,
            'magerr': obs.ant_magerr,
            'filter': f"ant_{obs.ant_passband}",
        }
        for obs in lc.itertuples()
    ]

import math as m

import numpy as np
from astropy.time import Time
from immutabledict import immutabledict

from ztf_viewer.cache import cache
from ztf_viewer.catalogs import find_ztf_oid
from ztf_viewer.util import immutabledefaultdict

MJD_OFFSET = 58000


LN10_04 = 0.4 * np.log(10.0)
ABZPMAG_JY = 8.9


@cache()
def get_plot_data(cur_oid, dr, other_oids=frozenset(), min_mjd=None, max_mjd=None, additional_data=immutabledict(),
                  ref_mag=immutabledefaultdict(lambda: np.inf), ref_magerr=immutabledefaultdict(float)):
    """Get plot data

    additional_data format is:
    {
        'id1': [
            {
                'mjd': 58800.3,
                'mag': 18.1,
                'magerr': 0.34,
                'filter': 'r',
            },
            ...
        ],
        ...
    }
    """
    oids = [cur_oid]
    oids.extend(sorted(other_oids, key=int))
    lcs = {}
    for oid in oids:
        if oid == cur_oid:
            size = 3
        else:
            size = 1
        lc = find_ztf_oid.get_lc(oid, dr, min_mjd=min_mjd, max_mjd=max_mjd)
        meta = find_ztf_oid.get_meta(oid, dr)
        ref_flux = 10 ** (-0.4 * (ref_mag[meta['filter']] - ABZPMAG_JY))
        ref_fluxerr = LN10_04 * ref_flux * ref_magerr[meta['filter']]
        for obs in lc:
            obs['oid'] = oid
            obs['fieldid'] = meta['fieldid']
            obs['rcid'] = meta['rcid']
            obs['filter'] = meta['filter']
            obs['mark_size'] = size

            obs['flux_Jy'] = 10 ** (-0.4 * (obs['mag'] - ABZPMAG_JY))
            obs['fluxerr_Jy'] = LN10_04 * obs['flux_Jy'] * obs['magerr']

            obs['diffflux_Jy'] = obs['flux_Jy'] - ref_flux
            obs['difffluxerr_Jy'] = np.hypot(obs['fluxerr_Jy'], ref_fluxerr)

            if obs['diffflux_Jy'] <= 0:
                obs['diffmag'] = np.inf
                obs['diffmagerr'] = np.inf
            else:
                obs['diffmag'] = ABZPMAG_JY - 2.5 * m.log10(obs['diffflux_Jy'])
                obs['diffmagerr'] = 1.0 / LN10_04 * obs['difffluxerr_Jy'] / obs['diffflux_Jy']
        lcs[oid] = lc
    for identifier, lc in additional_data.items():
        list_lc = []
        for obs in lc:
            obs = dict(obs)
            obs['oid'] = identifier
            obs['mark_size'] = 3
            list_lc.append(obs)
        lcs[identifier] = list_lc
    for oid, lc in lcs.items():
        mjd = np.array([obs['mjd'] for obs in lc])
        time = Time(mjd, format='mjd')
        for t, obs in zip(time, lc):
            obs[f'mjd_{MJD_OFFSET}'] = obs['mjd'] - MJD_OFFSET
            obs['date'] = t.strftime('%Y-%m-%d')
            obs['cur_oid'] = cur_oid
    return lcs


@cache()
def get_folded_plot_data(cur_oid, dr, period, offset=None, other_oids=frozenset(), min_mjd=None, max_mjd=None,
                         additional_data=immutabledict(), ref_mag=immutabledefaultdict(lambda: np.inf),
                         ref_magerr=immutabledefaultdict(float)):
    if offset is None:
        offset = MJD_OFFSET
    lcs = get_plot_data(cur_oid, dr, other_oids=other_oids, min_mjd=min_mjd, max_mjd=max_mjd,
                        additional_data=additional_data, ref_mag=ref_mag, ref_magerr=ref_magerr)
    for lc in lcs.values():
        for obs in lc:
            obs['folded_time'] = (obs['mjd'] - offset) % period
            obs['phase'] = obs['folded_time'] / period
    return lcs

import math as m

import numpy as np
from astropy.time import Time
from immutabledict import immutabledict

from ztf_viewer.cache import cache
from ztf_viewer.lc_data.arbitrary import add_id_to_obs
from ztf_viewer.lc_data.ztf_dr import ztf_dr_lc
from ztf_viewer.util import immutabledefaultdict

MJD_OFFSET = 58000


LN10_04 = 0.4 * np.log(10.0)
ABZPMAG_JY = 8.9


def plot_data(lc, mark_size=1, min_mjd=None, max_mjd=None, ref_mag=immutabledefaultdict(lambda: np.inf),
              ref_magerr=immutabledefaultdict(float)):
    """Add photometry and time properties to observations, it mutates input"""
    if min_mjd is None:
        min_mjd = -np.inf
    if max_mjd is None:
        max_mjd = np.inf

    data = []
    for obs in lc:
        if not min_mjd <= obs['mjd'] <= max_mjd:
            continue

        obs['mark_size'] = mark_size

        ref_flux = 10 ** (-0.4 * (ref_mag[obs['filter']] - ABZPMAG_JY))
        ref_fluxerr = LN10_04 * ref_flux * ref_magerr[obs['filter']]

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

        obs[f'mjd_{MJD_OFFSET}'] = obs['mjd'] - MJD_OFFSET
        time = Time(obs['mjd'], format='mjd')
        obs['date'] = time.strftime('%Y-%m-%d')

        data.append(obs)

    return data


def folded_plot_data(plot_data, period, offset=None):
    """Adds 'folded_time' and 'phase' to observations, it mutates input"""
    if offset is None:
        offset = MJD_OFFSET
    for obs in plot_data:
        obs['folded_time'] = (obs['mjd'] - offset) % period
        obs['phase'] = obs['folded_time'] / period
    return plot_data


@cache()
def get_plot_data(cur_oid, dr, other_oids=frozenset(), min_mjd=None, max_mjd=None, additional_data=immutabledict(),
                  ref_mag=immutabledefaultdict(lambda: np.inf), ref_magerr=immutabledefaultdict(float)):
    lcs = {
        cur_oid: plot_data(ztf_dr_lc(cur_oid, dr), mark_size=3, min_mjd=min_mjd, max_mjd=max_mjd, ref_mag=ref_mag,
                           ref_magerr=ref_magerr,),
    } | {
        oid: plot_data(ztf_dr_lc(oid, dr), mark_size=1, min_mjd=min_mjd, max_mjd=max_mjd, ref_mag=ref_mag,
                       ref_magerr=ref_magerr)
        for oid in sorted(other_oids, key=int)
    } | {
        id: plot_data(lc, mark_size=3, min_mjd=min_mjd, max_mjd=max_mjd, ref_mag=ref_mag, ref_magerr=ref_magerr)
        for id, lc in add_id_to_obs(additional_data).items()
    }
    return lcs


@cache()
def get_folded_plot_data(cur_oid, dr, period, offset=None, other_oids=frozenset(), min_mjd=None, max_mjd=None,
                         additional_data=immutabledict(), ref_mag=immutabledefaultdict(lambda: np.inf),
                         ref_magerr=immutabledefaultdict(float)):
    lcs = get_plot_data(cur_oid=cur_oid, dr=dr, other_oids=other_oids, min_mjd=min_mjd, max_mjd=max_mjd,
                        additional_data=additional_data, ref_mag=ref_mag, ref_magerr=ref_magerr)
    lcs = {oid: folded_plot_data(lc, period=period, offset=offset) for oid, lc in lcs.items()}
    return lcs

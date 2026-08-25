import asyncio

import numpy as np
from astropy.time import Time
from immutabledict import immutabledict

from ztf_viewer.cache import cache
from ztf_viewer.lc_data import EXTERNAL_LC_DATA
from ztf_viewer.lc_data.arbitrary import add_id_to_obs
from ztf_viewer.lc_data.ztf_dr import ztf_dr_lc
from ztf_viewer.util import ABZPMAG_JY, FILTERS_ORDER, LN10_04, immutabledefaultdict

MJD_OFFSET = 58000

_DEFAULT_REF_MAG = immutabledefaultdict(lambda: np.inf)
_DEFAULT_REF_MAGERR = immutabledefaultdict(float)
_EMPTY_IMMUTABLEDICT: immutabledict = immutabledict()


def plot_data(
    lc,
    mark_size=1,
    min_mjd=None,
    max_mjd=None,
    ref_mag=_DEFAULT_REF_MAG,
    ref_magerr=_DEFAULT_REF_MAGERR,
):
    """Add photometry and time properties to observations, it mutates input"""
    if min_mjd is None:
        min_mjd = -np.inf
    if max_mjd is None:
        max_mjd = np.inf
    if not lc:
        return []

    mjd_all = np.array([obs["mjd"] for obs in lc])
    idx = np.nonzero((mjd_all >= min_mjd) & (mjd_all <= max_mjd))[0]
    if idx.size == 0:
        return []
    data = [lc[i] for i in idx]
    mjd = mjd_all[idx]
    mag = np.array([obs["mag"] for obs in data])
    magerr = np.array([obs["magerr"] for obs in data])
    # Normally we have a single oid for the light curve, but it could not
    # be a case, see get_antares_lc for an example
    ref_mag_arr = np.array([ref_mag[obs["oid"]] for obs in data])
    ref_magerr_arr = np.array([ref_magerr[obs["oid"]] for obs in data])

    ref_flux = 10 ** (-0.4 * (ref_mag_arr - ABZPMAG_JY))
    ref_fluxerr = LN10_04 * ref_flux * ref_magerr_arr
    flux_Jy = 10 ** (-0.4 * (mag - ABZPMAG_JY))
    fluxerr_Jy = LN10_04 * flux_Jy * magerr
    diffflux_Jy = flux_Jy - ref_flux
    difffluxerr_Jy = np.hypot(fluxerr_Jy, ref_fluxerr)

    # we do both for a weird case of negative error
    bad = (diffflux_Jy <= 0) | (diffflux_Jy < difffluxerr_Jy)
    with np.errstate(divide="ignore", invalid="ignore"):
        diffmag = np.where(bad, np.inf, ABZPMAG_JY - 2.5 * np.log10(diffflux_Jy))
        # for smaller flux
        diffmagerr_plus = np.where(bad, np.inf, -2.5 * np.log10(1 - difffluxerr_Jy / diffflux_Jy))
        # positive and for larger flux
        diffmagerr_minus = np.where(bad, np.inf, 2.5 * np.log10(1 + difffluxerr_Jy / diffflux_Jy))

    mjd_offset = mjd - MJD_OFFSET
    dates = Time(mjd, format="mjd").strftime("%Y-%m-%d")

    for i, obs in enumerate(data):
        obs["mark_size"] = mark_size
        obs["flux_Jy"] = float(flux_Jy[i])
        obs["fluxerr_Jy"] = float(fluxerr_Jy[i])
        obs["diffflux_Jy"] = float(diffflux_Jy[i])
        obs["difffluxerr_Jy"] = float(difffluxerr_Jy[i])
        obs["ref_flux"] = float(ref_flux[i])
        obs["diffmag"] = float(diffmag[i])
        obs["diffmagerr_plus"] = float(diffmagerr_plus[i])
        obs["diffmagerr_minus"] = float(diffmagerr_minus[i])
        obs[f"mjd_{MJD_OFFSET}"] = float(mjd_offset[i])
        obs["date"] = str(dates[i])

    data.sort(key=lambda obs: (FILTERS_ORDER[obs["filter"]], obs["mjd"]))

    return data


def folded_plot_data(plot_data, period, offset=None):
    """Adds 'folded_time' and 'phase' to observations, it mutates input"""
    if offset is None:
        offset = MJD_OFFSET
    for obs in plot_data:
        obs["folded_time"] = (obs["mjd"] - offset) % period
        obs["phase"] = obs["folded_time"] / period
    return plot_data


@cache()
async def get_plot_data(
    cur_oid,
    dr,
    other_oids=frozenset(),
    min_mjd=None,
    max_mjd=None,
    external_data=_EMPTY_IMMUTABLEDICT,
    additional_data=_EMPTY_IMMUTABLEDICT,
    ref_mag=_DEFAULT_REF_MAG,
    ref_magerr=_DEFAULT_REF_MAGERR,
):
    """Get plot data

    external_data format:
    {
        'antares': {<kwargs for get_antares_lc(oid, dr, **kwargs)>},
        ...
    }

    additional_data format:
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
    other_oids_sorted = sorted(other_oids, key=int)
    external_items = list(external_data.items())

    async def _ztf_lc(oid, mark_size):
        return plot_data(
            await ztf_dr_lc(oid, dr),
            mark_size=mark_size,
            min_mjd=min_mjd,
            max_mjd=max_mjd,
            ref_mag=ref_mag,
            ref_magerr=ref_magerr,
        )

    async def _external_lc(source, kwargs):
        return plot_data(
            await EXTERNAL_LC_DATA[source](cur_oid, dr, **kwargs),
            mark_size=1,
            min_mjd=min_mjd,
            max_mjd=max_mjd,
            ref_mag=ref_mag,
            ref_magerr=ref_magerr,
        )

    cur_lc, *rest = await asyncio.gather(
        _ztf_lc(cur_oid, mark_size=3),
        *(_ztf_lc(oid, mark_size=1) for oid in other_oids_sorted),
        *(_external_lc(source, kwargs) for source, kwargs in external_items),
    )
    other_lcs = rest[: len(other_oids_sorted)]
    external_lcs = rest[len(other_oids_sorted) :]

    lcs = {cur_oid: cur_lc}
    lcs.update(zip(other_oids_sorted, other_lcs))
    for id, lc in add_id_to_obs(additional_data).items():
        lcs[id] = plot_data(lc, mark_size=3, min_mjd=min_mjd, max_mjd=max_mjd, ref_mag=ref_mag, ref_magerr=ref_magerr)
    lcs.update((source, lc) for (source, _), lc in zip(external_items, external_lcs))
    return lcs


@cache()
async def get_folded_plot_data(
    cur_oid,
    dr,
    period,
    offset=None,
    other_oids=frozenset(),
    min_mjd=None,
    max_mjd=None,
    external_data=_EMPTY_IMMUTABLEDICT,
    additional_data=_EMPTY_IMMUTABLEDICT,
    ref_mag=_DEFAULT_REF_MAG,
    ref_magerr=_DEFAULT_REF_MAGERR,
):
    lcs = await get_plot_data(
        cur_oid=cur_oid,
        dr=dr,
        other_oids=other_oids,
        min_mjd=min_mjd,
        max_mjd=max_mjd,
        external_data=external_data,
        additional_data=additional_data,
        ref_mag=ref_mag,
        ref_magerr=ref_magerr,
    )
    lcs = {oid: folded_plot_data(lc, period=period, offset=offset) for oid, lc in lcs.items()}
    return lcs

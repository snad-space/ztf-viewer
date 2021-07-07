from datetime import datetime
from io import BytesIO, StringIO

import matplotlib
import matplotlib.backends.backend_pgf
import matplotlib.figure
import numpy as np
import pandas as pd
from flask import Response, request, send_file
from immutabledict import immutabledict
from matplotlib.ticker import AutoMinorLocator

from ztf_viewer.app import app
from ztf_viewer.cache import cache
from ztf_viewer.catalogs import find_ztf_oid
from ztf_viewer.exceptions import NotFound
from ztf_viewer.util import mjd_to_datetime, FILTER_COLORS, FILTERS_ORDER, parse_json_to_immutable, ZTF_FILTERS, flip

MJD_OFFSET = 58000


@cache()
def get_plot_data(cur_oid, dr, other_oids=frozenset(), min_mjd=None, max_mjd=None, additional_data=immutabledict()):
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
        for obs in lc:
            obs['oid'] = oid
            obs['fieldid'] = meta['fieldid']
            obs['rcid'] = meta['rcid']
            obs['filter'] = meta['filter']
            obs['mark_size'] = size
        lcs[oid] = lc
    for identifier, lc in additional_data.items():
        list_lc = []
        for obs in lc:
            obs = dict(obs)
            obs['oid'] = identifier
            obs['mark_size'] = 3
            list_lc.append(obs)
        lcs[identifier] = list_lc
    for lc in lcs.values():
        for obs in lc:
            obs[f'mjd_{MJD_OFFSET}'] = obs['mjd'] - MJD_OFFSET
            obs['Heliodate'] = mjd_to_datetime(obs['mjd']).strftime('%Y-%m-%d %H:%M:%S')
            obs['cur_oid'] = cur_oid
    return lcs


@cache()
def get_folded_plot_data(cur_oid, dr, period, offset=None, other_oids=frozenset(), min_mjd=None, max_mjd=None,
                         additional_data=immutabledict()):
    if offset is None:
        offset = MJD_OFFSET
    lcs = get_plot_data(cur_oid, dr, other_oids=other_oids, min_mjd=min_mjd, max_mjd=max_mjd,
                        additional_data=additional_data)
    for lc in lcs.values():
        for obs in lc:
            obs['folded_time'] = (obs['mjd'] - offset) % period
            obs['phase'] = obs['folded_time'] / period
    return lcs


MIMES = {
    'pdf': 'application/pdf',
    'png': 'image/png',
}


def save_fig(fig, fmt):
    bytes_io = BytesIO()
    if fmt == 'pdf':
        canvas = matplotlib.backends.backend_pgf.FigureCanvasPgf(fig)
        canvas.print_pdf(bytes_io)
    else:
        fig.savefig(bytes_io, format=fmt)
    return bytes_io


def plot_data(oid, dr, data, fmt='png', caption=True):
    usetex = fmt == 'pdf'

    lcs = {}
    seen_filters = set()
    for lc_oid, lc in data.items():
        if len(lc) == 0:
            continue
        first_obs = lc[0]
        fltr = first_obs['filter']

        marker = 's'
        if lc_oid == oid:
            marker = 'o'
        if fltr not in ZTF_FILTERS:
            marker = 'd'

        marker_size = 12
        if lc_oid == oid:
            marker_size = 24
        if fltr not in ZTF_FILTERS:
            marker_size = 36

        zorder = 1
        if lc_oid == oid:
            zorder = 2
        if fltr not in ZTF_FILTERS:
            zorder = 3

        lcs[lc_oid] = {
            'filter': fltr,
            't': [obs['mjd'] for obs in lc],
            'm': [obs['mag'] for obs in lc],
            'err': [obs['magerr'] for obs in lc],
            'color': FILTER_COLORS[fltr],
            'marker_size': marker_size,
            'label_errorbar': '' if fltr in seen_filters or fltr not in ZTF_FILTERS else fltr,
            'label_scatter': '' if fltr in seen_filters or fltr in ZTF_FILTERS else fltr,
            'marker': marker,
            'zorder': zorder,
        }
        seen_filters.add(fltr)

    fig = matplotlib.figure.Figure(dpi=300, figsize=(6.4, 4.8), constrained_layout=True)
    if caption:
        fig.text(
            0.50,
            0.005,
            f'Generated with the SNAD ZTF viewer on {datetime.now().date()}',
            ha='center',
            fontdict=dict(size=8, color='grey', usetex=usetex),
        )
    ax = fig.subplots()
    ax.invert_yaxis()
    ax.set_title(str(oid), usetex=usetex)
    ax.set_xlabel('MJD', usetex=usetex)
    ax.set_ylabel('magnitude', usetex=usetex)
    ax.xaxis.set_minor_locator(AutoMinorLocator(2))
    ax.yaxis.set_minor_locator(AutoMinorLocator(2))
    ax.tick_params(which='major', direction='in', length=6, width=1.5)
    ax.tick_params(which='minor', direction='in', length=4, width=1)
    for lc in lcs.values():
        ax.errorbar(
            lc['t'],
            lc['m'],
            lc['err'],
            c=lc['color'],
            label=lc['label_errorbar'],
            marker='',
            zorder=lc['zorder'],
            ls='',
            alpha=0.7,
        )
        ax.scatter(
            lc['t'],
            lc['m'],
            c=lc['color'],
            label=lc['label_scatter'],
            marker=lc['marker'],
            s=lc['marker_size'],
            linewidths=0.5,
            edgecolors='black',
            zorder=lc['zorder'],
            alpha=0.7,
        )
    legend_anchor_y = -0.026 if usetex else -0.032
    handles, labels = zip(*sorted(zip(*ax.get_legend_handles_labels()), key=lambda hl: FILTERS_ORDER[hl[1]]))
    ax.legend(
        flip(handles, 3), flip(labels, 3),
        bbox_to_anchor=(1, legend_anchor_y),
        ncol=min(3, len(seen_filters)),
        columnspacing=0.5,
        frameon=False,
        handletextpad=0.0,
    )
    bytes_io = save_fig(fig, fmt)
    return bytes_io.getvalue()


def plot_folded_data(oid, dr, data, period, offset=None, repeat=None, fmt='png', caption=True):
    if repeat is None:
        repeat = 2

    usetex = fmt == 'pdf'

    lcs = {}
    seen_filters = set()
    for lc_oid, lc in data.items():
        if len(lc) == 0:
            continue
        first_obs = lc[0]
        fltr = first_obs['filter']
        lcs[lc_oid] = {
            'filter': fltr,
            'folded_time': np.array([obs['folded_time'] for obs in lc]),
            'phase': np.array([obs['phase'] for obs in lc]),
            'm': np.array([obs['mag'] for obs in lc]),
            'err': np.array([obs['magerr'] for obs in lc]),
            'color': FILTER_COLORS[fltr],
            'marker_size': 24 if lc_oid == oid else 12,
            'label': '' if fltr in seen_filters else fltr,
            'marker': 'o' if lc_oid == oid else 's',
            'zorder': 2 if lc_oid == oid else 1,
        }
        seen_filters.add(fltr)

    fig = matplotlib.figure.Figure(dpi=300, figsize=(6.4, 4.8), constrained_layout=True)
    if caption:
        fig.text(
            0.50,
            0.005,
            f'Generated with the SNAD ZTF viewer on {datetime.now().date()}',
            ha='center',
            fontdict=dict(size=8, color='grey', usetex=usetex),
        )
    ax = fig.subplots()
    ax.invert_yaxis()
    ax.set_title(f'{oid}, P = {period:.4g} days', usetex=usetex)
    ax.set_xlabel('phase', usetex=usetex)
    ax.set_ylabel('magnitude', usetex=usetex)
    ax.xaxis.set_minor_locator(AutoMinorLocator(2))
    ax.yaxis.set_minor_locator(AutoMinorLocator(2))
    ax.tick_params(which='major', direction='in', length=6, width=1.5)
    ax.tick_params(which='minor', direction='in', length=4, width=1)
    for lc_oid, lc in sorted(lcs.items(), key=lambda item: FILTERS_ORDER[item[1]['filter']]):
        for i in range(-1, repeat + 1):
            label = ''
            if i == 0:
                label = lc['label']
            ax.errorbar(
                lc['phase'] + i,
                lc['m'],
                lc['err'],
                c=lc['color'],
                label=label,
                marker='',
                zorder=lc['zorder'],
                ls='',
                alpha=0.7,
            )
            ax.scatter(
                lc['phase'] + i,
                lc['m'],
                c=lc['color'],
                label='',
                marker=lc['marker'],
                s=lc['marker_size'],
                linewidths=0.5,
                edgecolors='black',
                zorder=lc['zorder'],
                alpha=0.7,
            )
    ax.set_xlim([-0.1, repeat + 0.1])
    secax = ax.secondary_xaxis('top', functions=(lambda x: x * period, lambda x: x / period))
    secax.set_xlabel('Folded time, days')
    secax.minorticks_on()
    secax.tick_params(direction='in', which='both')
    legend_anchor_y = -0.026 if usetex else -0.032
    ax.legend(
        bbox_to_anchor=(1, legend_anchor_y),
        ncol=min(3, len(seen_filters)),
        columnspacing=0.5,
        frameon=False,
        handletextpad=0.0,
    )
    bytes_io = save_fig(fig, fmt)
    return bytes_io.getvalue()


def parse_figure_args_helper(args, data=None):
    fmt = args.get('format', 'png')
    other_oids = frozenset(args.getlist('other_oid'))
    min_mjd = args.get('min_mjd', None)
    if min_mjd is not None:
        min_mjd = float(min_mjd)
    max_mjd = args.get('max_mjd', None)
    if max_mjd is not None:
        max_mjd = float(max_mjd)
    caption = args.get('copyright', 'yes') != 'no'

    if fmt not in MIMES:
        return '', 404

    if data:
        data = parse_json_to_immutable(data)
    else:
        data = immutabledict()

    return dict(fmt=fmt, other_oids=other_oids, min_mjd=min_mjd, max_mjd=max_mjd, caption=caption, additional_data=data)


@app.server.route('/<dr>/figure/<int:oid>', methods=['GET', 'POST'])
def response_figure(dr, oid):
    kwargs = parse_figure_args_helper(request.args, request.get_data(cache=False))
    fmt = kwargs.pop('fmt')
    caption = kwargs.pop('caption')

    data = get_plot_data(oid, dr, **kwargs)
    img = plot_data(oid, dr, data, fmt=fmt, caption=caption)

    return Response(
        img,
        mimetype=MIMES[fmt],
        headers={'Content-disposition': f'attachment; filename={oid}.{fmt}'},
    )


@app.server.route('/<dr>/figure/<int:oid>/folded/<float:period>')
def response_figure_folded(dr, oid, period):
    kwargs = parse_figure_args_helper(request.args)
    fmt = kwargs.pop('fmt')
    caption = kwargs.pop('caption')

    repeat = request.args.get('repeat', None)
    if repeat is not None:
        repeat = int(repeat)

    data = get_folded_plot_data(oid, dr, period=period, **kwargs)
    img = plot_folded_data(oid, dr, data, period=period, repeat=repeat, fmt=fmt, caption=caption)

    return Response(
        img,
        mimetype=MIMES[fmt],
        headers={'Content-disposition': f'attachment; filename={oid}.{fmt}'},
    )


def get_csv(dr, oid):
    lc = find_ztf_oid.get_lc(oid, dr)
    if lc is None:
        raise NotFound
    df = pd.DataFrame.from_records(lc)
    string_io = StringIO()
    df.to_csv(string_io, index=False)
    return string_io.getvalue()


@app.server.route('/<dr>/csv/<int:oid>')
def response_csv(dr, oid):
    try:
        csv = get_csv(dr, oid)
    except NotFound:
        return '', 404
    return Response(
        csv,
        mimetype='text/csv',
        headers={'Content-disposition': f'attachment; filename={oid}.csv'},
    )


@app.server.route('/favicon.ico')
def favicon():
    return send_file('static/img/logo.svg', mimetype='image/svg+xml')

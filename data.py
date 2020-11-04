from io import BytesIO, StringIO

import matplotlib
import matplotlib.backends.backend_pgf
import matplotlib.figure
import pandas as pd
from flask import Response, request, send_file
from matplotlib.ticker import AutoMinorLocator

from app import app
from cache import cache
from cross import find_ztf_oid
from util import mjd_to_datetime, NotFound, FILTER_COLORS, FILTERS_ORDER


@cache()
def get_plot_data(cur_oid, dr, other_oids=frozenset(), min_mjd=None, max_mjd=None):
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
            obs['mjd_58000'] = obs['mjd'] - 58000
            obs['Heliodate'] = mjd_to_datetime(obs['mjd']).strftime('%Y-%m-%d %H:%m:%S')
            obs['oid'] = oid
            obs['fieldid'] = meta['fieldid']
            obs['rcid'] = meta['rcid']
            obs['filter'] = meta['filter']
            obs['mark_size'] = size
            obs['cur_oid'] = cur_oid
        lcs[oid] = lc
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


def plot_data(oid, dr, data, fmt='png'):
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
            't': [obs['mjd'] for obs in lc],
            'm': [obs['mag'] for obs in lc],
            'err': [obs['magerr'] for obs in lc],
            'color': FILTER_COLORS[fltr],
            'marker_size': 24 if lc_oid == oid else 12,
            'label': '' if fltr in seen_filters else fltr,
            'marker': 'o' if lc_oid == oid else 's',
            'zorder': 2 if lc_oid == oid else 1,
        }
        seen_filters.add(fltr)

    fig = matplotlib.figure.Figure(dpi=300)
    ax = fig.subplots()
    ax.invert_yaxis()
    if usetex:
        ax.set_title(rf'\underline{{\href{{https://ztf.snad.space/{dr}/view/{oid}}}{{\texttt{{{oid}}}}}}}', usetex=True)
    else:
        ax.set_title(str(oid))
    ax.set_xlabel('MJD', usetex=usetex)
    ax.set_ylabel('magnitude', usetex=usetex)
    ax.xaxis.set_minor_locator(AutoMinorLocator(2))
    ax.yaxis.set_minor_locator(AutoMinorLocator(2))
    ax.tick_params(which='major', direction='in', length=6, width=1.5)
    ax.tick_params(which='minor', direction='in', length=4, width=1)
    for lc_oid, lc in sorted(lcs.items(), key=lambda item: FILTERS_ORDER[item[1]['filter']]):
        ax.errorbar(
            lc['t'],
            lc['m'],
            lc['err'],
            c=lc['color'],
            label=lc['label'],
            marker='',
            zorder=lc['zorder'],
            ls='',
            alpha=0.7,
        )
        ax.scatter(
            lc['t'],
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
    ax.legend(loc='upper right', ncol=min(5, len(seen_filters)))
    bytes_io = save_fig(fig, fmt)
    return bytes_io.getvalue()


@app.server.route('/<dr>/figure/<int:oid>')
def response_figure(dr, oid):
    fmt = request.args.get('format', 'png')
    other_oids = frozenset(request.args.getlist('other_oid'))
    min_mjd = request.args.get('min_mjd', None)
    if min_mjd is not None:
        min_mjd = float(min_mjd)
    max_mjd = request.args.get('max_mjd', None)
    if max_mjd is not None:
        max_mjd = float(max_mjd)

    if fmt not in MIMES:
        return '', 404

    data = get_plot_data(oid, dr, other_oids=other_oids, min_mjd=min_mjd, max_mjd=max_mjd)
    img = plot_data(oid, dr, data, fmt=fmt)

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

from io import BytesIO, StringIO

import matplotlib
import matplotlib.figure
import pandas as pd
from flask import Response, request

from app import app
from cache import cache
from cross import find_ztf_oid
from util import mjd_to_datetime, NotFound, FILTER_COLORS


@cache()
def get_plot_data(cur_oid, dr, other_oids=frozenset(), min_mjd=None, max_mjd=None):
    oids = [cur_oid]
    oids.extend(other_oids)
    lcs = []
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
        lcs.extend(lc)
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
    lcs = {}
    for d in data:
        lc = lcs.setdefault(d['oid'], {})
        t = lc.setdefault('t', [])
        t.append(d['mjd'])
        m = lc.setdefault('m', [])
        m.append(d['mag'])
        err = lc.setdefault('err', [])
        err.append(d['magerr'])
        lc['color'] = FILTER_COLORS[d['filter']]

    fig = matplotlib.figure.Figure()
    ax = fig.subplots()
    ax.invert_yaxis()
    if fmt == 'pdf':
        ax.set_title(rf'\underline{{\href{{https://ztf.snad.space/{dr}/view/{oid}}}{{{oid}}}}}', usetex=True)
    else:
        ax.set_title(str(oid))
    ax.set_xlabel('MJD')
    ax.set_ylabel(r'$m$')
    ax.scatter(
        [d['mjd'] for d in data],
        [d['mag'] for d in data],
        s=[4 * d['mark_size'] for d in data],
        color=[FILTER_COLORS[d['filter']] for d in data],
    )
    for oid, lc in lcs.items():
        ax.errorbar(
            lc['t'],
            lc['m'],
            lc['err'],
            c=lc['color'],
            ms=0,
            ls='',
            label=str(oid),
        )

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


@app.server.route("/<dr>/csv/<int:oid>")
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


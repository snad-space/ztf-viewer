"""Matplotlib rendering for the figure routes.

Kept separate from `ztf_viewer.pages.figure` so it can run in the process pool: the pool's
spawn start method re-imports a submitted function's module in the child, and
`ztf_viewer.pages.figure` imports `ztf_viewer.app`, which builds the whole Dash app as an
import side effect. This module only pulls in matplotlib and plain data, so importing it in a
fresh worker is cheap and side-effect-free.
"""

import pathlib
from datetime import UTC, datetime
from io import BytesIO

import matplotlib
import matplotlib.backends.backend_pgf
import matplotlib.font_manager
import matplotlib.image
import matplotlib.lines
import matplotlib.textpath
import numpy as np
from matplotlib.ticker import AutoMinorLocator
from PIL import Image

from ztf_viewer.util import DENSE_LC_MIN_POINTS, FILTER_COLORS, FILTERS_ORDER, ZTF_FILTERS, flip

# A filter no catalog has claimed a colour for. The interactive figure passes FILTER_COLORS
# to plotly as a map and unknown filters just fall back to a default colour, so the
# downloadable figure must not be the only place that fails on one.
UNKNOWN_FILTER_COLOR = "#777777"

# Brightness the figure plots, keyed as the light-curve page's radio buttons name it. Fields
# are the ones `lc_data.plot_data` puts on every observation; `err_minus` is set only where the
# error bar is asymmetric, and `inverted` marks the magnitude-like axes, which grow downwards.
BRIGHTNESS = {
    "mag": {"value": "mag", "err": "magerr", "err_minus": None, "label": "magnitude", "inverted": True},
    "flux": {"value": "flux_Jy", "err": "fluxerr_Jy", "err_minus": None, "label": "flux, Jy", "inverted": False},
    "diffmag": {
        "value": "diffmag",
        "err": "diffmagerr_plus",
        "err_minus": "diffmagerr_minus",
        "label": "difference magnitude",
        "inverted": True,
    },
    "diffflux": {
        "value": "diffflux_Jy",
        "err": "difffluxerr_Jy",
        "err_minus": None,
        "label": "difference flux, Jy",
        "inverted": False,
    },
}
DEFAULT_BRIGHTNESS = "mag"


def _brightness_arrays(lc, brightness):
    """Brightness and its error bar, as matplotlib takes them."""
    fields = BRIGHTNESS[brightness]
    m = np.array([obs[fields["value"]] for obs in lc], dtype=float)
    err = np.array([obs[fields["err"]] for obs in lc], dtype=float)
    if fields["err_minus"] is None:
        return m, err
    err_minus = np.array([obs[fields["err_minus"]] for obs in lc], dtype=float)
    # matplotlib reads a 2 x N `yerr` as (below the point, above the point)
    return m, np.stack([err_minus, err])


LEGEND_MARKER_SIZE = 24


def _enlarge_legend_markers(legend):
    """Keep the legend readable for a light curve drawn with markers too small to see in it."""
    for handle in legend.legend_handles:
        if hasattr(handle, "set_sizes"):
            handle.set_sizes([LEGEND_MARKER_SIZE])


def _split_by_filter(lc):
    """Group one object's observations by passband, in the order the passbands first appear.

    A ZTF OID is a single passband by construction, but an external light curve is not: one
    Gaia source carries G, BP and RP, and one Pan-STARRS object g, r, i, z and y. Each of them
    has to be drawn -- and named in the legend -- on its own.
    """
    by_filter = {}
    for obs in lc:
        by_filter.setdefault(obs["filter"], []).append(obs)
    return by_filter.items()


def plot_folded_data(oid, data, period, repeat=None, fmt="png", caption=True, title=None, brightness=None):
    if repeat is None:
        repeat = 2

    usetex = fmt == "pdf"
    brightness = brightness or DEFAULT_BRIGHTNESS

    if title is None:
        title = str(oid)

    lcs = {}
    seen_filters = set()
    for lc_oid, lc in data.items():
        if len(lc) == 0:
            continue
        for fltr, obs_list in _split_by_filter(lc):
            m, err = _brightness_arrays(obs_list, brightness)
            is_dense = len(obs_list) >= DENSE_LC_MIN_POINTS
            lcs[lc_oid, fltr] = {
                "filter": fltr,
                "folded_time": np.array([obs["folded_time"] for obs in obs_list]),
                "phase": np.array([obs["phase"] for obs in obs_list]),
                "m": m,
                "err": err,
                "color": FILTER_COLORS.get(fltr, UNKNOWN_FILTER_COLOR),
                "marker_size": 1 if is_dense else (24 if lc_oid == oid else 12),
                "label": "" if fltr in seen_filters else fltr,
                "marker": "o" if lc_oid == oid else "s",
                "zorder": 0 if is_dense else (2 if lc_oid == oid else 1),
            }
            seen_filters.add(fltr)

    fig = matplotlib.figure.Figure(dpi=300, figsize=(6.4, 4.8), constrained_layout=True)
    if caption:
        fig.text(
            0.50,
            0.005,
            f"Generated with the SNAD ZTF viewer on {datetime.now(tz=UTC).date()}",
            ha="center",
            fontdict={"size": 8, "color": "grey", "usetex": usetex},
        )
    ax = fig.subplots()
    if BRIGHTNESS[brightness]["inverted"]:
        ax.invert_yaxis()
    ax.set_title(f"{title}, P = {period:.6g} days", usetex=usetex)
    ax.set_xlabel("phase", usetex=usetex)
    ax.set_ylabel(BRIGHTNESS[brightness]["label"], usetex=usetex)
    ax.xaxis.set_minor_locator(AutoMinorLocator(2))
    ax.yaxis.set_minor_locator(AutoMinorLocator(2))
    ax.tick_params(which="major", direction="in", length=6, width=1.5)
    ax.tick_params(which="minor", direction="in", length=4, width=1)
    for _key, lc in sorted(lcs.items(), key=lambda item: FILTERS_ORDER[item[1]["filter"]]):
        for i in range(-1, repeat + 1):
            label = ""
            if i == 0:
                label = lc["label"]
            ax.errorbar(
                lc["phase"] + i,
                lc["m"],
                lc["err"],
                c=lc["color"],
                label=label,
                marker="",
                zorder=lc["zorder"],
                ls="",
                alpha=0.7,
            )
            ax.scatter(
                lc["phase"] + i,
                lc["m"],
                c=lc["color"],
                label="",
                marker=lc["marker"],
                s=lc["marker_size"],
                linewidths=0.5,
                edgecolors="black",
                zorder=lc["zorder"],
                alpha=0.7,
            )
    ax.set_xlim([-0.1, repeat + 0.1])
    secax = ax.secondary_xaxis("top", functions=(lambda x: x * period, lambda x: x / period))
    secax.set_xlabel("Folded time, days")
    secax.minorticks_on()
    secax.tick_params(direction="in", which="both")
    legend_anchor_y = -0.026 if usetex else -0.032
    legend = ax.legend(
        bbox_to_anchor=(1, legend_anchor_y),
        ncol=min(3, len(seen_filters)),
        columnspacing=0.5,
        frameon=False,
        handletextpad=0.0,
    )
    _enlarge_legend_markers(legend)
    bytes_io = save_fig(fig, fmt)
    return bytes_io.getvalue()


def _light_curve_series(oid, data, brightness):
    """Every light curve in `data` as one plottable series per OID and passband.

    The object's own OID is drawn as round markers and an external survey as diamonds, each
    bigger than the one behind it, so a crowded plot still reads which points are whose.
    """
    lcs = {}
    seen_filters = set()
    for lc_oid, lc in data.items():
        if len(lc) == 0:
            continue
        for fltr, obs_list in _split_by_filter(lc):
            marker = "s"
            if lc_oid == oid:
                marker = "o"
            if fltr not in ZTF_FILTERS:
                marker = "d"

            is_dense = len(obs_list) >= DENSE_LC_MIN_POINTS

            marker_size = 12
            if lc_oid == oid:
                marker_size = 24
            if fltr not in ZTF_FILTERS:
                marker_size = 36
            if is_dense:
                marker_size = 1

            zorder = 1
            if lc_oid == oid:
                zorder = 2
            if fltr not in ZTF_FILTERS:
                zorder = 3
            if is_dense:
                zorder = 0

            m, err = _brightness_arrays(obs_list, brightness)

            lcs[lc_oid, fltr] = {
                "filter": fltr,
                "t": [obs["mjd"] for obs in obs_list],
                "m": m,
                "err": err,
                "color": FILTER_COLORS.get(fltr, UNKNOWN_FILTER_COLOR),
                "marker_size": marker_size,
                "label_errorbar": "" if fltr in seen_filters or fltr not in ZTF_FILTERS else fltr,
                "label_scatter": "" if fltr in seen_filters or fltr in ZTF_FILTERS else fltr,
                "marker": marker,
                "zorder": zorder,
            }
            seen_filters.add(fltr)
    return lcs, seen_filters


def _draw_light_curve(ax, lcs):
    """Draw the series of `_light_curve_series` on `ax`, error bars under the markers."""
    for lc in lcs.values():
        ax.errorbar(
            lc["t"],
            lc["m"],
            lc["err"],
            c=lc["color"],
            label=lc["label_errorbar"],
            marker="",
            zorder=lc["zorder"],
            ls="",
            alpha=0.7,
        )
        ax.scatter(
            lc["t"],
            lc["m"],
            c=lc["color"],
            label=lc["label_scatter"],
            marker=lc["marker"],
            s=lc["marker_size"],
            linewidths=0.5,
            edgecolors="black",
            zorder=lc["zorder"],
            alpha=0.7,
        )


def plot_data(oid, data, fmt="png", caption=True, title=None, brightness=None):
    usetex = fmt == "pdf"
    brightness = brightness or DEFAULT_BRIGHTNESS

    if title is None:
        title = str(oid)

    lcs, seen_filters = _light_curve_series(oid, data, brightness)

    fig = matplotlib.figure.Figure(dpi=300, figsize=(6.4, 4.8), constrained_layout=True)
    if caption:
        fig.text(
            0.50,
            0.005,
            f"Generated with the SNAD ZTF viewer on {datetime.now(tz=UTC).date()}",
            ha="center",
            fontdict={"size": 8, "color": "grey", "usetex": usetex},
        )
    ax = fig.subplots()
    if BRIGHTNESS[brightness]["inverted"]:
        ax.invert_yaxis()
    ax.set_title(title, usetex=usetex)
    ax.set_xlabel("MJD", usetex=usetex)
    ax.set_ylabel(BRIGHTNESS[brightness]["label"], usetex=usetex)
    ax.ticklabel_format(axis="x", style="plain", useOffset=False)
    ax.xaxis.set_minor_locator(AutoMinorLocator(2))
    ax.yaxis.set_minor_locator(AutoMinorLocator(2))
    ax.tick_params(which="major", direction="in", length=6, width=1.5)
    ax.tick_params(which="minor", direction="in", length=4, width=1)
    _draw_light_curve(ax, lcs)
    legend_anchor_y = -0.026 if usetex else -0.032
    handles, labels = zip(*sorted(zip(*ax.get_legend_handles_labels()), key=lambda hl: FILTERS_ORDER[hl[1]]))
    legend = ax.legend(
        list(flip(handles, 3)),
        list(flip(labels, 3)),
        bbox_to_anchor=(1, legend_anchor_y),
        ncol=min(3, len(seen_filters)),
        columnspacing=0.5,
        frameon=False,
        handletextpad=0.0,
    )
    _enlarge_legend_markers(legend)
    bytes_io = save_fig(fig, fmt)
    return bytes_io.getvalue()


# The link preview picture, drawn at 2:1. Every card renderer crops to about that ratio, so a
# plot drawn in the 4:3 of the downloadable figure would lose a slice of itself on the way.
CARD_FIGSIZE = (12.0, 6.0)
CARD_DPI = 100

# What a card is encoded as, and the media type and extension that go with it. Read by
# `ztf_viewer.pages.figure` for the response and by `ztf_viewer.social` for the `og:image` URL.
CARD_FORMAT = "WEBP"
CARD_MIMETYPE = "image/webp"
CARD_SUFFIX = "webp"

# Where the header's two lines of text begin, right of the logo, and how big they are set
HEADER_X = 0.115
TITLE_SIZE = 25
SUBTITLE_SIZE = 15

LOGO_PATH = pathlib.Path(__file__).parent / "static" / "img" / "logo.png"


def _ink_left(s, fontsize, weight):
    """How far a string's first glyph sits from its anchor, as a fraction of the card width.

    Two lines set at the same x still look ragged: the bold "6" of an OID carries more left
    side bearing than the "S" of "SNAD" below it. The reader aligns the ink, not the anchor, so
    the header subtracts the bearing from each line's x.
    """
    if not s:
        return 0.0
    prop = matplotlib.font_manager.FontProperties(size=fontsize, weight=weight)
    # TextPath is laid out in points, 72 to the inch
    return matplotlib.textpath.TextPath((0, 0), s, prop=prop).get_extents().x0 / (72 * CARD_FIGSIZE[0])


def _card_legend_marker(fltr):
    """A legend dot for a passband, in its colour."""
    return matplotlib.lines.Line2D(
        [],
        [],
        ls="",
        marker="o",
        markersize=9,
        markerfacecolor=FILTER_COLORS.get(fltr, UNKNOWN_FILTER_COLOR),
        markeredgecolor="black",
        markeredgewidth=0.5,
    )


def plot_card(oid, data, title=None, subtitle=None, brightness=None):
    """The light curve as a link preview card: the plot under a header naming the object.

    A card is read at a glance and at thumbnail size, so it carries the logo and larger type
    than the downloadable figure, and leaves out its generated-on caption.
    """
    brightness = brightness or DEFAULT_BRIGHTNESS

    if title is None:
        title = str(oid)

    lcs, seen_filters = _light_curve_series(oid, data, brightness)

    fig = matplotlib.figure.Figure(figsize=CARD_FIGSIZE, dpi=CARD_DPI, facecolor="white")

    logo_ax = fig.add_axes((0.026, 0.795, 0.075, 0.15))
    logo_ax.imshow(matplotlib.image.imread(LOGO_PATH))
    logo_ax.set_axis_off()
    fig.text(
        HEADER_X - _ink_left(title, TITLE_SIZE, "bold"),
        0.895,
        title,
        fontsize=TITLE_SIZE,
        fontweight="bold",
        va="center",
    )
    if subtitle:
        fig.text(
            HEADER_X - _ink_left(subtitle, SUBTITLE_SIZE, "normal"),
            0.827,
            subtitle,
            fontsize=SUBTITLE_SIZE,
            color="#555555",
            va="center",
        )

    ax = fig.add_axes((0.07, 0.13, 0.905, 0.63))
    if BRIGHTNESS[brightness]["inverted"]:
        ax.invert_yaxis()
    ax.set_xlabel("MJD", fontsize=15)
    ax.set_ylabel(BRIGHTNESS[brightness]["label"], fontsize=15)
    ax.ticklabel_format(axis="x", style="plain", useOffset=False)
    ax.xaxis.set_minor_locator(AutoMinorLocator(2))
    ax.yaxis.set_minor_locator(AutoMinorLocator(2))
    ax.tick_params(which="major", direction="in", length=6, width=1.5, labelsize=13)
    ax.tick_params(which="minor", direction="in", length=4, width=1)
    _draw_light_curve(ax, lcs)
    if seen_filters:
        # In the header rather than on the axes: a card is one picture, and a legend inside it
        # would sit on top of whichever corner of the light curve happens to be empty. Drawn
        # from proxy markers, so every passband reads as a dot of its colour at card size.
        labels = sorted(seen_filters, key=FILTERS_ORDER.__getitem__)
        fig.legend(
            [_card_legend_marker(fltr) for fltr in labels],
            labels,
            loc="upper right",
            bbox_to_anchor=(0.975, 0.95),
            ncol=min(4, len(labels)),
            columnspacing=0.8,
            frameon=False,
            fontsize=15,
        )

    return _card_bytes(fig)


def plot_site_card(title, subtitle):
    """The card a link to any page without a light curve of its own previews with.

    The site's own picture -- logo, name, and what the site is for -- at the same size and in
    the same format as an object's card, so a link to the front page or to a search unfurls as
    something rather than as a bare URL with a logo stamp beside it.
    """
    fig = matplotlib.figure.Figure(figsize=CARD_FIGSIZE, dpi=CARD_DPI, facecolor="white")

    logo_side = 0.36  # of the card's height; the logo is square and the card is 2:1
    logo_ax = fig.add_axes((0.5 - logo_side / 4, 0.46, logo_side / 2, logo_side))
    logo_ax.imshow(matplotlib.image.imread(LOGO_PATH))
    logo_ax.set_axis_off()

    fig.text(0.5, 0.34, title, fontsize=42, fontweight="bold", ha="center", va="center")
    fig.text(0.5, 0.20, subtitle, fontsize=19, color="#555555", ha="center", va="center")

    return _card_bytes(fig)


def _card_bytes(fig):
    """The figure in the form a card is served in: lossless WebP of a 256-colour image.

    A plot is flat colour on white, so a palette holds one with no visible loss, and the two
    steps compound -- for a dense light curve, 120 kB of truecolour PNG as matplotlib writes it
    become 44 kB of palette PNG and 36 kB of WebP. Lossless because the lossy encoders ring
    around the type at any quality that is smaller than this.
    """
    png = save_fig(fig, "png")
    png.seek(0)
    out = BytesIO()
    with Image.open(png) as img:
        palette = img.convert("RGB").quantize(colors=256, method=Image.MEDIANCUT)
        palette.convert("RGB").save(out, CARD_FORMAT, lossless=True, method=6)
    return out.getvalue()


def save_fig(fig, fmt):
    bytes_io = BytesIO()
    if fmt == "pdf":
        canvas = matplotlib.backends.backend_pgf.FigureCanvasPgf(fig)
        canvas.print_pdf(bytes_io)
    else:
        fig.savefig(bytes_io, format=fmt)
    return bytes_io

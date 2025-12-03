import pathlib
from collections import OrderedDict, defaultdict
from functools import lru_cache, partial
from itertools import chain
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import dash_dangerously_set_inner_html as ddsih
import dash_defer_js_import as dji
import json
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from astropy.coordinates import SkyCoord
from astropy.table import QTable
from astropy.units import Quantity
from dash import ALL, MATCH, Input, Output, State, dcc, html
from dash.dash_table import DataTable
from dash.exceptions import PreventUpdate
from immutabledict import immutabledict
from requests import ConnectionError

from ztf_viewer import brokers
from ztf_viewer.akb import akb
from ztf_viewer.app import app
from ztf_viewer.catalogs.conesearch import (
    ANTARES_QUERY,
    GAIA_DR3,
    PANSTARRS_DR2_QUERY,
    catalog_query_objects,
    get_catalog_query,
)
from ztf_viewer.catalogs.extinction import bayestar, sfd
from ztf_viewer.catalogs.skybot import SKYBOT_QUERY
from ztf_viewer.catalogs.snad.catalog import snad_catalog
from ztf_viewer.catalogs.vizier import find_vizier, vizier_catalog_details
from ztf_viewer.catalogs.ztf_dr import find_ztf_circle, find_ztf_oid
from ztf_viewer.catalogs.ztf_ref import ztf_ref
from ztf_viewer.config import JS9_URL, ZTF_FITS_PROXY_URL
from ztf_viewer.date_with_frac import DateWithFrac, correct_date
from ztf_viewer.exceptions import CatalogUnavailable, NotFound
from ztf_viewer.model_fit import model_fit
from ztf_viewer.lc_data.plot_data import MJD_OFFSET, get_folded_plot_data, get_plot_data
from ztf_viewer.lc_features import light_curve_features
from ztf_viewer.util import (
    FILTER_COLORS,
    INF,
    ZTF_FILTERS,
    available_drs,
    format_sep,
    html_from_astropy_table,
    immutabledefaultdict,
    list_join,
    min_max_mjd_short,
    to_str,
    hmjd_to_earth,
    DEFAULT_MIN_MAX_MJD,
)

LIGHT_CURVE_TABLE_COLUMNS = ("mjd", "mag", "magerr", "clrcoeff")

METADATA_FIELDS = (
    "nobs",
    "ngoodobs",
    "ngoodobs_short",
    "filter",
    "coord_string",
    "duration",
    "duration_short",
    "fieldid",
    "rcid",
    "ref_mag",
    "ref_magerr",
    "ref_flags",
)
SUMMARY_FIELDS = {
    "__objname": "Name",
    "__type": "Type",
    "__distance": "Distance",
    "__period": "Period, days",
}
SUMMARY_PROB_CLASS_MIN_PROBABILITY = 0.5

MARKER_SIZE = 10

LIST_MAXSHOW = 4

ADDITIONAL_LC_SEARCH_RADIUS_ARCSEC = 5.0

LIGHT_CURVE_VALUE_VERSION_ANNOTATION = defaultdict(str) | {
    "v0.1": " (Malanchev et al. 2021)",
    "v0.2": " (Aleo et al. 2022)",
}


BRIGHT_LABELS = {
    "mag": "mag",
    "flux_Jy": "flux, Jy",
    "diffmag": "diff mag",
    "diffflux_Jy": "diff flux, Jy",
}
BRIGHTERR_LABELS = {
    "magerr": "mag error",
    "fluxerr_Jy": "flux error, Jy",
    "diffmagerr_plus": "diff mag error +",
    "diffmagerr_minus": "diff mag error -",
    "difffluxerr_Jy": "diff flux error, Jy",
}


def parse_pathname(pathname):
    path = pathlib.Path(pathname)
    is_short = False
    if path.name == "short":
        is_short = True
        path = path.parent
    *_, dr, _, oid = path.parts
    return dr, int(oid), is_short


def parse_search(search_query: str) -> dict[str, Any]:
    parsed = parse_qs(urlparse(search_query).query)
    result = dict()
    result["min_mjd"] = float(parsed.get("min_mjd", [-INF])[-1])
    result["max_mjd"] = float(parsed.get("max_mjd", [INF])[-1])
    return result


def set_div_for_aladin(oid, version):
    ra, dec = find_ztf_oid.get_coord(oid, version)
    coord = find_ztf_oid.get_coord_string(oid, version)
    style = {"display": "none"}
    return html.Div(
        [
            html.Div(id="aladin-oid", children=f"{oid}", style=style),
            html.Div(id="aladin-ra", children=f"{ra}", style=style),
            html.Div(id="aladin-dec", children=f"{dec}", style=style),
            html.Div(id="aladin-coord", children=f"{coord}", style=style),
        ],
        id="for-aladin",
    )


@lru_cache(maxsize=128)
def get_layout(pathname, search):
    dr, oid, is_short = parse_pathname(pathname)
    try:
        find_ztf_oid.find(oid, dr)
    except NotFound:
        return html.Div(
            [
                html.H1("404"),
                html.H3(f"Object {oid} is not found in ZTF {dr.upper()}"),
            ]
        )
    other_drs = [other_dr for other_dr in available_drs if other_dr != dr]
    ra, dec = find_ztf_oid.get_coord(oid, dr)
    coord = find_ztf_oid.get_coord_string(oid, dr)

    short_min_mjd, short_max_mjd = min_max_mjd_short(dr)
    min_mjd, max_mjd = (short_min_mjd, short_max_mjd) if is_short else (-INF, INF)
    search_query_parsed = parse_search(search)
    min_mjd = search_query_parsed.get("min_mjd", min_mjd)
    max_mjd = search_query_parsed.get("max_mjd", max_mjd)

    try:
        features = light_curve_features(oid, dr, version="latest", min_mjd=min_mjd, max_mjd=max_mjd)
    except NotFound:
        features = None
    layout = html.Div(
        [
            html.Div("", id="placeholder", style={"display": "none"}),
            html.Div(f"{oid}", id="oid", style={"display": "none"}),
            html.Div(f"{dr}", id="dr", style={"display": "none"}),
            html.H2(id="title"),
            html.Div(id="akb-neighbours"),
            html.Div(set_akb_info(0, oid), id="akb-info"),
            html.Div(
                [
                    html.Div(
                        [
                            dcc.Graph(
                                id="graph",
                                config={
                                    "toImageButtonOptions": {"filename": str(oid)},
                                    "displaylogo": False,
                                },
                            ),
                            html.Div(
                                [
                                    "Download ",
                                    html.A("PNG", href=f"/{dr}/figure/{oid}?format=png", id="figure-png-link"),
                                    ", ",
                                    html.A("PDF", href=f"/{dr}/figure/{oid}?format=pdf", id="figure-pdf-link"),
                                    ", ",
                                    html.A("CSV", href=f"/{dr}/csv/{oid}", id="csv-link"),
                                ]
                            ),
                            html.Div(
                                [
                                    "MJD range:",
                                    dcc.Input(
                                        value=max(DEFAULT_MIN_MAX_MJD[0], min_mjd),
                                        id="min-mjd",
                                        type="number",
                                        placeholder=56789.0 if short_min_mjd == -INF else short_min_mjd,
                                        style={"width": "8em"},
                                    ),
                                    "—",
                                    dcc.Input(
                                        value=min(DEFAULT_MIN_MAX_MJD[1], max_mjd),
                                        id="max-mjd",
                                        type="number",
                                        placeholder=67890.1 if short_max_mjd == INF else short_max_mjd,
                                        style={"width": "8em"},
                                    ),
                                    " ",
                                    dcc.RadioItems(
                                        id="min-max-mjd-radio",
                                        options=[
                                            {
                                                "label": f"{DEFAULT_MIN_MAX_MJD[0]} ≤ MJD ≤ {DEFAULT_MIN_MAX_MJD[1]}",
                                                "value": "default",
                                            }
                                        ]
                                        + (short_min_mjd != -INF and short_max_mjd != INF)
                                        * [
                                            {
                                                "label": f"ZTF Private Survey: {short_min_mjd} ≤ MJD ≤ {short_max_mjd}",
                                                "value": "short",
                                            },
                                        ],
                                        value="short" if is_short else None,
                                        style={
                                            "display": "inline-block",
                                            "vertical-align": "middle",
                                        },
                                    ),
                                ],
                                style={"display": "inline-block"},
                            ),
                            dcc.RadioItems(
                                options=[
                                    {"label": "Full light curve", "value": "full"},
                                    {"label": "Folded light curve", "value": "folded"},
                                ],
                                value="full",
                                labelStyle={"display": "inline-block", "margin-right": "2em"},
                                id="light-curve-type",
                            ),
                            html.Div(
                                [
                                    html.Div(
                                        [
                                            dcc.Input(
                                                value=(
                                                    features.get("period_0_magn", features.get("period_0", None))
                                                    if features is not None
                                                    else None
                                                ),
                                                id="fold-period",
                                                placeholder="Period, days",
                                                type="number",
                                            ),
                                            " period, days",
                                        ],
                                        style={"width": "40%", "display": "inline-block", "margin-bottom": "1em"},
                                    ),
                                    html.Div(
                                        [
                                            dcc.Slider(
                                                value=0.0,
                                                id="fold-zero-phase",
                                                min=0.0,
                                                max=1.0,
                                                step=1e-3,
                                                marks={str(x): f"{x:.1f}" for x in np.linspace(0, 1, 11)},
                                            ),
                                        ],
                                        style={"width": "60%", "display": "inline-block", "vertical-align": "bottom"},
                                    ),
                                ],
                                id="fold-period-layout",
                                style={"display": "none", "vertical-align": "center"},
                            ),
                            dcc.Checklist(
                                id="additional-light-curves",
                                options=[
                                    {
                                        "label": "Closest Antares object, diff-photometry",
                                        "value": "antares",
                                        "disabled": False,
                                    },
                                    {
                                        "label": "Closest Pan-STARRS object, apparent",
                                        "value": "panstarrs",
                                        "disabled": False,
                                    },
                                    {"label": "Closest Gaia object, apparent", "value": "gaia", "disabled": False},
                                ],
                                value=[],
                                labelStyle={"display": "inline-block", "margin-right": "2em"},
                                style={"display": "block"},
                            ),
                            dcc.RadioItems(
                                options=[
                                    {"label": "Magnitude", "value": "mag"},
                                    {"label": "Flux", "value": "flux"},
                                    {"label": "diff Magnitude", "value": "diffmag"},
                                    {"label": "diff Flux", "value": "diffflux"},
                                ],
                                value="mag",
                                labelStyle={"display": "inline-block", "margin-right": "2em"},
                                id="light-curve-brightness",
                            ),
                            html.Div(
                                [
                                    html.Div(
                                        [
                                            html.B("Reference:"),
                                            html.Div(id="ref-mag"),
                                        ],
                                        style={
                                            "display": "inline-block",
                                            "vertical-align": "top",
                                        },
                                    ),
                                ],
                                id="ref-mag-layout",
                                style={"display": "none"},
                            ),
                        ],
                        id="graph-layout",
                        style={"flex-basis": "70%", "flex-grow": 1, "flex-shrink": 0},
                    ),
                    html.Div(
                        [
                            html.Div(className="JS9", id="JS9"),
                            dji.Import(src="/static/js/js9_helper.js"),
                            html.Div(id="fits-to-show"),
                            html.Div(id="skybot"),
                        ],
                        style={"min-width": "450px", "width": "20%", "vertical-align": "top", "flex-shrink": 0},
                    ),
                ],
                style={"display": "flex", "min-width": "100%", "overflow-x": "auto"},
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.H2("Model to fit"),
                                    dcc.Dropdown(model_fit.get_list_models(), id="models-fit-dd"),
                                    html.Div(id="dd-chosen-model"),
                                ]
                            ),
                            html.Div(
                                [
                                    html.H2("Parameters of fitting"),
                                    html.Div(id="results-fit"),
                                ],
                                id="results-fit-layout",
                                style={"display": "none"},
                            ),
                            html.Div(
                                id="results-fit-hidden",
                                style={"display": "none"},
                            ),
                            html.Div(
                                [
                                    html.H2("Summary"),
                                    html.Div(id="summary"),
                                ],
                                id="summary-layout",
                            ),
                            html.Div(
                                [
                                    html.H2("Neighbours"),
                                    html.Div(
                                        [
                                            html.H4("Different passband, same field"),
                                            dcc.Input(
                                                value="1",
                                                id="different_filter_radius",
                                                placeholder="Search radius, arcsec",
                                                type="number",
                                                step="0.1",
                                                min="0",
                                                max="60",
                                            ),
                                            " search radius, arcsec",
                                            html.Div(id="different_filter_neighbours"),
                                        ],
                                        style={"width": "45%", "display": "inline-block"},
                                    ),
                                    html.Div(
                                        [
                                            html.H4("Different field"),
                                            dcc.Input(
                                                value="1",
                                                id="different_field_radius",
                                                placeholder="Search radius, arcsec",
                                                type="number",
                                                step="0.1",
                                                min="0",
                                                max="60",
                                            ),
                                            " search radius, arcsec",
                                            html.Div(id="different_field_neighbours"),
                                        ],
                                        style={"width": "45%", "display": "inline-block"},
                                    ),
                                ],
                                id="neighbours-layout",
                            ),
                            html.Div(
                                [
                                    html.H2("Metadata"),
                                    html.Div(id="metadata"),
                                ],
                                id="metadata-layout",
                            ),
                        ],
                        id="neighbours-metadata-layout",
                        style={"width": "70%", "display": "inline-block"},
                    ),
                    html.Div(
                        [
                            html.H2(html.A("Aladin", href=f"//aladin.u-strasbg.fr/AladinLite/?target={coord}")),
                            set_div_for_aladin(oid, dr),
                            html.Div(
                                id="aladin-lite-div",
                                style={"width": "450px", "height": "450px"},
                            ),
                            dji.Import(src="/static/js/aladin_helper.js"),
                        ],
                        style={"width": "20%", "display": "inline-block", "vertical-align": "top"},
                        id="aladin-layout",
                    ),
                ],
                id="neighbours-metadata-aladin-layout",
            ),
            html.H3(
                [
                    "Same object in ",
                ]
                + list_join(", ", (html.A(dr.upper(), href=f"/{dr}/view/{oid}") for dr in other_drs))
            ),
            html.Div(
                [
                    html.H2("GCVS"),
                    dcc.Input(
                        value="10",
                        id=dict(type="search-radius", index="gcvs"),
                        placeholder="Search radius, arcsec",
                        type="number",
                    ),
                    " search radius, arcsec",
                    html.Div(id="gcvs-table"),
                ],
                id="gcvs",
            ),
            html.Div(
                [
                    html.H2("VSX"),
                    dcc.Input(
                        value="10",
                        id=dict(type="search-radius", index="vsx"),
                        placeholder="Search radius, arcsec",
                        type="number",
                    ),
                    " search radius, arcsec",
                    html.Div(id="vsx-table"),
                ],
                id="vsx",
            ),
            html.Div(
                [
                    html.H2("SPICY"),
                    dcc.Input(
                        value="1",
                        id=dict(type="search-radius", index="spicy"),
                        placeholder="Search radius, arcsec",
                        type="number",
                    ),
                    " search radius, arcsec",
                    html.Div(id="spicy-table"),
                ],
                id="spicy",
            ),
            html.Div(
                [
                    html.H2("SDSS DR16 Quasars"),
                    dcc.Input(
                        value="10",
                        id=dict(type="search-radius", index="sdss-dr16-quasars"),
                        placeholder="Search radius, arcsec",
                        type="number",
                    ),
                    "search radius, arcsec",
                    html.Div(id="sdss-dr16-quasars-table"),
                ]
            ),
            html.Div(
                [
                    html.H2("ATLAS"),
                    dcc.Input(
                        value="10",
                        id=dict(type="search-radius", index="atlas"),
                        placeholder="Search radius, arcsec",
                        type="number",
                    ),
                    " search radius, arcsec",
                    html.Div(id="atlas-table"),
                ],
                id="atlas",
            ),
            html.Div(
                [
                    html.H2("ZTF Catalog of Periodic Variable Stars"),
                    dcc.Input(
                        value="1",
                        id=dict(type="search-radius", index="ztf-periodic"),
                        placeholder="Search radius, arcsec",
                        type="number",
                        min="0.1",
                        max="3600",
                        step="0.1",
                    ),
                    " search radius, arcsec",
                    html.Div(id="ztf-periodic-table"),
                ],
                id="ztf-periodic",
            ),
            html.Div(
                [
                    html.H2("Pan-STARRS DR2 Stacked"),
                    dcc.Input(
                        value="5",
                        id=dict(type="search-radius", index="pan-starrs-dr2-stacked"),
                        placeholder="Search radius, arcsec",
                        type="number",
                        step="1",
                    ),
                    " search radius, arcsec",
                    html.Div(id="pan-starrs-dr2-stacked-table"),
                ],
                id="pan-starrs-dr2-stacked",
            ),
            html.Div(
                [
                    html.H2("Transient Name Server"),
                    dcc.Input(
                        value="5",
                        id=dict(type="search-radius", index="transient-name-server"),
                        placeholder="Search radius, arcsec",
                        type="number",
                        step="1",
                    ),
                    " search radius, arcsec",
                    html.Div(id="transient-name-server-table"),
                ],
                id="transient-name-server",
            ),
            html.Div(
                [
                    html.H2("Astro-COLIBRI"),
                    # Fake input for arcsec
                    dcc.Input(
                        value="3600",
                        id=dict(type="search-radius", index="astro-colibri"),
                        type="number",
                        step="1",
                        style={"display": "none"},
                    ),
                    # Real input for degrees
                    dcc.Input(
                        value="1",
                        id="astro-colibri-search-radius-degrees",
                        placeholder="Search radius, degrees",
                        type="number",
                        step="1",
                    ),
                    " search radius, degrees",
                    html.Div(id="astro-colibri-table"),
                ],
                id="astro-colibri",
            ),
            html.Div(
                [
                    html.H2("Astrocats"),
                    dcc.Input(
                        value="5",
                        id=dict(type="search-radius", index="astrocats"),
                        placeholder="Search radius, arcsec",
                        type="number",
                        step="1",
                    ),
                    " search radius, arcsec",
                    html.Div(id="astrocats-table"),
                ],
                id="astrocats",
            ),
            html.Div(
                [
                    html.H2("OGLE-III"),
                    dcc.Input(
                        value="10",
                        id=dict(type="search-radius", index="ogle"),
                        placeholder="Search radius, arcsec",
                        type="number",
                        min="0.1",
                        max="323999",
                    ),
                    " search radius, arcsec",
                    html.Div(id="ogle-table"),
                ],
                id="ogle",
            ),
            html.Div(
                [
                    html.H2("Simbad"),
                    dcc.Input(
                        value="50",
                        id=dict(type="search-radius", index="simbad"),
                        placeholder="Search radius, arcsec",
                        type="number",
                    ),
                    " search radius, arcsec",
                    html.Div(id="simbad-table"),
                ],
                id="simbad",
            ),
            html.Div(
                [
                    html.H2("Gaia EDR3 Distances"),
                    dcc.Input(
                        value="1",
                        id=dict(type="search-radius", index="gaia-edr3-distances"),
                        placeholder="Search radius, arcsec",
                        type="number",
                    ),
                    " search radius, arcsec",
                    html.Div(id="gaia-edr3-distances-table"),
                ],
                id="gaia-edr3-distances",
            ),
            html.Div(
                [
                    html.H2("Gaia DR3"),
                    dcc.Input(
                        value="1",
                        id=dict(type="search-radius", index="gaia-dr3"),
                        placeholder="Search radius, arcsec",
                        type="number",
                    ),
                    " search radius, arcsec",
                    html.Div(id="gaia-dr3-table"),
                ],
                id="gaia-dr3",
            ),
            html.Div(
                [
                    html.H2("ALeRCE"),
                    dcc.Input(
                        value="1",
                        id=dict(type="search-radius", index="alerce"),
                        placeholder="Search radius, arcsec",
                        type="number",
                    ),
                    " search radius, arcsec",
                    html.Div(id="alerce-table"),
                ],
                id="alerce",
            ),
            html.Div(
                [
                    html.H2("Fink"),
                    dcc.Input(
                        value="1",
                        id=dict(type="search-radius", index="fink"),
                        placeholder="Search radius, arcsec",
                        type="number",
                    ),
                    " search radius, arcsec",
                    html.Div(id="fink-table"),
                ],
                id="fink",
            ),
            html.Div(
                [
                    html.H2("Vizier"),
                    html.A(
                        "Search on Vizier website within",
                        id="search-on-vizier",
                        href=find_vizier.get_search_url(ra, dec, 0),
                    ),
                    " ",
                    dcc.Input(
                        value="1",
                        id="vizier-radius",
                        placeholder="Search radius, arcsec",
                        type="number",
                        step="0.1",
                        size="3",
                    ),
                    " arcsec",
                    html.Button(
                        "Show",
                        id="vizier-button",
                        n_clicks=0,
                        style={"display": "none"},
                    ),
                    html.Div(id="vizier-list"),
                ],
                id="vizier",
            ),
            html.Div(
                [
                    html.H2("Features"),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.A(
                                        "light-curve-feature", href="https://github.com/light-curve/light-curve-feature"
                                    ),
                                    " version",
                                ],
                                style={"display": "inline-block"},
                            ),
                            html.Div(style={"display": "inline-block", "width": "0.5em"}),
                            dcc.Dropdown(
                                id="features-api-version",
                                placeholder="light-curve-feature version",
                                options=[
                                    dict(value=v, label=f"{v}{LIGHT_CURVE_VALUE_VERSION_ANNOTATION[v]}")
                                    for v in sorted(light_curve_features.versions())
                                ],
                                value="latest",
                                multi=False,
                                clearable=False,
                                style={"width": 300, "display": "inline-block"},
                            ),
                        ],
                        style={"align-items": "center", "display": "flex"},
                    ),
                    html.Br(),
                    html.Div(id="features-list"),
                ],
                id="features",
            ),
            html.H2(
                [
                    "Download light curve of the single OID: ",
                    html.A("CSV", href=f"/{dr}/csv/{oid}"),
                    ", ",
                    html.A("JSON", href=find_ztf_oid.json_url(oid, dr)),
                ],
                id="download-lc",
            ),
            html.Div(
                [
                    html.H2("Light curve (single OID)"),
                    DataTable(
                        id="light-curve-table",
                        columns=[{"name": column, "id": column} for column in LIGHT_CURVE_TABLE_COLUMNS],
                    ),
                ],
                id="light-curve",
                style={"width": "75%"},
            ),
        ]
    )
    return layout


@app.callback(
    Output("title", "children"),
    [
        Input("oid", "children"),
        Input("dr", "children"),
    ],
)
def set_title(oid, dr):
    ra, dec = find_ztf_oid.get_coord(oid, dr)
    try:
        snad_name = snad_catalog.search_region(ra, dec, radius_arcsec=3)
        snad_name = f"{snad_name} — "
    except NotFound:
        snad_name = ""
    return f"{snad_name}{oid}"


@app.callback(
    Output("results-fit-layout", "style"),
    [Input("models-fit-dd", "value")],
    [State("results-fit-layout", "style")],
)
def show_fit_params(value, old_style):
    style = old_style.copy()
    if value:
        style["display"] = "inline"
    else:
        style["display"] = "none"
    return style


@app.callback(
    [
        Output("results-fit", "children"),
        Output("results-fit-hidden", "children"),
    ],
    [
        Input("oid", "children"),
        Input("dr", "children"),
        Input("different_filter_neighbours", "children"),
        Input("different_field_neighbours", "children"),
        Input("min-mjd", "value"),
        Input("max-mjd", "value"),
        Input("light-curve-type", "value"),
        Input("fold-period", "value"),
        Input("fold-zero-phase", "value"),
        Input(dict(type="ref-mag-input", index=ALL), "id"),
        Input(dict(type="ref-mag-input", index=ALL), "value"),
        Input(dict(type="ref-magerr-input", index=ALL), "id"),
        Input(dict(type="ref-magerr-input", index=ALL), "value"),
        Input("additional-light-curves", "value"),
        Input("webgl-is-available", "children"),
        Input("models-fit-dd", "value"),
    ],
)
def fit_lc(
    cur_oid,
    dr,
    different_filter,
    different_field,
    min_mjd,
    max_mjd,
    lc_type,
    period,
    phase0,
    ref_mag_ids,
    ref_mag_values,
    ref_magerr_ids,
    ref_magerr_values,
    additional_lc_types,
    webgl_available,
    name_model,
):
    if lc_type == "folded" and not period:
        raise PreventUpdate

    if min_mjd is not None and max_mjd is not None and min_mjd >= max_mjd:
        raise PreventUpdate

    ref_mag = immutabledefaultdict(
        lambda: np.inf, {id["index"]: value for id, value in zip(ref_mag_ids, ref_mag_values) if value is not None}
    )
    ref_magerr = immutabledefaultdict(
        float, {id["index"]: value for id, value in zip(ref_magerr_ids, ref_magerr_values) if value is not None}
    )

    external_data = immutabledict(
        {value: immutabledict({"radius_arcsec": ADDITIONAL_LC_SEARCH_RADIUS_ARCSEC}) for value in additional_lc_types}
    )

    # It is "0" or "1" or None
    webgl_available = True if webgl_available is None else bool(int(webgl_available))
    render_mode = "auto" if webgl_available else "svg"

    other_oids = neighbour_oids(different_filter, different_field)
    if lc_type == "full":
        lcs = get_plot_data(
            cur_oid,
            dr,
            other_oids=other_oids,
            min_mjd=min_mjd,
            max_mjd=max_mjd,
            ref_mag=ref_mag,
            ref_magerr=ref_magerr,
            external_data=external_data,
        )
    elif lc_type == "folded":
        offset = -(phase0 or 0.0) * period
        lcs = get_folded_plot_data(
            cur_oid,
            dr,
            period=period,
            offset=offset,
            other_oids=other_oids,
            min_mjd=min_mjd,
            max_mjd=max_mjd,
            ref_mag=ref_mag,
            ref_magerr=ref_magerr,
            external_data=external_data,
        )
    else:
        raise ValueError(f"{lc_type = } is unknown")

    lcs = list(chain.from_iterable(lcs.values()))
    df = pd.DataFrame.from_records(lcs)
    coord = find_ztf_oid.get_sky_coord(cur_oid, dr)
    ebv = sfd.ebv(coord)
    items = []
    column_width = 0
    params = {}
    if name_model:
        params = model_fit.fit(df, name_model, dr, ebv)
        items = [f"**{k}**: {np.round(float(params[k]), 3)}" for k in params.keys()]
        params = json.dumps(params)
        column_width = max(map(len, items), default=2) - 2
    params_show = html.Div(
        html.Ul([html.Li(dcc.Markdown(text)) for text in items], style={"list-style-type": "none"}),
        style={"columns": f"{column_width}ch"},
    )
    return params_show, params


@app.callback(
    Output("akb-neighbours", "children"),
    [
        Input("different_filter_neighbours", "children"),
        Input("different_field_neighbours", "children"),
    ],
)
def set_akb_neighbours(different_filter, different_field):
    if not akb.is_token_valid():
        return None

    oids = neighbour_oids(different_filter, different_field)
    labeled_oids = [oid for oid in oids if akb.oid_exists(oid)]
    if len(labeled_oids) == 0:
        return None

    return html.Div(
        ["Neighbour OID(s) have been labeled: "]
        + list_join(", ", (html.A(str(oid), href=f"./{oid}") for oid in labeled_oids)),
        className="attention",
    )


def set_akb_info(_, oid):
    if not akb.is_token_valid():
        return None

    available_tags = akb.get_tags()
    try:
        akb_item = akb.get_by_oid(oid)
        tags_enabled = frozenset(akb_item["tags"])
        description = akb_item["description"]
    except NotFound:
        tags_enabled = frozenset()
        description = ""

    def checklist_index(tag):
        return tag["priority"] // 10

    checklist_tags = {}
    for tag in available_tags:
        tags = checklist_tags.setdefault(checklist_index(tag), [])
        tags.append(tag)

    checklists = [
        html.Div(
            [
                html.Div(
                    dcc.Checklist(
                        id=dict(type="akb-tags", index=f"{row}-{column}"),
                        options=[{"label": tag["name"], "value": tag["name"]}],
                        value=[tag["name"]] if tag["name"] in tags_enabled else [],
                        labelStyle={"display": "inline-block"},
                    ),
                    title=tag["description"],
                    style={"display": "inline-block"},
                )
                for column, tag in enumerate(tags)
            ],
        )
        for row, tags in checklist_tags.items()
    ]

    edit_layout = checklists + [
        "Point tag name to see its description. ",
        "See instructions and tag editor ",
        html.A("here", href="/tags"),
        dcc.Textarea(
            id="akb-description",
            placeholder="Description",
            disabled=False,
            cols=80,
            rows=5,
            value=description,
        ),
        html.Br(),
        html.Button(
            "Submit",
            id="akb-submit",
            n_clicks=0,
        ),
        " ",
        html.Div("", id="akb-submitted", style={"display": "inline-block"}),
        html.Br(),
        html.Button(
            "Reset",
            id="akb-reset",
            n_clicks=0,
        ),
    ]

    log = akb.get_object_log(oid)
    for entry in log:
        entry["tags_str"] = ", ".join(chain(*entry["tags"]))
        entry["changed_by_str"] = ", ".join(entry["changed_by"])
    log_layout = DataTable(
        data=log,
        columns=[
            {"id": "tags_str", "name": "Tags"},
            {"id": "description", "name": "Description"},
            {"id": "changed_by_str", "name": "Changed by"},
            {"id": "changed_at", "name": "Changed at"},
        ],
        page_size=5,
    )

    children = html.Div(
        [
            html.Div(
                edit_layout,
                style={"width": "50%", "display": "table-cell", "vertical_align": "top"},
            ),
            html.Div(
                log_layout,
                style={"width": "50%", "display": "table-cell", "vertical_align": "top"},
            ),
        ],
        style={
            "display": "table",
        },
    )

    return children


app.callback(
    Output("akb-info", "children"),
    [Input("akb-reset", "n_clicks")],
    [State("oid", "children")],
)(set_akb_info)


@app.callback(
    Output("akb-submitted", "children"),
    [Input("akb-submit", "n_clicks")],
    [
        State("oid", "children"),
        State(dict(type="akb-tags", index=ALL), "value"),
        State("akb-description", "value"),
    ],
)
def update_akb(n_clicks, oid, tags, description):
    if n_clicks == 0 or n_clicks is None or tags is None:
        raise PreventUpdate
    if description is None:
        description = ""
    tags = list(chain.from_iterable(tags))
    try:
        akb.post_object(oid, tags, description)
        return "Submitted"
    except RuntimeError:
        return "Error occurred"


@app.callback(
    [
        Output("min-mjd", "value"),
        Output("max-mjd", "value"),
    ],
    [Input("min-max-mjd-radio", "value")],
    [State("dr", "children")],
)
def set_min_max_mjd(value, dr):
    match value:
        case None:
            raise PreventUpdate
        case "short":
            return min_max_mjd_short(dr)
        case "default":
            return DEFAULT_MIN_MAX_MJD
    raise PreventUpdate


@app.callback(
    Output("min-max-mjd-radio", "value"),
    [Input("min-mjd", "n_submit"), Input("max-mjd", "n_submit")],
    [State("min-mjd", "value"), State("max-mjd", "value"), State("dr", "children")],
)
def update_min_max_mjd_radio(_n_min_mjd, _n_max_mjd, min_mjd, max_mjd, dr):
    try:
        min_mjd, max_mjd = float(min_mjd), float(max_mjd)
    except (TypeError, ValueError):
        raise PreventUpdate
    if min_mjd >= max_mjd:
        raise PreventUpdate
    min_mjd_short, max_mjd_short = min_max_mjd_short(dr)
    if abs(min_mjd - min_mjd_short) < 1e-5 and abs(max_mjd - max_mjd_short) < 1e-5:
        return "short"
    if abs(min_mjd - DEFAULT_MIN_MAX_MJD[0]) < 1e-5 and abs(max_mjd - DEFAULT_MIN_MAX_MJD[1]) < 1e-5:
        return "default"
    return None


@app.callback(
    Output("fold-period-layout", "style"), [Input("light-curve-type", "value")], [State("fold-period-layout", "style")]
)
def show_fold_period_layout(light_curve_type, old_style):
    style = old_style.copy()
    if light_curve_type == "folded":
        style["display"] = "inline"
    else:
        style["display"] = "none"
    return style


@app.callback(
    Output("additional-light-curves", "options"),
    [Input("oid", "children"), Input("dr", "children"), Input("additional-light-curves", "value")],
    [State("additional-light-curves", "options")],
)
def update_additional_light_curve_options(oid, dr, values, old_options):
    if len(values) == 0:
        raise PreventUpdate
    options_dict = {option["value"]: option for option in old_options}
    for value in values:
        if value == "antares":
            option = get_antares_lc_option(oid, dr, old=options_dict[value])
        elif value == "gaia":
            option = get_gaia_lc_option(oid, dr, old=options_dict[value])
        elif value == "panstarrs":
            option = get_panstarrs_lc_option(oid, dr, old=options_dict[value])
        else:
            raise ValueError(f'additional light curve value "{value}" unknown')
        options_dict[value] = option
    return list(options_dict.values())


def get_antares_lc_option(oid, dr, old):
    option = old.copy()
    ra, dec = find_ztf_oid.get_coord(oid, dr)
    try:
        row = ANTARES_QUERY.find_closest(ra, dec, radius_arcsec=ADDITIONAL_LC_SEARCH_RADIUS_ARCSEC)
    except NotFound:
        option["label"] = f"Antares object (not found in {ADDITIONAL_LC_SEARCH_RADIUS_ARCSEC}″)"
        option["disabled"] = True
    except CatalogUnavailable:
        option["label"] = "Antares API is unavailable now"
        option["disabled"] = False
    else:
        option["label"] = f'Antares {row[ANTARES_QUERY.id_column]} ({np.round(row["separation"], 1)}″), diff-photometry'
        option["disabled"] = False
    return option


def get_gaia_lc_option(oid, dr, old):
    option = old.copy()
    ra, dec = find_ztf_oid.get_coord(oid, dr)
    try:
        row = GAIA_DR3.find_closest(ra, dec, radius_arcsec=ADDITIONAL_LC_SEARCH_RADIUS_ARCSEC, has_light_curve=True)
    except NotFound:
        option["label"] = f"Gaia object (not found in {ADDITIONAL_LC_SEARCH_RADIUS_ARCSEC}″)"
        option["disabled"] = True
    else:
        option["label"] = f'Gaia object {row[GAIA_DR3.id_column]} ({np.round(row["separation"], 1)}″), apparent'
        option["disabled"] = False
    # Checxk if we can load data
    try:
        _ = GAIA_DR3.closest_light_curve(
            ra, dec, radius_arcsec=ADDITIONAL_LC_SEARCH_RADIUS_ARCSEC, fail_on_empty=False, fail_on_unavailable=True
        )
    except CatalogUnavailable:
        option["label"] = "Gaia DataLink is unavailable now"
        option["disabled"] = False
    return option


def get_panstarrs_lc_option(oid, dr, old):
    option = old.copy()
    ra, dec = find_ztf_oid.get_coord(oid, dr)
    try:
        row = PANSTARRS_DR2_QUERY.find_closest(ra, dec, radius_arcsec=ADDITIONAL_LC_SEARCH_RADIUS_ARCSEC)
    except NotFound:
        option["label"] = f"Pan-STARRS object (not found in {ADDITIONAL_LC_SEARCH_RADIUS_ARCSEC}″)"
        option["disabled"] = True
    except CatalogUnavailable:
        option["label"] = "MAST Pan-STARRS archive is unavailable now"
        option["disabled"] = False
    else:
        option["label"] = (
            f'Pan-STARRS {row[PANSTARRS_DR2_QUERY.id_column]} ({np.round(row["separation"], 1)}″), apparent'
        )
        option["disabled"] = False
    return option


@app.callback(
    Output("ref-mag-layout", "style"),
    [Input("light-curve-brightness", "value")],
    [State("ref-mag-layout", "style")],
)
def show_ref_mag_layout(brightness_type, old_style):
    style = old_style.copy()
    if brightness_type in {"diffmag", "diffflux"}:
        style["display"] = "inline"
    else:
        style["display"] = "none"
    return style


@app.callback(
    Output("ref-mag", "children"),
    [
        Input("oid", "children"),
        Input("dr", "children"),
        Input("different_filter_neighbours", "children"),
        Input("different_field_neighbours", "children"),
        Input("light-curve-brightness", "value"),
    ],
)
def show_ref_mag_or_magerr(oid, dr, different_filter, different_field, brightness_type):
    if brightness_type not in {"diffmag", "diffflux"}:
        raise PreventUpdate
    oids = sorted(neighbour_oids(different_filter, different_field) | {oid}, key=int)

    filters = defaultdict(list)
    for objectid in oids:
        fltr = find_ztf_oid.get_meta(objectid, dr)["filter"]
        filters[fltr].append(objectid)

    layout = []
    for fltr in ZTF_FILTERS:
        if fltr not in filters:
            continue
        filter_layout = [
            html.Div(
                html.B(fltr),
            ),
        ]
        for objectid in filters[fltr]:
            filter_layout.append(
                html.Div(
                    [
                        html.A(
                            objectid,
                            href=None,
                            id={"type": "ref-mag-link", "index": objectid},
                            n_clicks=0,
                            style={"display": "inline", "border-bottom": "1px dashed", "text-decoration": "none"},
                        ),
                        html.Br(),
                        html.Div(
                            "mag ",
                            style={"display": "inline"},
                        ),
                        dcc.Input(
                            value=None,
                            id={"type": "ref-mag-input", "index": objectid},
                            placeholder="mag",
                            type="number",
                            maxLength=6,
                            step=0.001,
                            style={"width": "6em", "display": "inline"},
                        ),
                        html.Div(
                            "  err ",
                            style={"display": "inline"},
                        ),
                        dcc.Input(
                            value=None,
                            id={"type": "ref-magerr-input", "index": objectid},
                            placeholder="mag err",
                            type="number",
                            maxLength=5,
                            min=0,
                            step=0.001,
                            style={"width": "5em", "display": "inline"},
                        ),
                    ],
                )
            )
        layout.append(
            html.Div(
                filter_layout,
                style={"display": "inline-block", "width": "50%", "vertical-align": "top"},
            )
        )
    return layout


@app.callback(
    [
        Output(dict(type="ref-mag-input", index=MATCH), "value"),
        Output(dict(type="ref-magerr-input", index=MATCH), "value"),
    ],
    [Input("dr", "children"), Input(dict(type="ref-mag-link", index=MATCH), "n_clicks")],
    [
        State(dict(type="ref-mag-link", index=MATCH), "id"),
    ],
)
def set_ref_mag_magerr(dr, _n_clicks, ref_mag_link_id):
    objectid = ref_mag_link_id["index"]
    try:
        ref = ztf_ref.get(objectid, dr)
    except (NotFound, CatalogUnavailable):
        raise PreventUpdate
    ref_mag = np.round(ref["mag"] + ref["magzp"], decimals=3)
    ref_magerr = np.round(ref["sigmag"], decimals=3)
    return ref_mag, ref_magerr


@app.callback(
    Output("summary", "children"),
    [
        Input("oid", "children"),
        Input("dr", "children"),
        Input("different_filter_neighbours", "children"),
        Input("different_field_neighbours", "children"),
        Input(dict(type="search-radius", index=ALL), "id"),
        Input(dict(type="search-radius", index=ALL), "value"),
    ],
)
def get_summary(oid, dr, different_filter, different_field, radius_ids, radius_values):
    if None in radius_values:
        raise PreventUpdate
    radii = {id["index"]: float(value) for id, value in zip(radius_ids, radius_values)}
    ra, dec = find_ztf_oid.get_coord(oid, dr)
    coord = find_ztf_oid.get_sky_coord(oid, dr)

    elements = OrderedDict()
    for catalog, query in catalog_query_objects().items():
        try:
            table = query.find(ra, dec, radii[catalog])
        except (NotFound, CatalogUnavailable, KeyError):
            continue
        idx = np.argmin(table["separation"])
        row = table[idx]
        for table_field, display_name in SUMMARY_FIELDS.items():
            try:
                value = row[table_field]
                if not isinstance(value, np.ndarray) and not isinstance(value, Quantity) and not value:
                    continue
                if table_field == "__distance" and table["__distance"].unit is not None:
                    value = value * table["__distance"].unit
                value = to_str(value).strip()
            except KeyError:
                continue
            if value == "":
                continue

            bra_list = []
            if table_field == "__distance" and "__redshift" in row.columns and row["__redshift"]:
                bra_list.append(f'z={to_str(row["__redshift"])}')
            if "__event_mjd" in row.columns and row["__event_mjd"]:
                bra_list.append(f'MJD {to_str(row["__event_mjd"], float_decimal_digits=1)}')
            bra = ", ".join(bra_list) + ", " if bra_list else ""
            cket = ""

            values = elements.setdefault(display_name, [])
            values.append(
                html.Div(
                    [
                        f'{value} ({bra}{format_sep(row["separation"])} ',
                        html.A(
                            query.query_name,
                            href=f"#{catalog}",
                            style={"border-bottom": "1px dashed", "text-decoration": "none"},
                        ),
                        f"{cket})",
                    ],
                    style={"display": "inline"},
                )
            )
    try:
        features = light_curve_features(oid, dr, version="latest")
        period = features.get("period_0_magn", features.get("period_0"))
        period_s2n = features.get("period_s_to_n_0_magn", features.get("period_s_to_n_0"))
        el = elements.setdefault("Period, days", [])
        el.insert(
            0,
            html.Div(
                [
                    f"{period:.3f} (",
                    html.A(
                        "periodogram",
                        href="#features",
                        style={"border-bottom": "1px dashed", "text-decoration": "none"},
                    ),
                    f" S/N={period_s2n:.3f})",
                ],
                style={"display": "inline"},
            ),
        )
    except NotFound:
        pass

    ml_classifications = []
    for catalog, query in catalog_query_objects().items():
        try:
            table = query.find(ra, dec, radii[catalog])
        except (NotFound, CatalogUnavailable, KeyError):
            continue
        if len(table) == 0:
            continue
        idx = np.argmin(table["separation"])
        row = table[idx]
        for pretty_name, column in query._prob_class_columns.items():
            if len(row[column]) == 0:
                continue
            class_name, prob = max(row[column].items(), key=lambda x: x[1])
            if prob < SUMMARY_PROB_CLASS_MIN_PROBABILITY:
                continue
            ml_classifications.append(
                html.Div(
                    [
                        f'{prob * 100:.0f}% {class_name} ({format_sep(row["separation"])}',
                        html.A(
                            query.query_name,
                            href=f"#{catalog}",
                            style={"border-bottom": "1px dashed", "text-decoration": "none"},
                        ),
                        # nothing if no name, otherwise space + name
                        pretty_name and f" {pretty_name}",
                        ")",
                    ],
                    style={"display": "inline"},
                )
            )
    if len(ml_classifications) > 0:
        elements["ML classifications"] = ml_classifications

    # Put these elements first
    for element_name in reversed(["Name", "Type", "ML classifications"]):
        try:
            elements.move_to_end(element_name, last=False)
        except KeyError:
            pass

    other_oids = neighbour_oids(different_filter, different_field)
    lcs = get_plot_data(oid, dr, other_oids=other_oids)
    mags = {}
    for obs in chain.from_iterable(lcs.values()):
        mags.setdefault(obs["filter"], []).append(obs["mag"])
    mean_mag = {fltr: np.mean(m) for fltr, m in mags.items()}
    elements["Average mag (including neighbourhood)"] = [
        f"{fltr} {mean_mag[fltr]: .2f}" for fltr in ZTF_FILTERS if fltr in mean_mag
    ]
    if "zg" in mean_mag and "zr" in mean_mag:
        elements["Average mag (including neighbourhood)"].append(f'(zg–zr) {mean_mag["zg"] - mean_mag["zr"]: .2f}')

    elements["Extinction"] = [f"SFD E(B-V) = {sfd.ebv(coord):.2f}"]
    try:
        table = get_catalog_query("Gaia EDR3 Distances").find(ra, dec, 1)
        row = QTable(table[np.argmin(table["separation"])])

        distance = row["__distance"]
        af = bayestar(SkyCoord(coord, distance=distance))
        elements["Extinction"].append(
            f'Bayestar & Gaia EDR distance Ag = {af["zg"]:.2f} Ar = {af["zr"]:.2f} Ai = {af["zi"]:.2f}'
        )
    except (NotFound, CatalogUnavailable):
        pass

    elements["Search in brokers"] = [
        brokers.alerce_tag(ra, dec),
        brokers.antares_tag(ra, dec, oid=oid),
        brokers.fink_tag(ra, dec),
        brokers.mars_tag(ra, dec),
    ]

    elements["Coordinates"] = [
        f"Eq {find_ztf_oid.get_coord_string(oid, dr, frame=None)}",
        f'Gal {find_ztf_oid.get_coord_string(oid, dr, frame="galactic")}',
    ]

    div = html.Div(
        html.Ul(
            [html.Li([html.B(k), ": "] + list_join(", ", v)) for k, v in elements.items()],
            style={"list-style-type": "none"},
        ),
    )
    return div


@app.callback(
    Output("metadata", "children"),
    [Input("oid", "children"), Input("dr", "children")],
)
def get_metadata(oid, dr):
    meta = find_ztf_oid.get_meta(oid, dr).copy()
    meta["coord_string"] = find_ztf_oid.get_coord_string(oid, dr)

    try:
        ref = ztf_ref.get(oid, dr)
    except (NotFound, CatalogUnavailable):
        pass
    else:
        meta["ref_mag"] = ref["mag"] + ref["magzp"]
        meta["ref_magerr"] = ref["sigmag"]
        meta["ref_flags"] = ref["flags"]

    items = [f"**{k}**: {to_str(meta[k])}" for k in METADATA_FIELDS if k in meta]
    column_width = max(map(len, items)) - 2
    div = html.Div(
        html.Ul([html.Li(dcc.Markdown(text)) for text in items], style={"list-style-type": "none"}),
        style={"columns": f"{column_width}ch"},
    )
    return div


def neighbour_oids(different_filter, different_field) -> frozenset:
    if not isinstance(different_filter, list):
        different_filter = []
    if not isinstance(different_field, list):
        different_field = []
    oids = frozenset(
        div["props"]["id"].rsplit("-", maxsplit=1)[-1]
        for div in different_filter + different_field
        if isinstance(div, dict)
    )
    return oids


@app.callback(
    Output("graph", "figure"),
    [
        Input("oid", "children"),
        Input("dr", "children"),
        Input("different_filter_neighbours", "children"),
        Input("different_field_neighbours", "children"),
        Input("min-mjd", "value"),
        Input("max-mjd", "value"),
        Input("light-curve-brightness", "value"),
        Input("light-curve-type", "value"),
        Input("fold-period", "value"),
        Input("fold-zero-phase", "value"),
        Input(dict(type="ref-mag-input", index=ALL), "id"),
        Input(dict(type="ref-mag-input", index=ALL), "value"),
        Input(dict(type="ref-magerr-input", index=ALL), "id"),
        Input(dict(type="ref-magerr-input", index=ALL), "value"),
        Input("additional-light-curves", "value"),
        Input("webgl-is-available", "children"),
        Input("models-fit-dd", "value"),
        Input("results-fit-hidden", "children"),
    ],
)
def set_figure(
    cur_oid,
    dr,
    different_filter,
    different_field,
    min_mjd,
    max_mjd,
    brightness_type,
    lc_type,
    period,
    phase0,
    ref_mag_ids,
    ref_mag_values,
    ref_magerr_ids,
    ref_magerr_values,
    additional_lc_types,
    webgl_available,
    name_model,
    fit_params,
):
    if lc_type == "folded" and not period:
        raise PreventUpdate

    if min_mjd is not None and max_mjd is not None and min_mjd >= max_mjd:
        raise PreventUpdate

    if brightness_type == "mag":
        bright = "mag"
        brighterr = "magerr"
        brighterr_minus = None
    elif brightness_type == "flux":
        bright = "flux_Jy"
        brighterr = "fluxerr_Jy"
        brighterr_minus = None
    elif brightness_type == "diffmag":
        bright = "diffmag"
        brighterr = "diffmagerr_plus"
        brighterr_minus = "diffmagerr_minus"
    elif brightness_type == "diffflux":
        bright = "diffflux_Jy"
        brighterr = "difffluxerr_Jy"
        brighterr_minus = None
    else:
        raise ValueError(f'Wrong brightness_type "{brightness_type}"')

    ref_mag = immutabledefaultdict(
        lambda: np.inf, {id["index"]: value for id, value in zip(ref_mag_ids, ref_mag_values) if value is not None}
    )
    ref_magerr = immutabledefaultdict(
        float, {id["index"]: value for id, value in zip(ref_magerr_ids, ref_magerr_values) if value is not None}
    )

    external_data = immutabledict(
        {value: immutabledict({"radius_arcsec": ADDITIONAL_LC_SEARCH_RADIUS_ARCSEC}) for value in additional_lc_types}
    )

    # It is "0" or "1" or None
    webgl_available = True if webgl_available is None else bool(int(webgl_available))
    render_mode = "auto" if webgl_available else "svg"

    other_oids = neighbour_oids(different_filter, different_field)
    if lc_type == "full":
        lcs = get_plot_data(
            cur_oid,
            dr,
            other_oids=other_oids,
            min_mjd=min_mjd,
            max_mjd=max_mjd,
            ref_mag=ref_mag,
            ref_magerr=ref_magerr,
            external_data=external_data,
        )
    elif lc_type == "folded":
        offset = -(phase0 or 0.0) * period
        lcs = get_folded_plot_data(
            cur_oid,
            dr,
            period=period,
            offset=offset,
            other_oids=other_oids,
            min_mjd=min_mjd,
            max_mjd=max_mjd,
            ref_mag=ref_mag,
            ref_magerr=ref_magerr,
            external_data=external_data,
        )
    else:
        raise ValueError(f"{lc_type = } is unknown")

    lcs = list(chain.from_iterable(lcs.values()))
    if brightness_type in {"mag", "diffmag"}:
        y_min = min(obs[bright] - obs[brighterr] for obs in lcs if np.isfinite(obs[bright]) and obs[brighterr] < 1)
        y_max = max(obs[bright] + obs[brighterr] for obs in lcs if np.isfinite(obs[bright]) and obs[brighterr] < 1)
        y_ampl = y_max - y_min
        range_y = [y_max + 0.1 * y_ampl, y_min - 0.1 * y_ampl]
    elif brightness_type in {"flux", "diffflux"}:
        y_min = min(obs[bright] - obs[brighterr] for obs in lcs)
        y_max = max(obs[bright] + obs[brighterr] for obs in lcs)
        y_ampl = y_max - y_min
        range_y = [min(0.0, y_min - 0.1 * y_ampl), y_max + 0.1 * y_ampl]
    else:
        raise ValueError(f'Wrong brightness_type "{brightness_type}"')
    df = pd.DataFrame.from_records(lcs)
    if lc_type == "full":
        figure = px.scatter(
            df,
            x=f"mjd_{MJD_OFFSET}",
            y=bright,
            error_y=brighterr,
            error_y_minus=brighterr_minus,
            color="filter",
            range_y=range_y,
            labels={
                f"mjd_{MJD_OFFSET}": f"mjd − {MJD_OFFSET}",
                bright: BRIGHT_LABELS[bright],
                brighterr: BRIGHTERR_LABELS[brighterr],
            }
            | ({} if brighterr_minus is None else {brighterr_minus: BRIGHTERR_LABELS[brighterr_minus]}),
            color_discrete_map=FILTER_COLORS,
            symbol="oid",
            size="mark_size",
            size_max=MARKER_SIZE,
            hover_data={f"mjd_{MJD_OFFSET}": ":.5f", "date": True, brighterr: True},
            custom_data=["mjd", "oid", "fieldid", "rcid", "filter"],
            render_mode=render_mode,
        )
    elif lc_type == "folded":
        figure = px.scatter(
            df,
            x="phase",
            y=bright,
            error_y=brighterr,
            error_y_minus=None,
            color="filter",
            range_y=range_y,
            labels={f"mjd_{MJD_OFFSET}": f"mjd − {MJD_OFFSET}"},
            color_discrete_map=FILTER_COLORS,
            symbol="oid",
            size="mark_size",
            size_max=MARKER_SIZE,
            hover_data={"folded_time": True, f"mjd_{MJD_OFFSET}": ":.5f", "date": True, brighterr: True},
            custom_data=["mjd", "oid", "fieldid", "rcid", "filter"],
            range_x=[0.0, 1.0],
            render_mode=render_mode,
        )
    else:
        raise ValueError(f"{lc_type = } is unknown")
    if name_model and fit_params:
        df_fit = model_fit.get_curve(df, dr, bright, json.loads(fit_params), name_model)
        if not df_fit.empty:
            band_color = {"zr": "red", "zg": "darkgreen", "zi": "black"}
            for band in df["filter"].unique():
                df_fit_b = df_fit[df_fit["band"] == "ztf" + str(band[1:])]
                figure.add_trace(
                    go.Scatter(
                        x=df_fit_b["time"],
                        y=df_fit_b["bright"],
                        mode="lines",
                        line=go.scatter.Line(color=band_color[band]),
                        name=f"{name_model}_{band}",
                    )
                )
    figure.update_traces(
        marker=dict(line=dict(width=0.5, color="black")),
        selector=dict(mode="markers"),
    )
    fw = go.FigureWidget(figure)
    fw.layout.hovermode = "closest"
    fw.layout.xaxis.title.standoff = 0
    fw.layout.yaxis.title.standoff = 0
    fw.layout.legend.orientation = "h"
    fw.layout.legend.xanchor = "left"
    fw.layout.legend.y = -0.1
    fw.layout.plot_bgcolor = "#E8E8E8"
    return fw


def set_figure_link(
    cur_oid, dr, title, different_filter, different_field, min_mjd, max_mjd, lc_type, period, phase0, fmt
):
    if lc_type == "folded" and not period:
        raise PreventUpdate
    if min_mjd is not None and max_mjd is not None and min_mjd >= max_mjd:
        raise PreventUpdate
    other_oids = neighbour_oids(different_filter, different_field)
    data = [("other_oid", oid) for oid in other_oids]
    data.append(("title", title))
    if min_mjd is not None:
        data.append(("min_mjd", min_mjd))
    if max_mjd is not None:
        data.append(("max_mjd", max_mjd))
    data.append(("format", fmt))
    if lc_type == "folded":
        offset = -(phase0 or 0.0) * period
        data.append(("offset", offset))
    query = urlencode(data)
    if lc_type == "full":
        return f"/{dr}/figure/{cur_oid}?{query}"
    elif lc_type == "folded":
        return f"/{dr}/figure/{cur_oid}/folded/{period}?{query}"
    raise ValueError(f"{lc_type = } is unknown")


app.callback(
    Output("figure-png-link", "href"),
    [
        Input("oid", "children"),
        Input("dr", "children"),
        Input("title", "children"),
        Input("different_filter_neighbours", "children"),
        Input("different_field_neighbours", "children"),
        Input("min-mjd", "value"),
        Input("max-mjd", "value"),
        Input("light-curve-type", "value"),
        Input("fold-period", "value"),
        Input("fold-zero-phase", "value"),
    ],
)(partial(set_figure_link, fmt="png"))


app.callback(
    Output("figure-pdf-link", "href"),
    [
        Input("oid", "children"),
        Input("dr", "children"),
        Input("title", "children"),
        Input("different_filter_neighbours", "children"),
        Input("different_field_neighbours", "children"),
        Input("min-mjd", "value"),
        Input("max-mjd", "value"),
        Input("light-curve-type", "value"),
        Input("fold-period", "value"),
        Input("fold-zero-phase", "value"),
    ],
)(partial(set_figure_link, fmt="pdf"))


@app.callback(
    Output("csv-link", "href"),
    [
        Input("oid", "children"),
        Input("dr", "children"),
        Input("different_filter_neighbours", "children"),
        Input("different_field_neighbours", "children"),
        Input("min-mjd", "value"),
        Input("max-mjd", "value"),
    ],
)
def set_csv_link(oid, dr, different_filter, different_field, min_mjd, max_mjd):
    url = f"/{dr}/csv/{oid}"
    query = {}

    if other_oids := neighbour_oids(different_filter, different_field):
        query |= {"other_oid": list(other_oids)}
    if min_mjd is not None:
        query["min_mjd"] = [min_mjd]
    if max_mjd is not None:
        query["max_mjd"] = [max_mjd]

    if len(query) > 0:
        url += "?" + urlencode(query, doseq=True)
    return url


def find_neighbours(radius, center_oid, dr, different):
    if radius is None:
        return html.P("No radius is specified")
    if float(radius) <= 0:
        return html.P("Radius should be positive")
    ra, dec = find_ztf_oid.get_coord(center_oid, dr)
    kwargs = dict(ra=ra, dec=dec, radius_arcsec=radius, dr=dr)
    fltr = find_ztf_oid.get_meta(center_oid, dr)["filter"]
    fieldid = find_ztf_oid.get_meta(center_oid, dr)["fieldid"]
    j = find_ztf_circle.find(**kwargs)
    if different == "filter":
        j = {
            oid: value
            for oid, value in j.items()
            if value["meta"]["filter"] != fltr and value["meta"]["fieldid"] == fieldid
        }
    elif different == "fieldid":
        j = {oid: value for oid, value in j.items() if value["meta"]["fieldid"] != fieldid}
    else:
        raise ValueError(f'Wrong "different" value {different}')
    children = []
    for i, (oid, obj) in enumerate(sorted(j.items(), key=lambda kv: kv[1]["separation"])):
        div = html.Div(
            [html.A(f"{oid}", href=f"./{oid}"), f' ({format_sep(obj["separation"])})'],
            id=f"different-{different}-{oid}",
            style={"display": "inline"},
        )
        if i != 0:
            div.children.insert(0, ", ")
        children.append(div)
    return children


app.callback(
    Output("different_field_neighbours", "children"),
    [Input("different_field_radius", "value")],
    [
        State("oid", "children"),
        State("dr", "children"),
    ],
)(partial(find_neighbours, different="fieldid"))

app.callback(
    Output("different_filter_neighbours", "children"),
    [Input("different_filter_radius", "value")],
    [
        State("oid", "children"),
        State("dr", "children"),
    ],
)(partial(find_neighbours, different="filter"))


app.clientside_callback(
    """
    function(divs) {
        console.log(divs);
        if (divs) {
            let ra = document.getElementById("fits-to-show-ra").innerText;
            let dec = document.getElementById("fits-to-show-dec").innerText;
            let fits = document.getElementById("fits-to-show-cutout-url").innerText;
            console.log(fits);
            JS9.Load(fits, {onload: function(im) {
                JS9.SetPan({ra: ra, dec: dec}, {display: im});
                JS9.AddRegions({shape: 'point', ra: ra, dec: dec}, {display: im});
                if (JS9.GetFlip() === "none") {
                    JS9.SetFlip("y");
                }
            }});
        }
        return '';
    }
    """,
    Output("placeholder", "children"),
    [Input("fits-to-show", "children")],
)


@app.callback(Output("fits-to-show", "children"), [Input("graph", "clickData")], [State("dr", "children")])
def load_fits_for_graph_clicked(data, dr):
    if data is None:
        raise PreventUpdate
    if not (points := data.get("points")):
        raise PreventUpdate
    point = points[0]
    mjd, oid, fieldid, rcid, fltr, *_ = point["customdata"]
    ra, dec = find_ztf_oid.get_coord(oid, dr)
    coord = find_ztf_oid.get_sky_coord(oid, dr)
    date = DateWithFrac.from_hmjd(mjd, coord=coord)
    correct_date(date)
    fits_url = urljoin(ZTF_FITS_PROXY_URL, date.sciimg_path(fieldid=fieldid, rcid=rcid, filter=fltr))
    cutout_query = urlencode(dict(size="449pix", gzip="false", center=f"{ra},{dec}"))
    fits_cutout_url = f"{fits_url}?{cutout_query}"
    js9_url = f'{JS9_URL}?{urlencode(dict(url=fits_url,zoom=10,ra=ra,dec=dec,scale="histeq",flip="y"))}'
    prod_dir_url = urljoin(ZTF_FITS_PROXY_URL, date.products_path)
    return [
        html.Div(ra, id="fits-to-show-ra", style={"display": "none"}),
        html.Div(dec, id="fits-to-show-dec", style={"display": "none"}),
        html.Div(fits_cutout_url, id="fits-to-show-cutout-url", style={"display": "none"}),
        html.A("Open in JS9", href=js9_url, id="fits-to-show-js9-url"),
        " ",
        html.A("Download FITS", href=fits_url, id="fits-to-download-url"),
        " ",
        html.A("Product directory", href=prod_dir_url, id="fits-to-show-dir-url"),
    ]


@app.callback(Output("skybot", "children"), [Input("graph", "clickData")], [State("dr", "children")])
def update_skybot_for_graph_clicked(data, dr):
    if data is None:
        raise PreventUpdate
    if not (points := data.get("points")):
        raise PreventUpdate
    point = points[0]
    mjd, oid, *_ = point["customdata"]
    coord = find_ztf_oid.get_sky_coord(oid, dr)
    observatory_mjd = hmjd_to_earth(mjd, coord)
    try:
        table = SKYBOT_QUERY.find(coord.ra.deg, coord.dec.deg, observatory_mjd, radius_arcsec=15.0)
    except NotFound:
        return html.Div("No minor planets found in 15″")

    return [html.B("Minor planets: ")] + list_join(
        ", ", (f"{row['__name']} ({row['__separation']}, mV={row['V'].to_value('mag'):.1f})" for row in table)
    )


@app.callback(
    Output(dict(type="search-radius", index="astro-colibri"), "value"),
    [Input("astro-colibri-search-radius-degrees", "value")],
)
def convert_astro_colibri_search_radius_to_arcsec(radius_deg):
    return int(np.round(float(radius_deg) * 3600))


def set_table(radius, oid, dr, catalog):
    ra, dec = find_ztf_oid.get_coord(oid, dr)
    if radius is None:
        return html.P("No radius is specified")
    radius = float(radius)
    if radius <= 0:
        return html.P("Radius should be positive")
    query = get_catalog_query(catalog)
    try:
        table = query.find(ra, dec, radius)
    except NotFound:
        return html.P(
            f'No {catalog.replace("-", " ")} objects within {format_sep(radius, 0, 0)} from {ra:.5f}, {dec:.5f}'
        )
    except (CatalogUnavailable, ConnectionError):
        return html.P("Catalog data is temporarily unavailable")
    table = table.copy()
    div = html.Div(
        [
            ddsih.DangerouslySetInnerHTML(html_from_astropy_table(table, query.columns)),
        ],
    )
    return div


def set_tables():
    for catalog in catalog_query_objects():
        app.callback(
            Output(f"{catalog}-table", "children"),
            [Input(dict(type="search-radius", index=catalog), "value")],
            [
                State("oid", "children"),
                State("dr", "children"),
            ],
        )(partial(set_table, catalog=catalog))


set_tables()


@app.callback(
    Output("search-on-vizier", "href"),
    [Input("vizier-radius", "value")],
    [
        State("oid", "children"),
        State("dr", "children"),
    ],
)
def set_vizier_url(radius, oid, dr):
    ra, dec = find_ztf_oid.get_coord(oid, dr)
    if radius is None:
        radius = 0
    return find_vizier.get_search_url(ra, dec, radius)


@app.callback(
    Output("vizier-list", "children"),
    [Input("vizier-button", "n_clicks")],
    [
        State("vizier-radius", "value"),
        State("oid", "children"),
        State("dr", "children"),
    ],
)
def set_vizier_list(n_clicks, radius, oid, dr):
    if n_clicks == 0:
        return ""

    if radius is None:
        return html.P("No radius is specified")

    radius = float(radius)
    ra, dec = find_ztf_oid.get_coord(oid, dr)

    table_list = find_vizier.find(ra, dec, radius)
    if len(table_list) == 0:
        return html.P(f"No vizier catalogs found within {format_sep(radius, 0, 0)} from {ra:.5f}, {dec:.5f}")

    records = []
    lengths = []
    for catalog, table in zip(table_list.keys(), table_list.values()):
        try:
            description = vizier_catalog_details.description(catalog)
        except NotFound:
            description = catalog
        n = len(table)
        n_objects = str(n) if n < find_vizier.row_limit else f"≥{n}"
        n_objects = f" ({n_objects} objects)" if n > LIST_MAXSHOW else ""
        r = sorted(table["_r"])
        if n > LIST_MAXSHOW:
            r = r[: LIST_MAXSHOW - 1]
        sep = ", ".join(f"{x}″" for x in r)
        if n > LIST_MAXSHOW:
            sep += ", …"
        url = find_vizier.get_catalog_url(catalog, ra, dec, radius)
        records.append(f"[{description}]({url}){n_objects}: {sep}")
        lengths.append(len(description) + len(n_objects) + 2 + len(sep))

    ul_column_width = max(lengths) + 2  # for bullet symbol
    div = html.Div(
        [
            html.Ul(
                [html.Li(dcc.Markdown(record)) for record in records],
                style={"columns": f"{ul_column_width}ch", "list-style-type": "none"},
            ),
        ]
    )
    return div


@app.callback(
    Output("features-list", "children"),
    [
        Input("oid", "children"),
        Input("dr", "children"),
        Input("features-api-version", "value"),
        Input("min-mjd", "value"),
        Input("max-mjd", "value"),
    ],
)
def set_features_list(oid, dr, version, min_mjd, max_mjd):
    if min_mjd is not None and max_mjd is not None and min_mjd >= max_mjd:
        raise PreventUpdate
    try:
        features = light_curve_features(oid, dr, version=version, min_mjd=min_mjd, max_mjd=max_mjd)
    except NotFound:
        return "Not available"
    items = [f"**{k}**: {v:.4g}" for k, v in sorted(features.items(), key=lambda item: item[0])]
    column_width = max(map(len, items)) - 2
    div = html.Div(
        html.Ul([html.Li(dcc.Markdown(text)) for text in items], style={"list-style-type": "none"}),
        style={"columns": f"{column_width}ch"},
    )
    return div


@app.callback(
    Output("light-curve-table", "data"),
    [
        Input("oid", "children"),
        Input("dr", "children"),
        Input("min-mjd", "value"),
        Input("max-mjd", "value"),
    ],
)
def set_lc_table(oid, dr, min_mjd, max_mjd):
    if min_mjd is not None and max_mjd is not None and min_mjd >= max_mjd:
        raise PreventUpdate
    return find_ztf_oid.get_lc(oid, dr, min_mjd=min_mjd, max_mjd=max_mjd)

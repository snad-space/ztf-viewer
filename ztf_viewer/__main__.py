#!/usr/bin/env python3

import argparse
import logging
import pathlib
import re
import urllib.parse

from astropy.coordinates import SkyCoord, get_icrs_coordinates
from astropy.coordinates.name_resolve import NameResolveError
from dash import Input, Output, State, dcc, html, no_update
from dash.exceptions import PreventUpdate

from ztf_viewer.akb import akb
from ztf_viewer.app import app
from ztf_viewer.catalogs.conesearch import ANTARES_QUERY, TNS_QUERY
from ztf_viewer.catalogs.snad import SnadCatalogSource
from ztf_viewer.exceptions import CatalogUnavailable, NotFound, UnAuthorized
from ztf_viewer.pages import favicon as _
from ztf_viewer.pages import figure as _
from ztf_viewer.pages import lc_csv as _
from ztf_viewer.pages.akb_table import get_layout as get_anomalies_layout
from ztf_viewer.pages.login import get_layout as get_login_layout
from ztf_viewer.pages.search import get_layout as get_search_layout
from ztf_viewer.pages.tags import get_layout as get_tags_layout
from ztf_viewer.pages.viewer import get_layout as get_viewer_layout
from ztf_viewer.util import DEFAULT_DR, YEAR, available_drs, list_join
from ztf_viewer.version import version_string, version_url

logging.basicConfig(level=logging.INFO)


app.title = "SNAD ZTF viewer"


app.layout = html.Div(
    [
        dcc.Location(id="url", refresh=True),
        html.Div(
            [
                html.H1(
                    [
                        html.A(
                            [
                                html.Img(src="/static/img/logo.svg", alt="logo", id="header-logo"),
                                "SNAD ZTF",
                            ],
                            href="/",
                        ),
                        " ",
                        html.Div(DEFAULT_DR.upper(), id="dr-title", style={"display": "inline-block"}),
                        " object viewer",
                    ],
                ),
                html.Div(id="username", style={"position": "absolute", "top": 0, "right": "1em"}),
                "ZTF DR OID or SNAD name ",
                dcc.Input(
                    id="input-oid",
                    placeholder="633207400004730 or 202",
                    type="text",
                    minLength=3,
                    maxLength=16,
                    n_submit=0,
                ),
                html.Div(
                    DEFAULT_DR,
                    id="data-release",
                    style={"display": "none"},
                ),
                html.Button(
                    "Go",
                    id="button-oid",
                    n_clicks=0,
                ),
            ]
        ),
        html.Div(
            [
                "Coordinates or name ",
                dcc.Input(
                    id="input-coord-or-name",
                    placeholder="00h00m00s +00d00m00s or M57",
                    type="text",
                    minLength=1,
                    maxLength=50,
                    n_submit=0,
                    style={"width": "16.5em"},
                ),
                " radius, arcsec ",
                dcc.Input(
                    value="1",
                    id="input-search-radius",
                    placeholder="1.23",
                    type="number",
                    step="0.1",
                    min="0",
                    max="60",
                    n_submit=0,
                ),
                html.Button(
                    "Go",
                    id="button-coord-or-name",
                    n_clicks=0,
                ),
            ]
        ),
        html.Div(id="page-content"),
        html.Footer(
            [
                f"© {YEAR} ",
                html.A("SИAD", href="//snad.space"),
                f". ",
                *(() if version_string is None else ("Version ", html.A(f"{version_string}", href=version_url), ".")),
                " Developed by Konstantin Malanchev, based on ",
                html.A("the ZTF Caltech data.", href="//ztf.caltech.edu"),
                " See the source code ",
                html.A("on GitHub", href="//github.com/snad-space/ztf-viewer"),
                ".",
                html.Br(),
                "If you use this web-site in your research, please cite ",
                html.A("this paper", href="https://ui.adsabs.harvard.edu/abs/2022arXiv221107605M"),
                " ",
                dcc.Clipboard(
                    content="""@ARTICLE{2022arXiv221107605M,
       author = {{Malanchev}, Konstantin and {Kornilov}, Matwey V. and {Pruzhinskaya}, Maria V. and {Ishida}, Emille E.~O. and {Aleo}, Patrick D. and {Korolev}, Vladimir S. and {Lavrukhina}, Anastasia and {Russeil}, Etienne and {Sreejith}, Sreevarsha and {Volnova}, Alina A. and {Voloshina}, Anastasiya and {Krone-Martins}, Alberto},
        title = "{The SNAD Viewer: Everything You Want to Know about Your Favorite ZTF Object}",
      journal = {arXiv e-prints},
     keywords = {Astrophysics - Instrumentation and Methods for Astrophysics},
         year = 2022,
        month = nov,
          eid = {arXiv:2211.07605},
        pages = {arXiv:2211.07605},
archivePrefix = {arXiv},
       eprint = {2211.07605},
 primaryClass = {astro-ph.IM},
       adsurl = {https://ui.adsabs.harvard.edu/abs/2022arXiv221107605M},
      adsnote = {Provided by the SAO/NASA Astrophysics Data System}
}
""",
                    title="copy BibTeX citation",
                    style={
                        "display": "inline-block",
                    },
                ),
                " as well as all relevant data source papers.",
            ],
            style={
                "margin-top": "5em",
            },
        ),
        html.Div(None, id="webgl-is-available", style={"display": "none"}),
    ],
    id="main-layout",
)


app.clientside_callback(
    """
    function(divs) {
        var canvas = document.createElement("canvas");
        // Get WebGLRenderingContext from canvas element.
        var gl = canvas.getContext("webgl")
          || canvas.getContext("experimental-webgl");
        // Report the result.
        if (gl && gl instanceof WebGLRenderingContext) {
            console.log("WebGL is available");
            return "1";
        } else {
            console.log("WebGL is unavailable");
            return "0";
        }
    }
    """,
    Output("webgl-is-available", "children"),
    [Input("main-layout", "children")],
)


@app.callback(
    Output("data-release", "children"),
    [Input("url", "pathname")],
)
def dr_from_url(url):
    try:
        parts = pathlib.Path(url).parts
    except TypeError:
        return DEFAULT_DR
    if len(parts) < 2:
        return DEFAULT_DR
    if parts[1].lower().startswith("dr"):
        return parts[1]
    return DEFAULT_DR


def dr_switch(current_dr, current_url, switch_dr):
    if switch_dr == current_dr:
        return current_dr.upper()
    if current_dr in current_url:
        switch_url = current_url.replace(current_dr, switch_dr)
    else:
        switch_url = f"/{switch_dr}{current_url}"
    return html.A(switch_dr.upper(), href=switch_url, style={"text-decoration-style": "dashed"})


@app.callback(
    Output("dr-title", "children"),
    [Input("data-release", "children")],
)
def set_dr_title(dr):
    return dr.upper()


@app.callback(
    Output("username", "children"),
    [Input("url", "pathname")],
)
def set_username(_):
    try:
        return akb.username()
    except UnAuthorized:
        return html.A("login", href="/login")


def oid_from_input(s: str):
    s = s.strip()
    if s.isnumeric() and 15 <= len(s) <= 16:
        return s
    if s.isnumeric() or s.upper().startswith("SNAD"):
        try:
            return str(SnadCatalogSource(s).ztf_oid)
        except KeyError:
            pass
    return s


def sky_coord_from_str(s):
    s = s.strip()
    if s.upper().startswith("SNAD"):
        try:
            return SnadCatalogSource(s).coord
        except KeyError:
            raise ValueError(f"ID {s} isn't found in the SNAD catalog")

    try:
        return SkyCoord(s)
    except ValueError:
        pass

    if s.upper().startswith("AT") or s.upper().startswith("SN"):
        s = s.removeprefix("AT").removeprefix("at").removeprefix("SN").removeprefix("sn").strip()
        try:
            return TNS_QUERY.resolve_name(s)
        except (NotFound, CatalogUnavailable):
            pass

    if s.upper().startswith("ZTF"):
        # make cases right
        s = "ZTF" + s.lower().removeprefix("ztf")
        try:
            return ANTARES_QUERY.resolve_name(s)
        except (NotFound, CatalogUnavailable):
            pass

    try:
        return get_icrs_coordinates(s)
    except NameResolveError:
        pass

    raise ValueError(f'Cannot parse given coordinates or a name: "{s}"')


@app.callback(
    Output("url", "pathname"),
    [
        Input("button-oid", "n_clicks"),
        Input("input-oid", "n_submit"),
        Input("button-coord-or-name", "n_clicks"),
        Input("input-coord-or-name", "n_submit"),
        Input("input-search-radius", "n_submit"),
    ],
    [
        State("input-oid", "value"),
        State("input-coord-or-name", "value"),
        State("input-search-radius", "value"),
        State("url", "pathname"),
        State("data-release", "children"),
    ],
)
def go_to_url(
    n_clicks_oid,
    n_submit_oid,
    n_clicks_search,
    n_submit_coord_or_name,
    n_submit_radius,
    oid,
    coord_or_name,
    radius_arcsec,
    current_pathaname,
    dr,
):
    if (n_submit_oid != 0 or n_clicks_oid != 0) and oid is not None:
        oid = oid_from_input(oid)
        return f"/{dr}/view/{oid}"
    if n_clicks_search != 0 or n_submit_coord_or_name != 0 or n_submit_radius != 0:
        coord_or_name = urllib.parse.quote(coord_or_name)
        return f"/{dr}/search/{coord_or_name}/{radius_arcsec}"
    return current_pathaname


@app.callback(
    [
        Output("page-content", "children"),
        Output("input-coord-or-name", "value"),
        Output("input-search-radius", "value"),
    ],
    [Input("url", "pathname")],
)
def app_select_by_url(pathname):
    if not isinstance(pathname, str):
        raise PreventUpdate
    # DR7 is not supported anymore:
    if m := re.search(r"^/dr7((?:/.*)?)$", pathname):
        href = m.group(1) or "/"
        return [
            [
                html.H3(
                    [
                        "DR7 is not supported any more, consider to use ",
                        html.A("the most recent DR instead", href=href),
                    ]
                ),
            ],
            no_update,
            no_update,
        ]
    if m := re.search(r"^/+(?:(dr\d{1,2})/+)?$", pathname):
        dr = m.group(1) or DEFAULT_DR
        other_drs = [other_dr for other_dr in available_drs if other_dr != dr]
        return [
            [
                html.Div(
                    [
                        "For example see the page for ",
                        html.A(f"SNAD101", href=f"/{dr}/view/633207400004730"),
                    ]
                ),
                html.H2("Welcome to SNAD ZTF object viewer!"),
                html.Div(
                    html.Big(
                        [
                            "This is a tool developed by the ",
                            html.A("SИAD team", href="//snad.space"),
                            " in order to enable quick expert investigation of objects within the public ",
                            html.A("Zwicky Transient Facility (ZTF)", href="//ztf.caltech.edu"),
                            " data releases. It was developed as part of the ",
                            html.A("3rd SИAD Workshop", href="//snad.space/2020/"),
                            ", held remotely in July, 2020.",
                            html.Br(),
                            html.Br(),
                            "The viewer allows visualization of raw and folded light curves and metadata, as well as cross-match information with the ",
                            html.A(
                                "the General Catalog of Variable Stars", href="http://www.sai.msu.ru/gcvs/intro.htm"
                            ),
                            ", ",
                            html.A(
                                "the International Variable Stars Index",
                                href="//www.aavso.org/vsx/index.php?view=about.top",
                            ),
                            ", ",
                            html.A("the ATLAS Catalog of Variable Stars", href="//archive.stsci.edu/prepds/atlas-var/"),
                            ", ",
                            html.A("the SDSS DR16 Quasar catalog", href="//www.sdss.org/dr16/algorithms/qso_catalog/"),
                            ", ",
                            html.A("the ZTF Catalog of Periodic Variable Stars", href="//zenodo.org/record/3886372"),
                            ", ",
                            html.A(
                                "The Spitzer/IRAC Candidate YSO Catalog",
                                href="https://vizier.cds.unistra.fr/viz-bin/VizieR?-source=J/ApJS/254/33",
                            ),
                            ", ",
                            html.A("PanStarrs DR2", href="//outerspace.stsci.edu/display/PANSTARRS/"),
                            ", ",
                            html.A("the Transient Name Server", href="//www.wis-tns.org"),
                            ", ",
                            html.A("the Open Astronomy Catalogs", href="//astrocats.space/"),
                            ", ",
                            html.A(
                                "the OGLE III Catalog of Variable Stars", href="http://ogledb.astrouw.edu.pl/~ogle/CVS/"
                            ),
                            ", ",
                            html.A("the Simbad Astronomical Data Base", href="//simbad.u-strasbg.fr/simbad/"),
                            ", ",
                            html.A(
                                "Gaia EDR3 distances (Bailer-Jones+, 2021)",
                                href="//vizier.u-strasbg.fr/viz-bin/VizieR?-source=I/352",
                            ),
                            ", ",
                            html.A("Gaia DR3", href="//www.cosmos.esa.int/web/gaia/dr3"),
                            ", ",
                            html.A("Vizier", href="//vizier.u-strasbg.fr/viz-bin/VizieR"),
                            ".",
                            html.Br(),
                            html.Br(),
                            html.Div(
                                [
                                    "The viewer is also available for ",
                                ]
                                + list_join(", ", (html.A(f"ZTF {dr.upper()}", href=f"/{dr}/") for dr in other_drs)),
                            ),
                            html.Br(),
                            "You can find the Viewer description and implementation details in the paper ",
                            html.A(
                                "“The SNAD Viewer: Everything You Want to Know about Your Favorite ZTF Object”, Malanchev at al. 2022",
                                href="https://ui.adsabs.harvard.edu/abs/2022arXiv221107605M",
                            ),
                            ", BibTeX citation:",
                        ],
                    ),
                    style={"max-width": "1200px"},
                ),
                html.Br(),
                html.Div(
                    [
                        dcc.Markdown(
                            """```latex
@ARTICLE{2022arXiv221107605M,
   author = {{Malanchev}, Konstantin and {Kornilov}, Matwey V. and {Pruzhinskaya}, Maria V. and {Ishida}, Emille E.~O. and {Aleo}, Patrick D. and {Korolev}, Vladimir S. and {Lavrukhina}, Anastasia and {Russeil}, Etienne and {Sreejith}, Sreevarsha and {Volnova}, Alina A. and {Voloshina}, Anastasiya and {Krone-Martins}, Alberto},
    title = "{The SNAD Viewer: Everything You Want to Know about Your Favorite ZTF Object}",
  journal = {arXiv e-prints},
 keywords = {Astrophysics - Instrumentation and Methods for Astrophysics},
     year = 2022,
    month = nov,
      eid = {arXiv:2211.07605},
    pages = {arXiv:2211.07605},
archivePrefix = {arXiv},
   eprint = {2211.07605},
primaryClass = {astro-ph.IM},
   adsurl = {https://ui.adsabs.harvard.edu/abs/2022arXiv221107605M},
  adsnote = {Provided by the SAO/NASA Astrophysics Data System}
}
```""",
                            id="bibtex_citation",
                            style={
                                "overflow": "auto",
                                "background-color": "rgba(34, 17, 76, 0.07)",
                            },
                        ),
                        dcc.Clipboard(
                            target_id="bibtex_citation",
                            style={
                                "position": "absolute",
                                "top": 0,
                                "right": 20,
                                "fontSize": "1.6em",
                            },
                        ),
                    ],
                    style={"width": "50%", "max-width": "800px", "position": "relative"},
                ),
            ],
            no_update,
            no_update,
        ]
    if match := re.search(r"^/+view/+(\d+)", pathname):
        return [
            get_viewer_layout(f"/{DEFAULT_DR}/view/{match.group(1)}"),
            no_update,
            no_update,
        ]
    if re.search(r"^/+dr\d{1,2}/+view/+(\d+)", pathname):
        return [
            get_viewer_layout(pathname),
            no_update,
            no_update,
        ]
    if search_match := re.search(
        r"""^
                                     (?:/+(?P<dr>dr\d{1,2}))?
                                     /+search
                                     /+(?P<coord_or_name>[^/]+)
                                     /+(?P<radius_arcsec>[^/]+)
                                     /*
                                     $""",
        pathname,
        flags=re.VERBOSE,
    ):

        coord_or_name = urllib.parse.unquote(search_match["coord_or_name"])
        try:
            coordinates = sky_coord_from_str(coord_or_name)
        except ValueError:
            return [
                html.Div(
                    [
                        html.H1("404"),
                        html.P(f"Cannot parse coordinate or find an object name {coord_or_name}"),
                    ]
                ),
                coord_or_name,
                no_update,
            ]

        try:
            radius_arcsec = float(search_match["radius_arcsec"])
        except ValueError:
            return [
                html.Div(
                    [
                        html.H1("404"),
                        html.P("Wrong radius format"),
                    ]
                ),
                coord_or_name,
                search_match["radius_arcsec"],
            ]
        dr = search_match.group("dr") or DEFAULT_DR
        return [
            get_search_layout(coordinates, radius_arcsec, dr),
            coord_or_name,
            radius_arcsec,
        ]
    if re.search(r"^/+login/*$", pathname):
        return [
            get_login_layout(pathname),
            no_update,
            no_update,
        ]
    if re.search("^/+(?:(?:anomalies)|(?:akb))/*$", pathname):
        return [
            get_anomalies_layout(pathname),
            no_update,
            no_update,
        ]
    if re.search("^/+tags/*$", pathname):
        return [
            get_tags_layout(pathname),
            no_update,
            no_update,
        ]
    return [
        html.H1("404"),
        no_update,
        no_update,
    ]


def server():
    """Entrypoint for Gunicorn"""
    return app.server


def parse_args(args):
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    return parser.parse_args(args)


if __name__ == "__main__":
    args = parse_args(None)
    app.run_server(host=args.host, debug=True)

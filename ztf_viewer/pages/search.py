from astropy.table import Table
from dash import html

from ztf_viewer.catalogs import find_ztf_circle
from ztf_viewer.exceptions import NotFound
from ztf_viewer.util import dash_table_from_astropy_table

COLUMNS = {
    "oid": "OID",
    "separation": "separation, arcsec",
    "filter": "filter",
    "ngoodobs": 'Number of "good" observations',
    "duration": "Duration, days",
}


def get_layout(coordinates, radius_arcsec, dr):
    ra = coordinates.ra.to_value("deg")
    dec = coordinates.dec.to_value("deg")
    cone_str = f"({ra:.5f} deg, {dec:.5f} deg), r = {radius_arcsec:.1f}″"
    try:
        j = find_ztf_circle.find(ra, dec, radius_arcsec, dr)
    except NotFound:
        return html.Div(
            [
                html.H1("404"),
                f"Nothing inside cone {cone_str}",
            ]
        )
    table = Table(
        [
            dict(oid=oid, separation=obj["separation"], **obj["meta"])
            for oid, obj in sorted(j.items(), key=lambda x: x[1]["separation"])
        ]
    )
    layout = html.Div(
        [
            html.H1(f"Objects inside cone {cone_str}"),
            dash_table_from_astropy_table(
                table,
                COLUMNS,
                cell_renderers={"oid": lambda oid: html.A(oid, href=f"/{dr}/view/{oid}")},
            ),
        ],
    )
    return layout

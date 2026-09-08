from astropy.table import Table
from dash import dcc, html

from ztf_viewer.catalogs import find_ztf_circle
from ztf_viewer.exceptions import NotFound
from ztf_viewer.util import format_sep, html_from_astropy_table

COLUMNS = {
    "oid": "OID",
    "separation": "separation, arcsec",
    "filter": "filter",
    "ngoodobs": 'Number of "good" observations',
    "duration": "Duration, days",
}


async def get_layout(coordinates, radius_arcsec, dr):
    ra = coordinates.ra.to_value("deg")
    dec = coordinates.dec.to_value("deg")
    # Not `:.1f`: the radius field takes three decimal digits, and rounding them off here would
    # report a different cone than the one actually searched.
    cone_str = f"({ra:.5f} deg, {dec:.5f} deg), r = {format_sep(radius_arcsec)}"
    try:
        j = await find_ztf_circle.find(ra, dec, radius_arcsec, dr)
    except NotFound:
        return html.Div(
            [
                html.H1("404"),
                f"Nothing inside cone {cone_str}",
            ]
        )
    table = Table(
        [
            dict(oid=f'<a href="/{dr}/view/{oid}">{oid}</a>', separation=obj["separation"], **obj["meta"])
            for oid, obj in sorted(j.items(), key=lambda x: x[1]["separation"])
        ]
    )
    layout = html.Div(
        [
            html.H1(f"Objects inside cone {cone_str}"),
            dcc.Markdown(
                html_from_astropy_table(table, COLUMNS, html_columns=frozenset({"oid"})),
                dangerously_allow_html=True,
            ),
        ],
    )
    return layout

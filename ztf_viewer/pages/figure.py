from fastapi import Body, Request
from immutabledict import immutabledict

from ztf_viewer.app import app
from ztf_viewer.figure_render import plot_data, plot_folded_data
from ztf_viewer.lc_data.plot_data import get_folded_plot_data, get_plot_data
from ztf_viewer.procpool import run_in_process
from ztf_viewer.util import parse_json_to_immutable
from ztf_viewer.web import binary_response, error_response, query_args

MIMES = {
    "pdf": "application/pdf",
    "png": "image/png",
}


class UnknownFormat(Exception):
    """Raised by `parse_figure_args_helper` when `format` isn't one of `MIMES`."""


@app.server.api_route("/{dr}/figure/{oid}/folded/{period}")
async def response_figure_folded(dr: str, oid: int, period: float, request: Request):
    args = query_args(request)
    try:
        kwargs = parse_figure_args_helper(args)
    except UnknownFormat:
        return error_response("", 404)
    offset = float(args.get("offset", 0.0))
    fmt = kwargs.pop("fmt")
    caption = kwargs.pop("caption")
    title = kwargs.pop("title")

    repeat = args.get("repeat", None)
    if repeat is not None:
        repeat = int(repeat)

    data = await get_folded_plot_data(oid, dr, period=period, offset=offset, **kwargs)
    img = await run_in_process(
        plot_folded_data, oid, data, period=period, repeat=repeat, fmt=fmt, caption=caption, title=title
    )

    return binary_response(img, mimetype=MIMES[fmt], filename=f"{oid}.{fmt}")


@app.server.api_route("/{dr}/figure/{oid}", methods=["GET", "POST"])
async def response_figure(dr: str, oid: int, request: Request, body: bytes = Body(default=b"")):
    args = query_args(request)
    try:
        kwargs = parse_figure_args_helper(args, body)
    except UnknownFormat:
        return error_response("", 404)
    fmt = kwargs.pop("fmt")
    caption = kwargs.pop("caption")
    title = kwargs.pop("title")

    data = await get_plot_data(oid, dr, **kwargs)
    img = await run_in_process(plot_data, oid, data, fmt=fmt, caption=caption, title=title)

    return binary_response(img, mimetype=MIMES[fmt], filename=f"{oid}.{fmt}")


def parse_figure_args_helper(args, data=None):
    fmt = args.get("format", "png")
    other_oids = frozenset(args.getlist("other_oid"))
    title = args.get("title", None)
    min_mjd = args.get("min_mjd", None)
    if min_mjd is not None:
        min_mjd = float(min_mjd)
    max_mjd = args.get("max_mjd", None)
    if max_mjd is not None:
        max_mjd = float(max_mjd)
    caption = args.get("copyright", "yes") != "no"

    if fmt not in MIMES:
        raise UnknownFormat(fmt)

    if data:
        data = parse_json_to_immutable(data)
    else:
        data = immutabledict()

    return {
        "fmt": fmt,
        "other_oids": other_oids,
        "min_mjd": min_mjd,
        "max_mjd": max_mjd,
        "caption": caption,
        "additional_data": data,
        "title": title,
    }

import numpy as np
from fastapi import Body, Request
from immutabledict import immutabledict

from ztf_viewer.app import app
from ztf_viewer.figure_render import BRIGHTNESS, DEFAULT_BRIGHTNESS, plot_data, plot_folded_data
from ztf_viewer.lc_data.plot_data import get_folded_plot_data, get_plot_data
from ztf_viewer.procpool import run_in_process
from ztf_viewer.util import immutabledefaultdict, parse_json_to_immutable
from ztf_viewer.web import binary_response, error_response, query_args

MIMES = {
    "pdf": "application/pdf",
    "png": "image/png",
}


class InvalidFigureArgs(Exception):
    """Raised by `parse_figure_args_helper` when a query argument cannot be used."""


class UnknownFormat(InvalidFigureArgs):
    """Raised by `parse_figure_args_helper` when `format` isn't one of `MIMES`."""


class UnknownBrightness(InvalidFigureArgs):
    """Raised by `parse_figure_args_helper` when `brightness` isn't one of `BRIGHTNESS`."""


def _parse_ref_mags(values, default_factory):
    """Parse repeated `oid:value` query arguments into the mapping `get_plot_data` takes.

    Reference magnitudes are per-OID and editable on the light-curve page, so the difference
    photometry the figure shows is only the one on the page if the link carries them along.
    """
    ref = {}
    for value in values:
        oid, _, mag = value.partition(":")
        try:
            ref[int(oid)] = float(mag)
        except ValueError:
            raise InvalidFigureArgs(value) from None
    return immutabledefaultdict(default_factory, ref)


@app.server.api_route("/{dr}/figure/{oid}/folded/{period}")
async def response_figure_folded(dr: str, oid: int, period: float, request: Request):
    args = query_args(request)
    try:
        kwargs = parse_figure_args_helper(args)
    except InvalidFigureArgs:
        return error_response("", 404)
    offset = float(args.get("offset", 0.0))
    fmt = kwargs.pop("fmt")
    caption = kwargs.pop("caption")
    title = kwargs.pop("title")
    brightness = kwargs.pop("brightness")

    repeat = args.get("repeat", None)
    if repeat is not None:
        repeat = int(repeat)

    data = await get_folded_plot_data(oid, dr, period=period, offset=offset, **kwargs)
    img = await run_in_process(
        plot_folded_data,
        oid,
        data,
        period=period,
        repeat=repeat,
        fmt=fmt,
        caption=caption,
        title=title,
        brightness=brightness,
    )

    return binary_response(img, mimetype=MIMES[fmt], filename=f"{oid}.{fmt}")


@app.server.api_route("/{dr}/figure/{oid}", methods=["GET", "POST"])
async def response_figure(dr: str, oid: int, request: Request, body: bytes = Body(default=b"")):
    args = query_args(request)
    try:
        kwargs = parse_figure_args_helper(args, body)
    except InvalidFigureArgs:
        return error_response("", 404)
    fmt = kwargs.pop("fmt")
    caption = kwargs.pop("caption")
    title = kwargs.pop("title")
    brightness = kwargs.pop("brightness")

    data = await get_plot_data(oid, dr, **kwargs)
    img = await run_in_process(plot_data, oid, data, fmt=fmt, caption=caption, title=title, brightness=brightness)

    return binary_response(img, mimetype=MIMES[fmt], filename=f"{oid}.{fmt}")


def parse_figure_args_helper(args, data=None):
    fmt = args.get("format", "png")
    brightness = args.get("brightness", DEFAULT_BRIGHTNESS)
    try:
        other_oids = frozenset(int(oid) for oid in args.getlist("other_oid"))
    except ValueError as e:
        raise InvalidFigureArgs(str(e)) from None
    ref_mag = _parse_ref_mags(args.getlist("ref_mag"), lambda: np.inf)
    ref_magerr = _parse_ref_mags(args.getlist("ref_magerr"), float)
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
    if brightness not in BRIGHTNESS:
        raise UnknownBrightness(brightness)

    if data:
        data = parse_json_to_immutable(data)
    else:
        data = immutabledict()

    return {
        "fmt": fmt,
        "brightness": brightness,
        "other_oids": other_oids,
        "min_mjd": min_mjd,
        "max_mjd": max_mjd,
        "caption": caption,
        "additional_data": data,
        "ref_mag": ref_mag,
        "ref_magerr": ref_magerr,
        "title": title,
    }

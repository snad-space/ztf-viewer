import datetime
import json
import logging
import math
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from html.parser import HTMLParser
from itertools import chain, count
from typing import Callable

import astropy.table
import numpy as np
from astropy import units
from astropy.coordinates import EarthLocation
from astropy.time import Time
from dash import html
from immutabledict import immutabledict

YEAR = datetime.datetime.now().year


PALOMAR = EarthLocation(lon=-116.863, lat=33.356, height=1706)  # EarthLocation.of_site('Palomar')
# https://www.minorplanetcenter.net/iau/lists/ObsCodes.html
PALOMAR_OBS_CODE = "I41"


DEFAULT_MIN_MAX_MJD = 50000.0, 70000.0


INF = float("inf")
LN10_04 = 0.4 * np.log(10.0)
LGE_25 = 2.5 / np.log(10.0)

ABZPMAG_JY = 8.9

FILTER_COLORS = {
    "g": "#62D03E",
    "r": "#CC3344",
    "i": "#1c1309",
    "g'": "#62D03E",
    "r'": "#CC3344",
    "i'": "#1c1309",
    "zg": "#62D03E",
    "zr": "#CC3344",
    "zi": "#1c1309",
    "ant_g": "#05ffc5",
    "ant_R": "#f08b98",
    "gaia_G": "grey",
    "gaia_BP": "blue",
    "gaia_RP": "red",
    "ps_g": "#a7d984",
    "ps_r": "#e0848f",
    "ps_i": "#694721",
    "ps_z": "#5c5cff",
    "ps_y": "#9370d8",
}
FILTERS_ORDER = defaultdict(lambda: 100) | dict(zip(FILTER_COLORS, count(1)))
FILTERS = tuple(FILTER_COLORS)
ZTF_FILTERS = ("zg", "zr", "zi")


DEFAULT_DR = "dr23"
available_drs = (
    "dr2",
    "dr3",
    "dr4",
    "dr8",
    "dr13",
    "dr17",
    "dr23",
)


def db_coord_to_degrees(coord):
    match = re.search(r"^\((\S+)\s*,\s*(\S+)\)$", coord)
    ra = math.degrees(float(match.group(1)))
    dec = math.degrees(float(match.group(2)))
    return ra, dec


def hms_to_deg(hms: str):
    h, m, s = (float(x) for x in hms.split())
    angle = h * units.hourangle + m * units.arcmin + s * units.arcsec
    deg = angle.to_value(units.deg)
    return deg


class _DashHTMLParser(HTMLParser):
    """Parse a simple HTML string into Dash components.

    Handles <a>, <img>, and wraps unknown tags in html.Span.
    """

    def __init__(self):
        super().__init__()
        self._result = []
        self._stack = []  # list of (tag, attrs_dict, children)

    def handle_starttag(self, tag, attrs):
        self._stack.append((tag, dict(attrs), []))

    def handle_startendtag(self, tag, attrs):
        # Self-closing tags like <img />
        component = self._make_component(tag, dict(attrs), [])
        (self._stack[-1][2] if self._stack else self._result).append(component)

    def handle_endtag(self, tag):
        if not self._stack or self._stack[-1][0] != tag:
            return
        _, attrs, children = self._stack.pop()
        component = self._make_component(tag, attrs, children)
        (self._stack[-1][2] if self._stack else self._result).append(component)

    def handle_data(self, data):
        (self._stack[-1][2] if self._stack else self._result).append(data)

    def _make_component(self, tag, attrs, children):
        kids = children[0] if len(children) == 1 else (children or None)
        if tag == "a":
            return html.A(kids, href=attrs.get("href", "#"), target=attrs.get("target"))
        if tag == "img":
            return html.Img(src=attrs.get("src", ""), width=attrs.get("width"))
        return html.Span(kids)

    def get_result(self):
        if not self._result:
            return ""
        return self._result[0] if len(self._result) == 1 else self._result


def _render_cell(value):
    """Render a cell value: parse HTML strings into Dash components, pass other values through."""
    if isinstance(value, str) and "<" in value:
        parser = _DashHTMLParser()
        parser.feed(value)
        return parser.get_result()
    return value


def dash_table_from_astropy_table(table: astropy.table.Table, columns: dict, cell_renderers: dict = None):
    """Convert an astropy Table to a Dash html.Table component.

    columns: dict mapping column_name -> display_label
    cell_renderers: optional dict mapping column_name -> callable(raw_value) -> Dash component or str.
                    Columns not in cell_renderers are converted to str via to_str(), then rendered
                    with _render_cell (which handles HTML strings via dcc.Markdown).
    """
    if cell_renderers is None:
        cell_renderers = {}
    table = table[list(columns.keys())].copy()
    for column in table.colnames:
        if column not in cell_renderers:
            table[column] = [to_str(x) for x in table[column]]
    header = html.Thead(html.Tr([html.Td(_render_cell(label)) for label in columns.values()]))
    rows = [
        html.Tr([
            html.Td(cell_renderers[col](row[col]) if col in cell_renderers else _render_cell(row[col]))
            for col in columns
        ])
        for row in table
    ]
    return html.Table([header, html.Tbody(rows)], id="simbad-table")


def to_str(s, *, float_decimal_digits=3):
    if isinstance(s, bytes):
        return s.decode()
    if isinstance(s, str):
        return s
    if isinstance(s, np.integer) or isinstance(s, int):
        return str(s)
    if isinstance(s, np.floating) or isinstance(s, float):
        if np.isnan(s):
            return ""
        return f"{s:.{float_decimal_digits}f}"
    if isinstance(s, units.Quantity):
        if s.unit.is_equivalent("cm"):
            for unit in (units.pc, units.kpc, units.Mpc, units.Gpc):
                if 1e-1 < (distance := s.to(unit)).value < 3e3:
                    return f"{distance:.2f}"
            else:
                logging.warning(f"Value {s} is too large or too small")
                return str(s)
    if np.ma.is_masked(s):
        return ""
    if s is None:
        return ""
    raise ValueError(f"Argument should be str, bytes, int, float or unit.Quantity (distance), not {type(s)}")


def format_sep(sep_arcsec: float, float_decimal_digits_small: int = 3, float_decimal_digits_large: int = 1) -> str:
    if sep_arcsec < 0.0:
        raise ValueError(f"Separation {sep_arcsec} < 0")
    if sep_arcsec < 60.0:
        return f"{sep_arcsec:.{float_decimal_digits_small}f}″"
    if sep_arcsec < 3600.0:
        arcmin = int(sep_arcsec // 60.0)
        arcsec = sep_arcsec % 60.0
        return f"{arcmin:d}′{arcsec:02.{float_decimal_digits_large}f}″"
    deg = int(sep_arcsec // 3600.0)
    arcmin = int(sep_arcsec // 60.0 - deg * 60.0)
    arcsec = sep_arcsec % 60.0 % 60.0
    return f"{deg:d}°{arcmin:02d}′{arcsec:02.0f}″"


def anchor_form(url, data, title):
    inputs = "\n".join(f'<input type="hidden" name="{key}" value="{value}">' for key, value in data.items())
    return f"""
        <form method="post" action="{url}" class="inline">
            {inputs}
            <button type="submit" class="link-button">
                {title}
            </button>
        </form>
    """


def min_max_mjd_short(dr):
    if dr == "dr2":
        return 58194.0, 58299.0
    if dr == "dr3":
        return 58194.0, 58483.0
    if dr == "dr4":
        return 58194.0, 58664.0
    if dr == "dr7":
        return 58194.0, 58908.0
    if dr == "dr8":
        return 58194.0, 58972.0
    if dr == "dr13":
        return 58194.0, 59280.0
    if dr == "dr17":
        return 58194.0, 59524.0
    return -INF, INF


def hmjd_to_earth(hmjd, coord):
    t = Time(hmjd, format="mjd")
    return t - t.light_travel_time(coord, kind="heliocentric", location=PALOMAR)


def raise_if(condition, exception):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if condition:
                raise exception
            return f(*args, **kwargs)

        return wrapper

    return decorator


def joiner(value, iterator):
    iterator = iter(iterator)
    try:
        yield next(iterator)
    except StopIteration:
        return
    for item in iterator:
        yield value
        yield item


def list_join(value, iterator):
    return list(joiner(value, iterator))


def _json_hook(d):
    for k, v in d.items():
        if isinstance(v, list):
            d[k] = tuple(v)
    return immutabledict(d)


def parse_json_to_immutable(s):
    return json.loads(s, object_hook=_json_hook)


def flip(items, ncol):
    """https://stackoverflow.com/a/10101532/5437597"""
    return chain(*[items[i::ncol] for i in range(ncol)])


def ccdid_from_rcid(rcid: int) -> int:
    return rcid // 4 + 1


def qid_from_rcid(rcid: int) -> int:
    return rcid % 4 + 1


class immutabledefaultdict(immutabledict):
    dict_cls = defaultdict


def compose_plus_minus_expression(value, lower, upper, **to_str_kwargs):
    return f"""
        <div class="expression">
            {to_str(value, **to_str_kwargs)}
            <span class='supsub'>
              <sup class='superscript'>+{to_str(upper - value, **to_str_kwargs)}</sup>
              <sub class='subscript'>-{to_str(value - lower, **to_str_kwargs)}</sub>
            </span>
            </div>
    """


def timeout(seconds: float, exception=TimeoutError, exception_kwargs=None) -> Callable:
    """A decorator to limit the execution time of a function"""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(func, *args, **kwargs)
                try:
                    return future.result(timeout=seconds)
                except TimeoutError:
                    if exception_kwargs is None:
                        raise exception
                    raise exception(**exception_kwargs)

        return wrapper

    return decorator

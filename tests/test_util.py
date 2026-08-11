from xml.etree import ElementTree as ET

from astropy.table import Table
from markupsafe import Markup

from ztf_viewer.util import html_from_astropy_table


def test_html_from_astropy_table_is_single_commonmark_html_block():
    """The output is rendered via dcc.Markdown(dangerously_allow_html=True), which treats a
    raw HTML block (table/tr/td) as literal text only until the first blank line, and only
    recognizes it as a block at all if it starts with <=3 spaces of indentation. So the whole
    table must come out as one contiguous, unindented block.
    """
    columns = {"name": "Name", "link": "Link"}
    table = Table(rows=[("some name", "some value")], names=["name", "link"])

    html = html_from_astropy_table(table, columns)

    lines = html.splitlines()
    assert lines, "expected non-empty output"
    assert all(line.strip() for line in lines), "output must not contain blank/whitespace-only lines"
    assert all(line == line.strip() for line in lines), "output must not contain leading/trailing whitespace"
    assert lines[0].startswith("<table"), "first line must start the HTML block with no indentation"


def test_plain_cells_and_headers_are_escaped():
    """Most cell/header values are plain scientific text, which may happen to contain
    markdown-special characters (*, _) or HTML/XML-special characters (&, <, >, "). Since
    dcc.Markdown(dangerously_allow_html=True) parses the whole table as one raw HTML block,
    anything not deliberately marked as pre-built HTML (via `html_columns` for cells, or
    markupsafe.Markup() for headers) must be escaped, or it would either corrupt the table
    (unescaped "<"/"&" breaking the JSX parser used at render time) or get reinterpreted as
    markdown (unescaped "*"/"_").
    """
    columns = {"name": "Name & <notes>", "value": "Value"}
    table = Table(rows=[("SN Ia*_pec", "A & B < C")], names=["name", "value"])

    html = html_from_astropy_table(table, columns)

    assert "Name & <notes>" not in html
    assert "Name &amp; &lt;notes&gt;" in html
    assert "A & B < C" not in html
    assert "A &amp; B &lt; C" in html
    assert "SN Ia*_pec" in html  # markdown-special chars are untouched (not markdown syntax, just text)

    # Still well-formed HTML/XML despite the raw "&"/"<" in the source values.
    ET.fromstring(f"<root>{html}</root>")


def test_html_columns_cells_are_not_escaped():
    """Cell values for columns named in `html_columns` are deliberately pre-built HTML
    (e.g. catalog get_link()/anchor_form() output) and must pass through unescaped."""
    columns = {"link": "Link", "plain": "Plain"}
    table = Table(rows=[('<a href="https://example.com/obj/1">obj1</a>', "A & B")], names=["link", "plain"])

    html = html_from_astropy_table(table, columns, html_columns=frozenset({"link"}))

    assert '<a href="https://example.com/obj/1">obj1</a>' in html
    assert "A &amp; B" in html
    ET.fromstring(f"<root>{html}</root>")


def test_markup_headers_are_not_escaped():
    """Column *header* labels bypass astropy's Table/numpy storage (they're a plain Python
    dict, not a table column), so markupsafe.Markup() applied directly to a header value (as
    several catalogs' `columns` dicts do, e.g. gcvs.py/vsx.py) survives correctly."""
    columns = {"type": Markup('<a href="https://example.com/help">Variability type</a>')}
    table = Table(rows=[("RRAB",)], names=["type"])

    html = html_from_astropy_table(table, columns)

    assert '<a href="https://example.com/help">Variability type</a>' in html
    ET.fromstring(f"<root>{html}</root>")

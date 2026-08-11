from astropy.table import Table

from ztf_viewer.util import html_from_astropy_table


def test_html_from_astropy_table_is_single_commonmark_html_block():
    """The output is rendered via dcc.Markdown(dangerously_allow_html=True), which treats a
    raw HTML block (table/tr/td) as literal text only until the first blank line, and only
    recognizes it as a block at all if it starts with <=3 spaces of indentation. So the whole
    table must come out as one contiguous, unindented block, with catalog-generated HTML
    fragments (links, images) preserved byte-for-byte and markdown-special characters in cell
    text left untouched.
    """
    columns = {"name": 'Name <a href="https://example.com/help">?</a>', "link": "Link"}
    table = Table(
        rows=[
            ("SN Ia*_pec", '<a href="https://example.com/obj/1">obj1</a>'),
        ],
        names=["name", "link"],
    )

    html = html_from_astropy_table(table, columns)

    lines = html.splitlines()
    assert lines, "expected non-empty output"
    assert all(line.strip() for line in lines), "output must not contain blank/whitespace-only lines"
    assert all(line == line.strip() for line in lines), "output must not contain leading/trailing whitespace"
    assert lines[0].startswith("<table"), "first line must start the HTML block with no indentation"

    assert 'Name <a href="https://example.com/help">?</a>' in html
    assert '<a href="https://example.com/obj/1">obj1</a>' in html
    assert "SN Ia*_pec" in html

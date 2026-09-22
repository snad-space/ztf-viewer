"""`ztf_viewer.social` describes the page a shared link points at, for crawlers that never run
the page's JavaScript."""

from pathlib import Path

import pytest

import ztf_viewer
from ztf_viewer.social import LOGO_PATH, SITE_DESCRIPTION, social_meta_html, social_meta_tags
from ztf_viewer.util import DEFAULT_DR

_ROOT = "https://ztf.snad.space/"


def _content(pathname, key, url=_ROOT, root=_ROOT):
    tags = social_meta_tags(pathname, url, root)
    contents = [tag["content"] for tag in tags if key in (tag.get("name"), tag.get("property"))]
    assert len(contents) <= 1, f"{key} is set more than once"
    return contents[0] if contents else None


def test_object_page_is_titled_by_its_oid():
    assert "633207400004730" in _content("/view/633207400004730", "og:title")


@pytest.mark.parametrize("pathname", ["/view/633207400004730", "/dr17/view/633207400004730"])
def test_object_page_description_names_the_object(pathname):
    description = _content(pathname, "og:description")

    assert "633207400004730" in description
    assert description == _content(pathname, "twitter:description")


def test_object_page_description_names_its_data_release():
    assert DEFAULT_DR.upper() in _content("/view/633207400004730", "og:description")
    assert "DR17" in _content("/dr17/view/633207400004730", "og:description")


def test_object_page_previews_its_light_curve():
    image = _content("/dr17/view/633207400004730", "og:image")

    assert image == "https://ztf.snad.space/dr17/card/633207400004730.png"
    assert image == _content("/dr17/view/633207400004730", "twitter:image")
    assert _content("/dr17/view/633207400004730", "twitter:card") == "summary_large_image"


def test_object_page_without_a_data_release_previews_the_default_one():
    assert _content("/view/633207400004730", "og:image") == f"{_ROOT}{DEFAULT_DR}/card/633207400004730.png"


def test_image_url_follows_the_host_it_is_served_from():
    root = "http://localhost:8050/"
    assert _content("/view/1", "og:image", root=root).startswith(root)


def test_search_page_describes_the_search():
    description = _content("/dr17/search/M31/10", "og:description")

    assert "M31" in description
    assert "10" in description
    assert "DR17" in description


def test_search_page_description_is_url_decoded():
    assert "00h00m00s +00d00m00s" in _content("/search/00h00m00s%20%2B00d00m00s/1", "og:description")


@pytest.mark.parametrize("pathname", ["/", "/anomalies", "/tags", "/no-such-page"])
def test_page_with_no_light_curve_falls_back_to_the_logo(pathname):
    assert _content(pathname, "og:image") == f"{_ROOT}{LOGO_PATH}"
    assert _content(pathname, "twitter:card") == "summary"
    assert _content(pathname, "og:description") == SITE_DESCRIPTION


def test_the_logo_it_falls_back_to_exists():
    assert (Path(ztf_viewer.__file__).parent / LOGO_PATH).is_file()


def test_url_is_the_one_being_served():
    url = "https://ztf.snad.space/dr17/view/633207400004730?hello=world"
    assert _content("/dr17/view/633207400004730", "og:url", url=url) == url


def test_html_is_meta_tags():
    html = social_meta_html("/view/633207400004730", _ROOT, _ROOT)

    assert '<meta property="og:title" content="633207400004730 — SNAD ZTF' in html
    assert html.count("<meta ") == len(social_meta_tags("/view/633207400004730", _ROOT, _ROOT))


def test_html_escapes_the_page_it_describes():
    html = social_meta_html("/search/%22%3E%3Cscript%3E/1", _ROOT, _ROOT)

    assert "<script>" not in html
    assert "&quot;" in html

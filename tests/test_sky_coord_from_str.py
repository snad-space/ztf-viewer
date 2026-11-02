import asyncio

import pytest

from ztf_viewer import config

config.CACHE_TYPE = "memory"
config.UNAVAILABLE_CATALOGS_CACHE_TYPE = "memory"

import ztf_viewer.__main__ as main_module


@pytest.fixture
def no_name_resolver(monkeypatch):
    """Sesame is hosted by CDS, so a CDS outage must not take coordinate search down with it."""

    def get_icrs_coordinates(name):
        raise AssertionError(f"{name!r} was sent to the name resolver")

    monkeypatch.setattr(main_module, "get_icrs_coordinates", get_icrs_coordinates)


@pytest.mark.parametrize(
    "s,ra,dec",
    [
        ("83.633 22.0145", 83.633, 22.0145),
        ("83.633, 22.0145", 83.633, 22.0145),
        ("83.633,22.0145", 83.633, 22.0145),
        ("05:34:31.94 +22:00:52.2", 83.63308, 22.0145),
        ("05 34 31.94 +22 00 52.2", 83.63308, 22.0145),
        ("05h34m31.94s +22d00m52.2s", 83.63308, 22.0145),
    ],
)
def test_coordinates_are_parsed_without_the_name_resolver(no_name_resolver, s, ra, dec):
    coord = asyncio.run(main_module.sky_coord_from_str(s))
    assert coord.ra.deg == pytest.approx(ra, abs=1e-5)
    assert coord.dec.deg == pytest.approx(dec, abs=1e-5)


def test_name_still_goes_to_the_name_resolver(monkeypatch):
    names = []

    def get_icrs_coordinates(name):
        names.append(name)
        return main_module.SkyCoord(83.633, 22.0145, unit="deg")

    monkeypatch.setattr(main_module, "get_icrs_coordinates", get_icrs_coordinates)
    asyncio.run(main_module.sky_coord_from_str("M1"))
    assert names == ["M1"]

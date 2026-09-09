"""Unit tests for `ztf_viewer.pages.figure` and `ztf_viewer.figure_render`.

`tests/test_golden_http.py`'s figure tests hit the real ZTF DR API and are network-marked, so
they only assert the HTTP surface (status, mimetype, magic bytes) and skip cleanly when the
network is unavailable. These tests cover what that one can't, without any network dependency:

* the renderers against synthetic light curves, for both formats;
* that `ztf_viewer.figure_render` -- the module the process pool re-imports in every spawned
  child -- never builds the Dash app as an import side effect, the way `pages.figure` does;
* that a crashed pool worker surfaces to the HTTP caller as a 500, not a hang, through the real
  route and the real process pool (only `get_plot_data` and the renderer are stubbed).
"""

import shutil
import subprocess
import sys

import pytest

from ztf_viewer import config

config.CACHE_TYPE = "memory"
config.UNAVAILABLE_CATALOGS_CACHE_TYPE = "memory"

import numpy as np

from ztf_viewer.figure_render import BRIGHTNESS, _brightness_arrays, plot_data, plot_folded_data
from ztf_viewer.lc_data.plot_data import plot_data as add_photometry
from ztf_viewer.util import immutabledefaultdict

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_PDF_MAGIC = b"%PDF-"


def _pgf_texsystem():
    import matplotlib

    return matplotlib.rcParams.get("pgf.texsystem", "xelatex")


def _synthetic_lc(n=60):
    filters = ["zg", "zr", "zi"]
    return {
        1: [
            {"mjd": 58000.0 + i, "mag": 18.0 + 0.1 * (i % 5), "magerr": 0.05, "filter": filters[i % 3]}
            for i in range(n)
        ]
    }


def _synthetic_folded_lc(n=60, period=1.5):
    lc = _synthetic_lc(n)
    for obs_list in lc.values():
        for obs in obs_list:
            obs["folded_time"] = obs["mjd"] % period
            obs["phase"] = obs["folded_time"] / period
    return lc


def _photometry_lc(n=60, ref_mag=19.0):
    """A synthetic light curve carrying the fields the light-curve page plots.

    Built through the real `lc_data.plot_data`, so flux, difference flux and difference
    magnitude (infinite where the difference flux is consistent with zero) are the same
    quantities the interactive figure shows.
    """
    lc = _synthetic_lc(n)[1]
    for obs in lc:
        obs["oid"] = 1
    return {
        1: add_photometry(
            lc,
            ref_mag=immutabledefaultdict(lambda: np.inf, {1: ref_mag}),
            ref_magerr=immutabledefaultdict(float, {1: 0.05}),
        )
    }


def test_brightness_arrays_keep_asymmetric_diff_mag_errors():
    lc = _photometry_lc()[1]
    m, err = _brightness_arrays(lc, "diffmag")
    assert m == pytest.approx([obs["diffmag"] for obs in lc])
    # (below the point, above the point): brighter is a smaller magnitude, so the "minus" error
    assert err[0] == pytest.approx([obs["diffmagerr_minus"] for obs in lc])
    assert err[1] == pytest.approx([obs["diffmagerr_plus"] for obs in lc])


@pytest.mark.parametrize("brightness", sorted(BRIGHTNESS))
def test_plot_data_renders_every_brightness(brightness):
    img = plot_data(1, _photometry_lc(), fmt="png", brightness=brightness)
    assert img.startswith(_PNG_MAGIC)


@pytest.mark.parametrize("brightness", sorted(BRIGHTNESS))
def test_plot_folded_data_renders_every_brightness(brightness):
    data = _photometry_lc()
    for obs in data[1]:
        obs["folded_time"] = obs["mjd"] % 1.5
        obs["phase"] = obs["folded_time"] / 1.5
    img = plot_folded_data(1, data, period=1.5, fmt="png", brightness=brightness)
    assert img.startswith(_PNG_MAGIC)


def test_plot_data_renders_all_infinite_difference_magnitude():
    """A reference brighter than every observation leaves no positive difference flux, so every
    difference magnitude is infinite; matplotlib skips such points and the figure still renders."""
    data = _photometry_lc(ref_mag=10.0)
    assert not np.any(np.isfinite([obs["diffmag"] for obs in data[1]]))
    img = plot_data(1, data, fmt="png", brightness="diffmag")
    assert img.startswith(_PNG_MAGIC)


def test_plot_data_renders_png():
    img = plot_data(1, _synthetic_lc(), fmt="png")
    assert img.startswith(_PNG_MAGIC)


def test_plot_data_renders_pdf():
    texsystem = _pgf_texsystem()
    if shutil.which(texsystem) is None:
        pytest.skip(f"LaTeX ({texsystem}) is not available locally; PDF rendering shells out to it")
    img = plot_data(1, _synthetic_lc(), fmt="pdf")
    assert img.startswith(_PDF_MAGIC)


def test_plot_folded_data_renders_png():
    img = plot_folded_data(1, _synthetic_folded_lc(), period=1.5, fmt="png")
    assert img.startswith(_PNG_MAGIC)


def test_figure_render_import_has_no_app_side_effects():
    """Spawn's re-import of a submitted function's module must stay cheap and side-effect-free:
    a fresh interpreter that only imports `figure_render` must never pull in Dash or the app."""
    code = (
        "import sys; import ztf_viewer.figure_render; " "print('dash' in sys.modules, 'ztf_viewer.app' in sys.modules)"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "False False"


def _crash_render(*args, **kwargs):
    import os

    os._exit(1)


async def _fake_get_plot_data(oid, dr, **kwargs):
    return _synthetic_lc()


def test_broken_pool_surfaces_as_500(monkeypatch):
    """A worker killed mid-render must reach the caller as a 500, not a hang or a 200 with a
    truncated body -- exercised through the real HTTP route and the real process pool.

    Uses its own client with ``raise_server_exceptions=False``: the shared `client` fixture's
    default (`True`) is a debug convenience that re-raises into the test instead of returning
    the response a real ASGI server would send, which is exactly the behaviour under test here.
    """
    from fastapi.testclient import TestClient

    import ztf_viewer.pages.figure as figure_module
    from tests.conftest import reset_shared_thread_pool

    monkeypatch.setattr(figure_module, "get_plot_data", _fake_get_plot_data)
    monkeypatch.setattr(figure_module, "plot_data", _crash_render)

    reset_shared_thread_pool()
    import ztf_viewer.__main__ as main_module

    with TestClient(main_module.app.server, raise_server_exceptions=False) as test_client:
        response = test_client.get("/dr24/figure/1")

    assert response.status_code == 500


def _parse(**query):
    """`parse_figure_args_helper` against the same query-argument view the routes get."""
    from starlette.datastructures import QueryParams

    from ztf_viewer.pages.figure import parse_figure_args_helper
    from ztf_viewer.web import QueryArgs

    pairs = [(key, str(value)) for key, values in query.items() for value in values]
    return parse_figure_args_helper(QueryArgs(QueryParams(pairs)))


def test_brightness_defaults_to_magnitude():
    assert _parse()["brightness"] == "mag"


def test_brightness_is_taken_from_the_query():
    assert _parse(brightness=["diffflux"])["brightness"] == "diffflux"


def test_unknown_brightness_is_rejected():
    from ztf_viewer.pages.figure import UnknownBrightness

    with pytest.raises(UnknownBrightness):
        _parse(brightness=["luminosity"])


def test_reference_magnitudes_are_taken_from_the_query():
    """Difference photometry follows the reference magnitudes typed on the light-curve page,
    so the link has to carry them, per OID, for the figure to match the plot."""
    kwargs = _parse(ref_mag=["1:19.5", "2:18.25"], ref_magerr=["1:0.02"])
    assert dict(kwargs["ref_mag"]) == {1: 19.5, 2: 18.25}
    assert dict(kwargs["ref_magerr"]) == {1: 0.02}
    # OIDs without a reference fall back to no reference at all, and to a zero error
    assert kwargs["ref_mag"][3] == np.inf
    assert kwargs["ref_magerr"][3] == 0.0


def test_malformed_reference_magnitude_is_rejected():
    from ztf_viewer.pages.figure import InvalidFigureArgs

    with pytest.raises(InvalidFigureArgs):
        _parse(ref_mag=["1:not-a-magnitude"])


def test_external_light_curves_are_taken_from_the_query():
    """`lc=` puts the other surveys' observations on the downloaded figure, as the page plots
    them, in the shape `get_plot_data` takes."""
    from ztf_viewer.lc_data.external import ADDITIONAL_LC_SEARCH_RADIUS_ARCSEC

    external_data = _parse(lc=["antares", "gaia,panstarrs"])["external_data"]
    assert set(external_data) == {"antares", "gaia", "panstarrs"}
    assert external_data["antares"] == {"radius_arcsec": ADDITIONAL_LC_SEARCH_RADIUS_ARCSEC}


def test_no_external_light_curves_without_the_query_argument():
    assert _parse()["external_data"] == {}


def test_unknown_external_light_curve_is_dropped():
    """A stale bookmark should still render the ZTF light curve rather than 404."""
    assert set(_parse(lc=["antares,bogus"])["external_data"]) == {"antares"}


def test_other_oids_are_parsed_as_integers():
    """`get_plot_data` puts them on every observation, where reference magnitudes are looked
    up by OID, so a string OID would silently miss its reference."""
    assert _parse(other_oid=["2", "3"])["other_oids"] == frozenset({2, 3})


def test_unknown_brightness_is_a_404(monkeypatch):
    from fastapi.testclient import TestClient

    import ztf_viewer.pages.figure as figure_module

    monkeypatch.setattr(figure_module, "get_plot_data", _fake_get_plot_data)

    import ztf_viewer.__main__ as main_module

    with TestClient(main_module.app.server) as test_client:
        assert test_client.get("/dr24/figure/1?brightness=luminosity").status_code == 404

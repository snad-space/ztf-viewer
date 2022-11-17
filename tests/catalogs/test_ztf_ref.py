from pytest import approx


def test_fits_url():
    from ztf_viewer.catalogs.ztf_ref import ztf_ref
    from ztf_viewer.config import ZTF_FITS_PROXY_URL

    oid = 633207400004730
    dr = "dr8"  # any supported
    assert (
        f"{ZTF_FITS_PROXY_URL}/products/ref/000/field000633/zr/ccd07/q4/ztf_000633_zr_c07_q4_refpsfcat.fits"
        == ztf_ref.fits_url(oid, dr)
    )


def test_regression_get():
    from ztf_viewer.catalogs.ztf_ref import ztf_ref

    oid = 633207400004730
    dr = "dr8"  # any supported

    expected = {
        "sourceid": 4730,
        "xpos": 450.532,
        "ypos": 1580.329,
        "ra": 247.4554285,
        "dec": 24.772822,
        "flux": 149.41699,
        "sigflux": 8.380944,
        "mag": -5.436,
        "sigmag": 0.061,
        "snr": 17.83,
        "chi": 1.002,
        "sharp": 0.015,
        "flags": 0,
        "magzp": 26.275,
        "magzp_rms": 0.0257194382,
        "infobits": 0,
    }

    actual = ztf_ref.get(oid, dr)

    assert expected == approx(actual)

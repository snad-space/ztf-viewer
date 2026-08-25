"""Unit tests for `ztf_viewer.csv_render`, the module a pool worker re-imports for `get_csv`.

Split out of `ztf_viewer.pages.lc_csv` so that re-import stays cheap: `lc_csv.py` pulls in the
astroquery-backed catalog clients for its own routes, which costs seconds to import, while this
module only needs pandas.
"""

import subprocess
import sys

import pandas as pd

from ztf_viewer.csv_render import dfs_to_csv


def _df(oid, n=3):
    return pd.DataFrame(
        {
            "oid": oid,
            "filter": ["zg"] * n,
            "mjd": [58000.0 + oid + i for i in range(n)],
            "mag": [18.0] * n,
            "magerr": [0.05] * n,
            "clrcoeff": [0.1] * n,
            "ref": [17.5] * n,
            "ref_err": [0.02] * n,
        }
    )


def test_dfs_to_csv_concatenates_and_sorts_by_mjd():
    csv = dfs_to_csv([_df(2), _df(1)])
    lines = csv.strip().splitlines()
    assert lines[0] == "oid,filter,mjd,mag,magerr,clrcoeff,ref,ref_err"
    mjds = [float(line.split(",")[2]) for line in lines[1:]]
    assert mjds == sorted(mjds)


def test_dfs_to_csv_keeps_only_the_expected_columns():
    df = _df(1)
    df["extra_column"] = "not in the csv"
    csv = dfs_to_csv([df])
    header = csv.strip().splitlines()[0]
    assert "extra_column" not in header


def test_csv_render_import_has_no_catalog_or_app_side_effects():
    """Spawn's re-import of a submitted function's module must stay cheap: a fresh interpreter
    that only imports `csv_render` must never pull in Dash, the app, or astroquery."""
    code = (
        "import sys; import ztf_viewer.csv_render; "
        "print('dash' in sys.modules, 'ztf_viewer.app' in sys.modules, 'astroquery' in sys.modules)"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "False False False"

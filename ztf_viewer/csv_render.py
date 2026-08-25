"""Light-curve CSV assembly, split out so it can run in the process pool.

Kept separate from `ztf_viewer.pages.lc_csv` so a pool worker importing this module doesn't also
pull in the astroquery-backed catalog clients `lc_csv.py` needs for its own routes -- that chain
costs seconds to import, this module only needs pandas.
"""

from io import StringIO

import pandas as pd


def dfs_to_csv(dfs):
    df = pd.concat(dfs, axis="index")
    df.sort_values(by="mjd", inplace=True)
    df = df[["oid", "filter", "mjd", "mag", "magerr", "clrcoeff", "ref", "ref_err"]]

    string_io = StringIO()
    df.to_csv(string_io, index=False)
    return string_io.getvalue()

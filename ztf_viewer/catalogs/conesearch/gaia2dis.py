from astropy import units

from ztf_viewer.catalogs.conesearch._base import _BaseVizierQuery


class Gaia2Dis(_BaseVizierQuery):
    """Gaia DR2 distances from Bailer-Jones et al 2018

    Estimating Distance from Parallaxes. IV. Distances to 1.33 Billion Stars
    in Gaia Data Release 2
    https://ui.adsabs.harvard.edu/abs/2018AJ....156...58B
    """

    id_column = "Source"
    columns = {
        "__link": "Source ID",
        "separation": "Separation, arcsec",
        "rest": "Distance, pc",
        "b_rest": "Lower bound of conf. interval, pc",
        "B_rest": "Upper bound of conf. interval, pc",
    }

    _vizier_columns = ["Source", "rest", "b_rest", "B_rest", "rlen", "ResFlag", "ModFlag"]
    _vizier_catalog = "I/347/gaia2dis"

    def add_distance_column(self, table):
        table["__distance"] = [x * units.pc for x in table["rest"]]

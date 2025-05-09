import logging

import numpy as np
from astropy.time import Time, TimeDelta
from astroquery.gaia import GaiaClass
from requests.exceptions import RequestException

from ztf_viewer.catalogs.conesearch._base import (
    ValueWithIntervalColumn,
    ValueWithUncertaintyColumn,
    _BaseLightCurveQuery,
    _BaseVizierQuery,
)
from ztf_viewer.exceptions import CatalogUnavailable, NotFound
from ztf_viewer.util import LGE_25


class GaiaDr3Query(_BaseVizierQuery, _BaseLightCurveQuery):
    id_column = "Source"
    columns = {
        "__link": "Source ID",
        "separation": "Sep, arcsec",
        "_A0": "A(λ=5477Å), mag",
        "_Teff": "Teff, K",
        "_logg": "lg(g)",
        "_[Fe/H]": "[Fe/H]",
        "_Plx": "parallax, mas",
        "_pmRA": "pm RA, mas/yr",
        "_pmDE": "pm Dec, mas/yr",
        "PQSO": "quasar prob",
        "PGal": "galaxy prob",
        "PSS": "single star prob",
    }

    _prob_class_column = "classifications"
    _prob_class_columns = {"": _prob_class_column}

    _vizier_columns = [
        id_column,
        "Teff",
        "b_Teff",
        "B_Teff",
        "logg",
        "b_logg",
        "B_logg",
        "[Fe/H]",
        "b_[Fe/H]",
        "B_[Fe/H]",
        "A0",
        "b_A0",
        "B_A0",
        "Plx",
        "e_Plx",
        "pmRA",
        "e_pmRA",
        "pmDE",
        "e_pmDE",
        "PQSO",
        "PGal",
        "PSS",
        "EpochPh",
    ]
    _vizier_catalog = "I/355/gaiadr3"

    _value_with_interval_columns = [
        ValueWithIntervalColumn(value="A0"),
        ValueWithIntervalColumn(value="Teff", float_decimal_digits=1),
        ValueWithIntervalColumn(value="logg"),
        ValueWithIntervalColumn(name="_[Fe/H]", value="[Fe/H]", lower="b_[Fe/H]", upper="B_[Fe/H]"),
    ]
    _value_with_uncertainty_columns = [
        ValueWithUncertaintyColumn(value="Plx"),
        ValueWithUncertaintyColumn(value="pmRA"),
        ValueWithUncertaintyColumn(value="pmDE"),
    ]

    # https://www.cosmos.esa.int/web/gaia/edr3-passbands
    AB_ZP = {
        "G": 25.8010446445,
        "BP": 25.3539555559,
        "RP": 25.1039837393,
    }
    AB_ZP_ERR = {
        "G": 0.0027590522,
        "BP": 0.0023065687,
        "RP": 0.0015800349,
    }
    BANDS = ["G", "BP", "RP"]

    def __init__(self, query_name):
        super().__init__(query_name)
        self.gaia = GaiaClass()

    def find_closest(self, ra, dec, radius_arcsec, has_light_curve: bool = False):
        table = self.find(ra, dec, radius_arcsec)
        if has_light_curve:
            table = table[table["EpochPh"] == 1]
            if len(table) == 0:
                raise NotFound
        return table[0]

    def _table_to_light_curve(self, id, table):
        """https://gea.esac.esa.int/archive/documentation/GDR3/Gaia_archive/chap_datamodel/sec_dm_photometry/ssec_dm_epoch_photometry.html"""

        tables = {band: table[~table[f"variability_flag_{band.lower()}_reject"]] for band in self.BANDS}

        source_id = np.full(sum(map(len, tables.values())), id)

        band = np.concatenate([np.full(len(tab), band) for band, tab in tables.items()])

        gaia_time = np.concatenate(
            [tables["G"]["g_transit_time"]] + [tables[band][f"{band.lower()}_obs_time"] for band in ["BP", "RP"]]
        )
        tcb = Time("2010-01-01T00:00:00", scale="tcb") + TimeDelta(gaia_time, format="jd")
        time = Time(tcb, scale="utc").mjd

        ab_zp = np.vectorize(self.AB_ZP.get)(band)
        gaia_flux = np.concatenate(
            [tables["G"]["g_transit_flux"]] + [tables[band][f"{band.lower()}_flux"] for band in ["BP", "RP"]]
        )
        mag = ab_zp - 2.5 * np.log10(gaia_flux)

        ab_zp_err = np.vectorize(self.AB_ZP_ERR.get)(band)
        flux_over_error = np.concatenate(
            [tables["G"]["g_transit_flux_over_error"]]
            + [tables[band][f"{band.lower()}_flux_over_error"] for band in ["BP", "RP"]]
        )
        magerr = np.hypot(LGE_25 / flux_over_error, ab_zp_err)

        keys = ["oid", "mjd", "mag", "magerr", "filter"]
        return [dict(zip(keys, values)) for values in zip(source_id, time, mag, magerr, band)]

    def light_curve(self, id, row=None):
        self._raise_if_unavailable()
        try:
            result = self.gaia.load_data(
                ids=[id],
                data_release="Gaia DR3",
                retrieval_type="EPOCH_PHOTOMETRY",
                data_structure="INDIVIDUAL",
            )
        except RequestException as e:
            logging.warning(str(e))
            raise CatalogUnavailable(catalog=self)

        if len(result) == 0:
            raise NotFound
        assert (
            len(result) == 1
        ), "we asked for a single GAIA DR3 object light curve, how could we have more than one result?"
        tables = next(iter(result.values()))
        assert len(tables) == 1
        table = tables[0].to_table()  # From VOtable to normal astropy table
        table = table[~table["rejected_by_photometry"]]
        if len(table) == 0:
            raise NotFound
        return self._table_to_light_curve(id, table)

    def add_prob_class_columns(self, table):
        table["classifications"] = [{} for _ in range(len(table))]
        for row in table:
            for pretty_name, column_name in [("Quasar", "PQSO"), ("galaxy", "PGal"), ("single star", "PSS")]:
                if (prob := row[column_name]) is None:
                    continue
                row["classifications"][pretty_name] = prob

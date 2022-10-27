import logging
import os
import random
from string import ascii_lowercase
from tempfile import TemporaryDirectory

import numpy as np
from astropy.time import Time
from astroquery.gaia import GaiaClass
from requests.exceptions import RequestException

from ztf_viewer.catalogs.conesearch._base import _BaseVizierQuery, _BaseLightCurveQuery, ValueWithIntervalColumn, ValueWithUncertaintyColumn
from ztf_viewer.exceptions import NotFound, CatalogUnavailable
from ztf_viewer.util import LGE_25


class GaiaDr3Query(_BaseVizierQuery, _BaseLightCurveQuery):
    id_column = 'Source'
    columns = {
        '__link': 'Source ID',
        'separation': 'Sep, arcsec',
        '_A0': 'A(λ=5477Å), mag',
        '_Teff': 'Teff, K',
        '_logg': 'lg(g)',
        '_[Fe/H]': '[Fe/H]',
        '_Plx': 'parallax, mas',
        '_pmRA': 'pm RA, mas/yr',
        '_pmDE': 'pm Dec, mas/yr',
        'PQSO': 'quasar prob',
        'PGal': 'galaxy prob',
        'PSS': 'single star prob',
    }

    _vizier_columns = [id_column,
                       'Teff', 'b_Teff', 'B_Teff',
                       'logg', 'b_logg', 'B_logg',
                       '[Fe/H]', 'b_[Fe/H]', 'B_[Fe/H]',
                       'A0', 'b_A0', 'B_A0',
                       'Plx', 'e_Plx',
                       'pmRA', 'e_pmRA',
                       'pmDE', 'e_pmDE',
                       'PQSO', 'PGal', 'PSS',
                       'EpochPh']
    _vizier_catalog = 'I/355/gaiadr3'

    _value_with_interval_columns = [
        ValueWithIntervalColumn(value='A0'),
        ValueWithIntervalColumn(value='Teff', float_decimal_digits=1),
        ValueWithIntervalColumn(value='logg'),
        ValueWithIntervalColumn(name='_[Fe/H]', value='__Fe_H_', lower='b__Fe_H_', upper='B__Fe_H_'),
    ]
    _value_wirh_uncertanty_columns = [
        ValueWithUncertaintyColumn(value='Plx'),
        ValueWithUncertaintyColumn(value='pmRA'),
        ValueWithUncertaintyColumn(value='pmDE'),
    ]

    # https://www.cosmos.esa.int/web/gaia/edr3-passbands
    AB_ZP = {
        'G': 25.8010446445,
        'BP': 25.3539555559,
        'RP': 25.1039837393,
    }
    AB_ZP_ERR = {
        'G': 0.0027590522,
        'BP': 0.0023065687,
        'RP': 0.0015800349,
    }

    def __init__(self, query_name):
        super().__init__(query_name)
        self.gaia = GaiaClass()

    def find_closest(self, ra, dec, radius_arcsec, has_light_curve: bool = False):
        table = self.find(ra, dec, radius_arcsec)
        if has_light_curve:
            table = table[table['EpochPh'] == 1]
            if len(table) == 0:
                raise NotFound
        return table[0]

    def _table_to_light_curve(self, table):
        """https://gea.esac.esa.int/archive/documentation/GDR3/Gaia_archive/chap_datamodel/sec_dm_photometry/ssec_dm_epoch_photometry.html"""
        table['mjd'] = (Time('2010-01-01T00:00:00') + table['time']).mjd
        table['AB_zp'] = [self.AB_ZP[band] for band in table['band']]
        table['AB_zperr'] = [self.AB_ZP_ERR[band] for band in table['band']]
        table['mag_AB'] = table['AB_zp'] - 2.5 * np.log10(table['flux'])
        table['magerr_AB'] = np.hypot(LGE_25 / table['flux_over_error'], table['AB_zperr'])

        return [
            {
               'oid': row['source_id'],
               'mjd': row['mjd'],
               'mag': row['mag_AB'],
               'magerr': row['magerr_AB'],
               'filter': f"gaia_{row['band']}",
            }
            for row in table
        ]

    def light_curve(self, id, row=None):
        self._raise_if_unavailable()
        # By default, load_data creates temporary file in the current directory with time-based name. It could cause
        # problems in multiprocessing scenario
        with TemporaryDirectory() as output_dir:
            filename = ''.join(random.choices(ascii_lowercase, k=6))
            output_file = os.path.join(output_dir, filename)
            try:
                result = self.gaia.load_data(ids=[id], data_release='Gaia DR3', retrieval_type='EPOCH_PHOTOMETRY',
                                             data_structure='INDIVIDUAL', output_file=output_file)
            except RequestException as e:
                logging.warning(str(e))
                raise CatalogUnavailable(catalog=self)

        if len(result) == 0:
            raise NotFound
        assert len(result) == 1, 'we asked for a single GAIA DR3 object light curve, how could we have more than one result?'
        tables = next(iter(result.values()))
        assert len(tables) == 1
        table = tables[0].to_table()  # From VOtable to normal astropy table
        table = table[~table['rejected_by_photometry']]
        if len(table) == 0:
            raise NotFound
        return self._table_to_light_curve(table)

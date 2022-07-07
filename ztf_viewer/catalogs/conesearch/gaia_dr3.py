import urllib.parse

import numpy as np
from astropy.coordinates import Angle
from astropy.time import Time
from astroquery.gaia import GaiaClass

from ztf_viewer.catalogs.conesearch._base import _BaseVizierQuery, _BaseLightCurveQuery
from ztf_viewer.exceptions import NotFound
from ztf_viewer.util import LGE_25, to_str, compose_plus_minus_expression


class GaiaDr3Query(_BaseVizierQuery, _BaseLightCurveQuery):
    id_column = 'DR3Name'
    columns = {
        '__link': 'Source ID',
        'separation': 'Sep, ″',
        '_A0': 'A(λ=5477Å)',
        '_Teff': 'Teff, K',
        '_logg': 'lg(g)',
        '_[Fe/H]': '[Fe/H]',
        '_Plx': 'parallax, mas',
        '_pmRA': 'pm RA, mas/yr',
        '_pmDE': 'pm Dec, mas/yr',
    }

    _vizier_columns = [id_column,
                       'Teff', 'b_Teff', 'B_Teff',
                       'logg', 'b_logg', 'B_logg',
                       '[Fe/H]', 'b_[Fe/H]', 'B_[Fe/H]',
                       'A0', 'b_A0', 'B_A0',
                       'Plx', 'e_Plx',
                       'pmRA', 'e_pmRA',
                       'pmDE', 'e_pmDE',
                       'EpochPh']
    _vizier_catalog = 'I/355/gaiadr3'

    def add_additional_columns(self, table):
        super().add_additional_columns(table)
        self.add_A0_column(table)
        self.add_Teff_column(table)
        self.add_logg_column(table)
        self.add_FeH_column(table)
        self.add_Plx_column(table)
        self.add_pmRA_column(table)
        self.add_pmDE_column(table)

    def add_A0_column(self, table):
        table['_A0'] = [
            compose_plus_minus_expression(row['A0'], row['b_A0'], row['B_A0'], float_decimal_digits=1)
            if row['A0'] and row['b_A0'] and row['B_A0']
            else ''
            for row in table
        ]

    def add_Teff_column(self, table):
        table['_Teff'] = [
            compose_plus_minus_expression(row['Teff'], row['b_Teff'], row['B_Teff'], float_decimal_digits=1)
            if row['Teff'] and row['b_Teff'] and row['B_Teff']
            else ''
            for row in table
        ]

    def add_logg_column(self, table):
        table['_logg'] = [
            compose_plus_minus_expression(row['logg'], row['b_logg'], row['B_logg'], float_decimal_digits=1)
            if row['logg'] and row['b_logg'] and row['B_logg']
            else ''
            for row in table
        ]

    def add_FeH_column(self, table):
        table['_[Fe/H]'] = [
            compose_plus_minus_expression(row['__Fe_H_'], row['b__Fe_H_'], row['B__Fe_H_'], float_decimal_digits=1)
            if row['__Fe_H_'] and row['b__Fe_H_'] and row['B__Fe_H_']
            else ''
            for row in table
        ]

    def add_Plx_column(self, table):
        table['_Plx'] = [
            f'{to_str(row["Plx"])}±{to_str(row["e_Plx"])}'
            if row['Plx'] and row['e_Plx']
            else ''
            for row in table
        ]

    def add_pmRA_column(self, table):
        table['_pmRA'] = [
            f'{to_str(row["pmRA"])}±{to_str(row["e_pmRA"])}'
            if row['pmRA'] and row['e_pmRA']
            else ''
            for row in table
        ]

    def add_pmDE_column(self, table):
        table['_pmDE'] = [
            f'{to_str(row["pmDE"])}±{to_str(row["e_pmDE"])}'
            if row['pmDE'] and row['e_pmDE']
            else ''
            for row in table
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
        result = self.gaia.load_data(ids=[id], data_release='Gaia DR3', retrieval_type='EPOCH_PHOTOMETRY',
                                   data_structure='INDIVIDUAL')
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

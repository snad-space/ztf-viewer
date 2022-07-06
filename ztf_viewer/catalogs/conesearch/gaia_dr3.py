import urllib.parse

import numpy as np
from astropy.coordinates import Angle
from astropy.time import Time
from astroquery.gaia import GaiaClass

from ztf_viewer.catalogs.conesearch._base import _BaseCatalogQuery, _BaseLightCurveQuery
from ztf_viewer.exceptions import NotFound
from ztf_viewer.util import LGE_25, to_str


class GaiaDr3Query(_BaseCatalogQuery, _BaseLightCurveQuery):
    id_column = 'source_id'
    _table_ra = 'ra'
    _ra_unit = 'deg'
    _table_dec = 'dec'
    columns = {
        '__link': 'Name',
        'source_id': 'ID',
        'separation': 'Separation, arcsec',
        'parallax': 'parallax',
        'parallax_error': 'error',
        'pmra': 'pm RA',
        'pmra_error': 'error',
        'pmdec': 'pm Dec',
        'pmdec_error': 'error',
    }

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

    def _query_region(self, coord, radius):
        radius = Angle(radius)
        job = self.gaia.launch_job(f'''
            SELECT source_id, ra, dec, pmra, pmra_error, pmdec, pmdec_error, parallax, parallax_error,
            has_epoch_photometry, DISTANCE(POINT({coord.ra.deg}, {coord.dec.deg}), POINT(ra, dec)) as separation
                FROM gaiadr3.gaia_source
                WHERE CONTAINS(POINT({coord.ra.deg}, {coord.dec.deg}), CIRCLE(ra, dec, {radius.deg})) = 1
                ORDER by separation
        ''')
        table = job.get_results()
        return table

    def find_closest(self, ra, dec, radius_arcsec, has_light_curve: bool = False):
        table = self.find(ra, dec, radius_arcsec)
        if has_light_curve:
            table = table[table['has_epoch_photometry']]
            if len(table) == 0:
                raise NotFound
        return table[0]

    def get_url(self, id, row=None):
        id = to_str(id)
        id = urllib.parse.quote_plus(id)
        return f'//vizier.u-strasbg.fr/viz-bin/VizieR-6?-out.form=%2bH&-source=I/355/gaiadr3&{self.id_column}={id}'

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

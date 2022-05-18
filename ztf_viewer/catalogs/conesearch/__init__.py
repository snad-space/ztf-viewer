from ._base import _BaseCatalogQuery
from .alerce import AlerceQuery
from .antares import AntaresQuery
from .astrocats import AstrocatsQuery
from .atlas import AtlasQuery
from .fink import FinkQuery
from .gaia2dis import Gaia2Dis
from .gaia_edr3_dis import GaiaEdr3Dis
from .gcvs import GcvsQuery
from .ogle import OgleQuery
from .panstarrs import PanstarrsDr2StackedQuery
from .sdss import SdssQuasarsQuery
from .simbad import SimbadQuery
from .tns import TnsQuery
from .vsx import VsxQuery
from .ztf_periodic import ZtfPeriodicQuery


ALERCE_QUERY = AlerceQuery('Alerce')
ANTARES_QUERY = AntaresQuery('Antares')
ASTROCATS_QUERY = AstrocatsQuery('Astrocats')
FINK_QUERY = FinkQuery('Fink')
ATLAS_QUERY = AtlasQuery('ATLAS')
GAIA2_DIS = Gaia2Dis('Gaia DR2 Distances')
GAIA_EDR3_DIS = GaiaEdr3Dis('Gaia EDR3 Distances')
GCVS_QUERY = GcvsQuery('GCVS')
OGLE_QUERY = OgleQuery('OGLE')
PANSTARRS_DR2_QUERY = PanstarrsDr2StackedQuery('Pan-STARRS DR2 Stacked')
SDSS_QUASARS_QUERY = SdssQuasarsQuery('SDSS DR16 Quasars')
SIMBAD_QUERY = SimbadQuery('Simbad')
TNS_QUERY = TnsQuery('Transient Name Server')
VSX_QUERY = VsxQuery('VSX')
ZTF_PERIODIC_QUERY = ZtfPeriodicQuery('ZTF Periodic')


catalog_query_objects = _BaseCatalogQuery.get_objects


def get_catalog_query(catalog):
    try:
        return _BaseCatalogQuery.get_object(catalog)
    except KeyError as e:
        raise ValueError(f'No catalog query engine for catalog type "{catalog}"') from e

from ._base import _BaseCatalogQuery
from .alerce import AlerceQuery
from .antares import AntaresQuery
from .astrocats import AstrocatsQuery
from .atlas import AtlasQuery
from .colibri import ColibriQuery
from .fink_lsst import FinkLsstQuery
from .fink_ztf import FinkZtfQuery
from .gaia2dis import Gaia2Dis
from .gaia_dr3 import GaiaDr3Query
from .gaia_edr3_dis import GaiaEdr3Dis
from .gcvs import GcvsQuery
from .macho import MachoQuery
from .ogle import OgleQuery
from .otter import OtterQuery
from .panstarrs import PanstarrsDr2StackedQuery
from .sdss import SdssQuasarsQuery
from .simbad import SimbadQuery
from .skymapper import SkyMapperDr4Query
from .spicy import SpicyQuery
from .tess import TessLightCurveQuery
from .tns import TnsQuery
from .vsx import VsxQuery
from .ztf_periodic import ZtfPeriodicQuery
from .zubercal import ZubercalQuery

ALERCE_QUERY = AlerceQuery("Alerce")
ATLAS_QUERY = AtlasQuery("ATLAS")
ANTARES_QUERY = AntaresQuery("Antares")
ASTROCATS_QUERY = AstrocatsQuery("Astrocats")
OTTER_QUERY = OtterQuery("Otter")
COLIBRI_QUERY = ColibriQuery("Astro-COLIBRI")
FINK_LSST_QUERY = FinkLsstQuery("Fink LSST")
FINK_ZTF_QUERY = FinkZtfQuery("Fink ZTF")
GAIA2_DIS = Gaia2Dis("Gaia DR2 Distances")
GAIA_DR3 = GaiaDr3Query("Gaia DR3")
GAIA_EDR3_DIS = GaiaEdr3Dis("Gaia EDR3 Distances")
GCVS_QUERY = GcvsQuery("GCVS")
MACHO_QUERY = MachoQuery("MACHO")
OGLE_QUERY = OgleQuery("OGLE")
PANSTARRS_DR2_QUERY = PanstarrsDr2StackedQuery("Pan-STARRS DR2 Stacked")
SDSS_QUASARS_QUERY = SdssQuasarsQuery("SDSS DR16 Quasars")
SIMBAD_QUERY = SimbadQuery("Simbad")
SKYMAPPER_DR4_QUERY = SkyMapperDr4Query("SkyMapper DR4")
SPICY_QUERY = SpicyQuery("SPICY")
TESS_QUERY = TessLightCurveQuery("TESS")
TNS_QUERY = TnsQuery("Transient Name Server")
VSX_QUERY = VsxQuery("VSX")
ZTF_PERIODIC_QUERY = ZtfPeriodicQuery("ZTF Periodic")
ZUBERCAL_QUERY = ZubercalQuery("Zubercal DR20")


catalog_query_objects = _BaseCatalogQuery.get_objects


def get_catalog_query(catalog):
    try:
        return _BaseCatalogQuery.get_object(catalog)
    except KeyError as e:
        raise ValueError(f'No catalog query engine for catalog type "{catalog}"') from e

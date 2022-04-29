from ztf_viewer.catalogs.conesearch._base import _BaseVizierQuery


class VsxQuery(_BaseVizierQuery):
    id_column = 'OID'
    type_column = 'Type'
    period_column = 'Period'
    columns = {
        '__link': 'Designation',
        'separation': 'Separation, arcsec',
        'Name': 'Name',
        'Period': 'Period, days',
        'Type': '<a href="https://aavso.org/vsx/help/VariableStarTypeDesignationsInVSX.pdf">Variability type</a>',
        'max': 'Maximum mag',
        'n_max': 'Band of max mag',
        'min': 'Minimum mag',
        'n_min': 'Band of min mag',
    }
    _vizier_catalog='B/vsx/vsx'

    def get_url(self, id, row=None):
        return f'//www.aavso.org/vsx/index.php?view=detail.top&oid={id}'

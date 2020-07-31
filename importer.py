from time import sleep

import numpy as np


def import_matplotlib():
    """Matplotlib default parameters"""
    import matplotlib

    matplotlib.use('pgf')
    matplotlib.rcParams['pdf.fonttype'] = 42
    matplotlib.rcParams['ps.fonttype'] = 42
    matplotlib.rcParams['font.family'] = 'serif'
    matplotlib.rcParams['pgf.rcfonts'] = False
    matplotlib.rcParams['pgf.preamble'] = r'''
        \usepackage{hyperref}
        \hypersetup{colorlinks=true, urlcolor=black}
    '''


def import_astropy():
    """Dirty hack to overcome problem of simultaneous cache folder creation for astropy"""
    while True:
        try:
            from astroquery.cds import cds
            from astroquery.simbad import Simbad
            from astroquery.vizier import Vizier
            break
        except FileExistsError:
            sleep(np.random.uniform(0.05, 0.2))


import_matplotlib()
import_astropy()

import os


CACHE_TYPE = os.environ.get('CACHE_TYPE', 'redis')
UNAVAILABLE_CATALOGS_CACHE_TYPE = os.environ.get('UNAVAILABLE_CATALOGS_CACHE_TYPE', 'redis')
REDIS_HOSTNAME = os.environ.get('REDIS_URL', 'redis')
AKB_API_URL = os.environ.get('AKB_API_URL', 'https://akb.ztf.snad.space/')
LC_API_URL = os.environ.get('LC_API_URL', 'https://db.ztf.snad.space')
ZTF_FITS_PROXY_URL = os.environ.get('ZTF_FITS_PROXY_URL', 'https://fits.ztf.snad.space')
FEATURES_API_URL = os.environ.get('FEATURES_API_URL', 'https://features.lc.snad.space')
OGLE_III_API_URL = os.environ.get('OGLE_III_API_URL', 'https://ogle3.snad.space')
ZTF_PERIODIC_API_URL = os.environ.get('ZTF_PERIODIC_API_URL', 'https://periodic.ztf.snad.space')
TNS_API_URL = os.environ.get('TNS_API_URL', 'https://tns.snad.space')
JS9_URL = os.environ.get('JS9_URL', 'https://js9.si.edu/js9/js9.html')
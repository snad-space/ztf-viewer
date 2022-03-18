import os


CACHE_TYPE = os.environ.get('CACHE_TYPE', 'redis')
REDIS_HOSTNAME = os.environ.get('REDIS_URL', 'redis')
AKB_API_URL = os.environ.get('AKB_API_URL', 'https://akb.ztf.snad.space/')
LC_API_URL = os.environ.get('LC_API_URL', 'http://db.ztf.snad.space')
PRODUCTS_URL = os.environ.get('PRODUCTS_URL', 'https://fits.ztf.snad.space')

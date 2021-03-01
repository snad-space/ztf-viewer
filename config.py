import os


CACHE_TYPE = os.environ.get('CACHE_TYPE', 'redis')
REDIS_HOSTNAME = os.environ.get('REDIS_URL', 'redis')
AKB_API_URL = os.environ.get('AKB_API_URL', 'https://akb.ztf.snad.space/')
LC_API_URL = os.environ.get('LC_API_URL', 'http://db.ztf.snad.space')
PRODUCTS_URL = os.environ.get('PRODUCTS_URL', 'http://ztf-web-viewer-proxy')
TNS_API_URL = os.environ.get('TNS_API_URL', 'https://www.wis-tns.org')

TNS_API_KEY = os.environ.get('TNS_API_KEY', None)

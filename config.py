import os


LC_API_URL = os.environ.get('LC_API_URL', 'http://db.ztf.snad.space')
PRODUCTS_URL = os.environ.get('PRODUCTS_URL', 'http://ztf-web-viewer-proxy')
TNS_API_URL = os.environ.get('TNS_API_URL', 'https://wis-tns.weizmann.ac.il')

TNS_API_KEY = os.environ.get('TNS_API_KEY', None)

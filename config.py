import os


CACHE_TYPE = os.environ.get('CACHE_TYPE', 'redis')
REDIS_HOSTNAME = os.environ.get('REDIS_URL', 'redis')
LC_API_URL = os.environ.get('LC_API_URL', 'http://db.ztf.snad.space')
PRODUCTS_URL = os.environ.get('PRODUCTS_URL', 'http://ztf-web-viewer-proxy')
TNS_API_URL = os.environ.get('TNS_API_URL', 'https://wis-tns.weizmann.ac.il')

TNS_API_KEY = os.environ.get('TNS_API_KEY', None)
USER_TOKENS = set(os.environ.get('USER_TOKENS', '').split(':'))


def is_user_token_valid(token):
    return token in USER_TOKENS

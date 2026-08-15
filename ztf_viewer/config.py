import os

CACHE_TYPE = os.environ.get("CACHE_TYPE", "redis")
UNAVAILABLE_CATALOGS_CACHE_TYPE = os.environ.get("UNAVAILABLE_CATALOGS_CACHE_TYPE", "redis")
REDIS_HOSTNAME = os.environ.get("REDIS_URL", "redis")
AKB_API_URL = os.environ.get("AKB_API_URL", "https://akb.ztf.snad.space/")
LC_API_URL = os.environ.get("LC_API_URL", "https://db.ztf.snad.space")
ZTF_FITS_PROXY_URL = os.environ.get("ZTF_FITS_PROXY_URL", "https://fits.ztf.snad.space")
FEATURES_API_URL = os.environ.get("FEATURES_API_URL", "https://features.lc.snad.space")
MODEL_FIT_API_URL = os.environ.get("MODEL_FIT_API_URL", "https://fit.lc.snad.space")
OGLE_III_API_URL = os.environ.get("OGLE_III_API_URL", "https://ogle3.snad.space")
ZTF_PERIODIC_API_URL = os.environ.get("ZTF_PERIODIC_API_URL", "https://periodic.ztf.snad.space")
TNS_API_URL = os.environ.get("TNS_API_URL", "https://tns.snad.space")
JS9_URL = os.environ.get("JS9_URL", "https://www.js9.org/js9.html")
DUSTMAPS_API_URL = os.environ.get("DUSTMAPS_API_URL", "https://dustmaps.snad.space")

# Size of both thread pools the entrypoint installs: asyncio's default executor and anyio's
# sync-route limiter. Caps how many blocking calls the single event loop can have in flight.
THREAD_POOL_SIZE = int(os.environ.get("THREAD_POOL_SIZE", "16"))

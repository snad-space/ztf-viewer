import os

import httpx

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
# sync-route limiter. Caps how many blocking calls the single event loop can have in flight, so
# the process ceiling is twice this number. Sized against fan-out width rather than core count:
# the per-upstream limits below sum to 15, and the pool also carries the CPU-bound offloads
# (FITS parsing, figure rendering, CSV assembly) that have no upstream bucket.
THREAD_POOL_SIZE = int(os.environ.get("THREAD_POOL_SIZE", "32"))

# Per-upstream bounded thread offload for sync-only third-party clients that are not being
# ported to async (astroquery, alerce, antares_client -- see ztf_viewer/offload.py). Each
# upstream gets its own asyncio.Semaphore, so a slow or hanging one cannot fill the shared pool
# above and starve catalogs that have nothing to do with it.
#
# These are politeness limits, not capacity limits: we are one IP address serving every user of
# the site, and none of these are our services. Only CDS publishes numbers -- SIMBAD bans an IP
# for a minute above 10 queries/s and for an hour above 400 in 10s -- so SIMBAD gets 1 and
# everything else gets 2 until an operator has a measured reason to raise it. Note vizier,
# simbad, mocserver and sesame are all CDS, so their budgets add up at the same origin.
#
# A semaphore bounds concurrency, not rate: N in flight against latency L is N/L queries per
# second. SIMBAD at 1 stays inside 10/s for any response slower than 100ms.
UPSTREAM_THREAD_LIMITS = {
    "vizier": int(os.environ.get("UPSTREAM_THREADS_VIZIER", "2")),
    "simbad": int(os.environ.get("UPSTREAM_THREADS_SIMBAD", "1")),
    "mocserver": int(os.environ.get("UPSTREAM_THREADS_MOCSERVER", "2")),
    "skybot": int(os.environ.get("UPSTREAM_THREADS_SKYBOT", "2")),
    "gaia": int(os.environ.get("UPSTREAM_THREADS_GAIA", "2")),
    "sesame": int(os.environ.get("UPSTREAM_THREADS_SESAME", "2")),
    "alerce": int(os.environ.get("UPSTREAM_THREADS_ALERCE", "2")),
    "antares": int(os.environ.get("UPSTREAM_THREADS_ANTARES", "2")),
}

# Shared httpx.AsyncClient tuning (ztf_viewer/http.py). Limits are per client, and one client is
# built per event loop, so these bound a single worker's outbound connections.
HTTP_MAX_CONNECTIONS = int(os.environ.get("HTTP_MAX_CONNECTIONS", "100"))
HTTP_MAX_KEEPALIVE_CONNECTIONS = int(os.environ.get("HTTP_MAX_KEEPALIVE_CONNECTIONS", "20"))
# Connection-level retries only (httpx.AsyncHTTPTransport); never retries a request that got a
# response, even an error one.
HTTP_CONNECT_RETRIES = int(os.environ.get("HTTP_CONNECT_RETRIES", "2"))

# The client-level default is a backstop against a call site that forgets an explicit timeout,
# not a value to design around: upstreams disagree by two orders of magnitude (see the per-API
# budgets below), so passing a per-request `timeout=` is the norm, this is only the floor.
HTTP_DEFAULT_TIMEOUT = httpx.Timeout(30.0)

# Per-API request budgets. Each of the first five mirrors what that call site's `requests` call
# already uses today (`git grep timeout= ztf_viewer`), so the async conversions that follow start
# from current behaviour rather than a guess. The last four have no timeout at all today --
# `requests` then waits forever -- so each value below was chosen deliberately rather than
# inherited from a shared default. Named for the API they serve, not the number, so the value can
# move without a rename. Plain constants, not env vars: these encode a per-upstream behaviour
# decision, not a deployment knob, unlike the pool/backstop settings above.
TIMEOUT_ZTF_DR = httpx.Timeout(60.0)  # catalogs/ztf_dr.py: FindZTFOID.find, FindZTFCircle.find
# The generic SNAD-hosted conesearch endpoint shared by _BaseCatalogApiQuery subclasses,
# including OGLE's own circle-search call (conesearch/_base.py, conesearch/ogle.py).
TIMEOUT_CONESEARCH_API = httpx.Timeout(10.0)
TIMEOUT_OGLE_LIGHT_CURVE = httpx.Timeout(60.0)  # conesearch/ogle.py: third-party light-curve image host
# MAST's PanSTARRS catalog API (conesearch/panstarrs.py): a cone search can take minutes to
# answer once connected, but connecting itself should not -- split connect from read.
TIMEOUT_PANSTARRS = httpx.Timeout(10.0, read=600.0)
TIMEOUT_EXTINCTION = httpx.Timeout(10.0)  # extinction/_base.py

TIMEOUT_FEATURES = httpx.Timeout(60.0)  # lc_features.py: feature extraction over a full light curve
TIMEOUT_MODEL_FIT = httpx.Timeout(120.0)  # model_fit.py: the heaviest per-request compute of the first-party APIs
TIMEOUT_AKB = httpx.Timeout(10.0)  # akb.py: small CRUD-shaped JSON requests
TIMEOUT_ZTF_FITS_PROXY = httpx.Timeout(60.0)  # catalogs/ztf_ref.py, date_with_frac.py: both hit ZTF_FITS_PROXY_URL

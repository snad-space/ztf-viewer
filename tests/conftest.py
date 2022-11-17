def setup_config(item):
    from ztf_viewer import config

    config.CACHE_TYPE = "memory"
    config.UNAVAILABLE_CATALOGS_CACHE_TYPE = "memory"


def setup_cache(item):
    from ztf_viewer import cache

    cache.cache = cache._get_cache()


def pytest_runtest_setup(item):
    setup_config(item)
    setup_cache(item)

def setup_config(item):
    from ztf_viewer import config

    config.CACHE_TYPE = "memory"
    config.UNAVAILABLE_CATALOGS_CACHE_TYPE = "memory"


def setup_cache(item):
    from ztf_viewer import cache

    cache.cache = cache._get_cache()
    # Rebinding `cache.cache` only affects functions decorated *after* this point, and all 19
    # `@cache()` sites were decorated when their module was first imported.  Emptying the
    # backends is what actually gives a test an empty cache.
    cache.clear_memory_caches()


def pytest_runtest_setup(item):
    setup_config(item)
    setup_cache(item)

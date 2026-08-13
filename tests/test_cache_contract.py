"""Contract tests for ``ztf_viewer.cache.cache()``.

Black-box spec through the public ``cache()`` decorator only: no test asserts a literal key
string, only observable hit/miss behavior via call counts on the wrapped function. The only
implementation seam relied on is ``ztf_viewer.cache._get_cache()`` plus the module-level
``CACHE_TYPE`` / ``TTL`` names (also used by ``tests/conftest.py``); the Redis client
constructor is stubbed to point at the ``pytest-redis`` server.

The Redis half needs ``pytest-redis``; on macOS the default temp dir makes the fixture's
unix socket path too long, so run pytest with ``--basetemp=/tmp/pytest``.

Some tests are marked ``FAILS TODAY`` and are expected to fail against today's
implementation — plain failures rather than ``xfail``, so they can't silently rot.
"""

import time

import numpy as np
import pytest
import redis
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.table import Table
from immutabledict import immutabledict

from ztf_viewer.util import immutabledefaultdict

# Long enough that nothing expires mid-test.
LONG_TTL = 3600
# Redis TTLs have a one-second granularity, so this is as short as it gets.
SHORT_TTL = 1


def _build_cache(request, monkeypatch, cache_type, ttl):
    """Build a fresh ``cache()`` decorator on the given backend with the given TTL."""
    from ztf_viewer import cache as cache_module
    from ztf_viewer import config

    monkeypatch.setattr(config, "CACHE_TYPE", cache_type, raising=False)
    monkeypatch.setattr(cache_module, "CACHE_TYPE", cache_type, raising=False)
    monkeypatch.setattr(cache_module, "TTL", ttl, raising=False)

    if cache_type == "redis":
        client = request.getfixturevalue("redisdb")

        def factory(*args, **kwargs):
            """Whatever the implementation builds its client with, it gets the test server."""
            return client

        monkeypatch.setattr(config, "REDIS_HOSTNAME", "localhost", raising=False)
        monkeypatch.setattr(cache_module, "REDIS_HOSTNAME", "localhost", raising=False)
        monkeypatch.setattr(cache_module, "StrictRedis", factory, raising=False)
        monkeypatch.setattr(redis, "StrictRedis", factory)
        monkeypatch.setattr(redis, "Redis", factory)

    return cache_module._get_cache()


@pytest.fixture(params=["memory", "redis"])
def cache_type(request):
    return request.param


@pytest.fixture
def cache(request, monkeypatch, cache_type):
    """A ``cache()`` decorator with a TTL long enough to be irrelevant."""
    return _build_cache(request, monkeypatch, cache_type, LONG_TTL)


@pytest.fixture
def short_ttl_cache(request, monkeypatch, cache_type):
    """A ``cache()`` decorator that expires entries after ``SHORT_TTL`` seconds."""
    return _build_cache(request, monkeypatch, cache_type, SHORT_TTL)


class Counter:
    """A cached callable that records how many times the *body* actually ran."""

    _NO_RESULT = object()

    def __init__(self, cache, result=_NO_RESULT, name="counted"):
        self.calls = 0
        self._result = result

        def counted(*args, **kwargs):
            self.calls += 1
            if self._result is self._NO_RESULT:
                return f"result-{self.calls}"
            return self._result

        # Two distinct @cache() sites are distinct functions with distinct names; make these
        # look like that rather than like two closures sharing one qualname.
        counted.__name__ = name
        counted.__qualname__ = name
        self.func = cache()(counted)

    def __call__(self, *args, **kwargs):
        return self.func(*args, **kwargs)


def assert_hit(counter, *args, **kwargs):
    """Calling with these arguments twice must run the body once."""
    before = counter.calls
    first = counter(*args, **kwargs)
    assert counter.calls == before + 1, "first call should be a miss"
    second = counter(*args, **kwargs)
    assert counter.calls == before + 1, "second call with equal arguments should be a hit"
    return first, second


# --------------------------------------------------------------------------------------------
# Key identity: equal-but-distinct arguments of the awkward types the app really passes
# --------------------------------------------------------------------------------------------


def test_hit_on_plain_arguments(cache):
    counter = Counter(cache)
    assert_hit(counter, 633207400004353, "dr23")


def test_hit_on_frozenset(cache):
    """``other_oids`` in lc_data/plot_data.py:82."""
    counter = Counter(cache)
    counter(frozenset({1, 2, 3}))
    assert counter.calls == 1
    counter(frozenset({3, 2, 1}))
    assert counter.calls == 1, "an equal frozenset built in another order must hit"


def test_hit_on_empty_frozenset(cache):
    counter = Counter(cache)
    assert_hit(counter, frozenset())


def test_hit_on_tuple_of_int(cache):
    """``oids: tuple[int]`` in model_fit.py:89."""
    counter = Counter(cache)
    counter((633207400004353, 633207200004431))
    assert counter.calls == 1
    counter((633207400004353, 633207200004431))
    assert counter.calls == 1


def test_hit_on_immutabledict(cache):
    counter = Counter(cache)
    counter(immutabledict({"radius_arcsec": 1.0}))
    assert counter.calls == 1
    counter(immutabledict({"radius_arcsec": 1.0}))
    assert counter.calls == 1


def test_hit_on_nested_immutabledict(cache):
    """``external_data`` as pages/viewer.py:1658 builds it."""
    counter = Counter(cache)

    def make():
        return immutabledict({"antares": immutabledict({"radius_arcsec": 1.0})})

    counter(make())
    assert counter.calls == 1
    counter(make())
    assert counter.calls == 1


def test_hit_on_immutabledefaultdict(cache):
    """``ref_mag`` / ``ref_magerr`` as pages/viewer.py:901 builds them."""
    counter = Counter(cache)

    def make_ref_mag():
        return immutabledefaultdict(lambda: np.inf, {"zr": 18.5, "zg": 19.25})

    def make_ref_magerr():
        return immutabledefaultdict(float, {"zr": 0.1})

    counter(make_ref_mag(), make_ref_magerr())
    assert counter.calls == 1
    counter(make_ref_mag(), make_ref_magerr())
    assert counter.calls == 1, "equal immutabledefaultdicts built separately must hit"


def test_hit_on_empty_immutabledefaultdict(cache):
    """The common case: no reference magnitudes entered, so the mappings are empty."""
    counter = Counter(cache)
    counter(immutabledefaultdict(lambda: np.inf), immutabledefaultdict(float))
    assert counter.calls == 1
    counter(immutabledefaultdict(lambda: np.inf), immutabledefaultdict(float))
    assert counter.calls == 1


def test_hit_on_full_plot_data_signature(cache):
    """The real ``get_plot_data`` argument set (lc_data/plot_data.py:82), keywords and all."""
    counter = Counter(cache)

    def call():
        return counter(
            633207400004353,
            "dr23",
            other_oids=frozenset({633207200004431}),
            min_mjd=None,
            max_mjd=58000.0,
            external_data=immutabledict({"antares": immutabledict({"radius_arcsec": 1.0})}),
            additional_data=immutabledict(),
            ref_mag=immutabledefaultdict(lambda: np.inf, {"zr": 18.5}),
            ref_magerr=immutabledefaultdict(float, {"zr": 0.1}),
        )

    call()
    assert counter.calls == 1
    call()
    assert counter.calls == 1


def test_hit_on_none_and_float_arguments(cache):
    counter = Counter(cache)
    assert_hit(counter, None, 3.5, "dr23", True)


# --------------------------------------------------------------------------------------------
# Distinctness: different arguments must not produce a false hit
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("first", "second"),
    [
        pytest.param((1,), (2,), id="int"),
        pytest.param(("dr23",), ("dr17",), id="str"),
        pytest.param((1.0,), (1.5,), id="float"),
        pytest.param((None,), ("",), id="none-vs-empty-str"),
        pytest.param((frozenset({1, 2}),), (frozenset({1, 3}),), id="frozenset"),
        pytest.param((frozenset(),), (frozenset({1}),), id="empty-frozenset"),
        pytest.param(((1, 2),), ((2, 1),), id="tuple-order"),
        pytest.param(((1, 2),), ((1, 2, 3),), id="tuple-length"),
        pytest.param(
            (immutabledict({"a": 1}),),
            (immutabledict({"a": 2}),),
            id="immutabledict-value",
        ),
        pytest.param(
            (immutabledict({"a": 1}),),
            (immutabledict({"b": 1}),),
            id="immutabledict-key",
        ),
        pytest.param(
            (immutabledefaultdict(lambda: np.inf, {"zr": 18.5}),),
            (immutabledefaultdict(lambda: np.inf, {"zr": 19.5}),),
            id="immutabledefaultdict-value",
        ),
        pytest.param(
            (immutabledefaultdict(lambda: np.inf),),
            (immutabledefaultdict(lambda: np.inf, {"zr": 18.5}),),
            id="immutabledefaultdict-empty-vs-not",
        ),
        pytest.param((1, 2), (2, 1), id="positional-order"),
        pytest.param((1,), (1, 2), id="arity"),
    ],
)
def test_different_args_do_not_hit(cache, first, second):
    counter = Counter(cache)
    counter(*first)
    assert counter.calls == 1
    counter(*second)
    assert counter.calls == 2, "different arguments must not hit each other's entry"


def test_different_kwarg_values_do_not_hit(cache):
    counter = Counter(cache)
    counter(oid=1, dr="dr23")
    assert counter.calls == 1
    counter(oid=1, dr="dr17")
    assert counter.calls == 2


def test_different_kwarg_names_do_not_hit(request, cache):
    """``f(min_mjd=x)`` and ``f(max_mjd=x)`` are different calls.

    Real shape: ``get_plot_data`` / ``model_fit.fit`` take ``min_mjd`` and ``max_mjd`` keywords
    that carry the same kind of value.
    """
    # BUG (redis): redis_lru's key hashes only kwargs *values*, ignoring the names, so any two
    # keywords carrying an equal value are indistinguishable.
    # FAILS TODAY on redis — fixed by `cache-sync`: redis_lru keys on kwargs values only,
    # ignoring their names, so f(min_mjd=X) and f(max_mjd=X) are one entry.
    counter = Counter(cache)
    counter(min_mjd=58000.0)
    assert counter.calls == 1
    counter(max_mjd=58000.0)
    assert counter.calls == 2


def test_distinct_functions_do_not_collide(request, cache):
    """Two different cached functions called with identical arguments are different entries."""
    # BUG (memory): every decorated function shares one cachetools.TTLCache, and the default
    # cachetools key (`keys.hashkey`) does not include the function, so *all* @cache() sites
    # share one keyspace. Two functions taking the same arguments return each other's values.
    # FAILS TODAY on memory — fixed by `cache-sync`: cachetools.cached keys do not include the
    # function, so every @cache() site shares one keyspace.
    first = Counter(cache, result="first", name="first_function")
    second = Counter(cache, result="second", name="second_function")

    assert first(1, "dr23") == "first"
    assert second(1, "dr23") == "second"
    assert first.calls == 1
    assert second.calls == 1


def test_distinct_methods_of_same_class_do_not_collide(request, cache):
    """Cone-search classes carry several cached methods with the same ``(ra, dec, radius)``."""
    # FAILS TODAY on memory — fixed by `cache-sync`: cachetools.cached keys do not include the
    # function, so every @cache() site shares one keyspace.

    class Query:
        @cache()
        def find(self, ra, dec):
            return "find"

        @cache()
        def find_closest(self, ra, dec):
            return "find_closest"

    query = Query()
    assert query.find(10.0, 20.0) == "find"
    assert query.find_closest(10.0, 20.0) == "find_closest"


def test_same_method_name_on_different_classes_does_not_collide(cache):
    """``find(self, ra, dec, radius_arcsec)`` exists on every cone-search catalog class."""

    def make_class(name, result):
        class Query:
            @cache()
            def find(self, ra, dec):
                return result

        Query.__name__ = Query.__qualname__ = name
        return Query

    simbad = make_class("SimbadQuery", "simbad")()
    ned = make_class("NedQuery", "ned")()

    assert simbad.find(10.0, 20.0) == "simbad"
    assert ned.find(10.0, 20.0) == "ned"


def test_method_hits_on_same_instance(cache):
    """The 16 method ``@cache()`` sites are all called on long-lived singletons."""

    class Query:
        def __init__(self):
            self.calls = 0

        @cache()
        def find(self, ra, dec, radius_arcsec):
            self.calls += 1
            return self.calls

    query = Query()
    assert query.find(10.0, 20.0, 1.0) == 1
    assert query.find(10.0, 20.0, 1.0) == 1
    assert query.calls == 1
    assert query.find(10.0, 20.0, 2.0) == 2


# FAILS TODAY on both backends — resolved by `cache-core`, which keys on the CLASS.
# A decision, not a defect: today the key depends on the identity of `self`, so entries are
# unreachable from any other process and are lost on restart. Keying on the class would be wrong
# for an instance carrying state, so `cache-core` audits the sites and adds a `__cache_key__()`
# opt-out for the one class that needs it.
def test_method_key_is_independent_of_instance_identity(cache):
    seen = []

    class Query:
        @cache()
        def find(self, ra, dec):
            seen.append((ra, dec))
            return "queried"

    assert Query().find(10.0, 20.0) == "queried"
    assert Query().find(10.0, 20.0) == "queried"
    assert len(seen) == 1, "an equivalent instance of the same class should reuse the entry"


# --------------------------------------------------------------------------------------------
# Value fidelity: what comes back out must be what went in (Redis round-trips through pickle)
# --------------------------------------------------------------------------------------------


def make_table():
    table = Table(
        {
            "ra": [10.0, 11.0, 12.0],
            "dec": [-5.0, -6.0, -7.0],
            "mag": np.ma.MaskedArray([18.5, 19.0, 20.0], mask=[False, True, False]),
            "name": ["a", "b", "c"],
        },
        masked=True,
    )
    table["ra"].unit = u.deg
    table["dec"].unit = u.deg
    table["mag"].unit = u.mag
    table["mag"].description = "PSF magnitude"
    table.meta["catalog"] = "test"
    return table


def assert_tables_equal(actual, expected):
    assert isinstance(actual, Table)
    assert actual.colnames == expected.colnames
    assert actual.meta == expected.meta
    for name in expected.colnames:
        assert actual[name].unit == expected[name].unit, f"unit lost for {name}"
        assert actual[name].description == expected[name].description
        expected_mask = getattr(expected[name], "mask", None)
        if expected_mask is not None:
            np.testing.assert_array_equal(np.asarray(actual[name].mask), np.asarray(expected_mask))
            np.testing.assert_array_equal(
                np.asarray(actual[name][~expected_mask]), np.asarray(expected[name][~expected_mask])
            )
        else:
            np.testing.assert_array_equal(np.asarray(actual[name]), np.asarray(expected[name]))


def test_table_with_units_and_masked_columns_round_trips(cache):
    counter = Counter(cache, result=make_table())
    first, second = assert_hit(counter, 10.0, 20.0, 1.0)
    assert_tables_equal(first, make_table())
    assert_tables_equal(second, make_table())


def test_table_row_round_trips(cache):
    """``VizierCatalogDetails._query_cds`` (catalogs/vizier.py:15) caches ``table[0]``."""
    table = make_table()
    counter = Counter(cache, result=table[0])
    _, second = assert_hit(counter, "II/246")
    assert second["name"] == table[0]["name"]
    assert second["ra"] == table[0]["ra"]


def test_skycoord_round_trips(cache):
    """``resolve_name`` (catalogs/conesearch/_base.py:275) returns a SkyCoord."""
    coord = SkyCoord(ra=123.456 * u.deg, dec=-12.345 * u.deg, frame="icrs")
    counter = Counter(cache, result=coord)
    _, second = assert_hit(counter, "SN 2020xyz")
    assert isinstance(second, SkyCoord)
    assert second.frame.name == "icrs"
    assert second.ra.deg == pytest.approx(coord.ra.deg)
    assert second.dec.deg == pytest.approx(coord.dec.deg)
    assert second.separation(coord).arcsec == pytest.approx(0.0, abs=1e-9)


def test_dict_round_trips(cache):
    value = {"oid": 633207400004353, "meta": {"filter": "zr", "mjd": [58000.0, 58001.5]}, "ok": True}
    counter = Counter(cache, result=value)
    _, second = assert_hit(counter, 1)
    assert second == value


def test_list_of_dicts_round_trips(cache):
    """Light curves are cached as lists of plain dicts (lc_data)."""
    value = [{"mjd": 58000.0, "mag": 18.5, "magerr": 0.1}, {"mjd": 58001.0, "mag": 18.6, "magerr": 0.2}]
    counter = Counter(cache, result=value)
    _, second = assert_hit(counter, 1, "dr23")
    assert second == value


def test_list_of_str_round_trips(cache):
    """``lc_features.versions`` (lc_features.py:18) caches ``List[str]``."""
    counter = Counter(cache, result=["latest", "v1"])
    _, second = assert_hit(counter)
    assert second == ["latest", "v1"]


def test_numpy_array_round_trips(cache):
    value = np.arange(10, dtype=np.float64)
    counter = Counter(cache, result=value)
    _, second = assert_hit(counter, 1)
    np.testing.assert_array_equal(second, value)


def test_hashable_value_holding_unhashable_parts_round_trips(request, cache):
    """Any picklable value must survive; the cache must not inspect it for hashability."""
    # BUG (redis): redis_lru does `value in self.exclude_values` on anything the Hashable ABC
    # accepts, so a tuple holding a dict raises TypeError instead of being cached.
    # FAILS TODAY on redis — fixed by `cache-sync`: RedisLRU.set hashes the value against its
    # exclude set, raising TypeError instead of caching.
    value = ({"oid": 1}, {"oid": 2})
    counter = Counter(cache, result=value)
    _, second = assert_hit(counter, 1)
    assert second == value


def test_unhashable_argument_does_not_raise(request, cache):
    """A cache is transparent: a legal call must not become a TypeError because of it."""
    # BUG (memory): cachetools' key is a tuple of the arguments, so an unhashable argument
    # raises TypeError out of the wrapper. Redis silently bypasses the cache instead. The
    # rewrite may key such arguments properly or bypass them, but must not raise.
    # FAILS TODAY on memory — fixed by `cache-sync`: cachetools hashes the argument tuple, so an
    # unhashable argument raises out of the wrapper.
    counter = Counter(cache)
    assert counter([1, 2, 3]) == "result-1"


def test_immutabledict_value_round_trips(cache):
    """``parse_json_to_immutable`` (util.py:256) results travel through cached call chains."""
    value = immutabledict({"a": (1, 2), "b": immutabledict({"c": 3})})
    counter = Counter(cache, result=value)
    _, second = assert_hit(counter, 1)
    assert second == value
    assert isinstance(second, immutabledict)


# --------------------------------------------------------------------------------------------
# TTL
# --------------------------------------------------------------------------------------------


def test_entry_survives_until_ttl(short_ttl_cache):
    counter = Counter(short_ttl_cache)
    counter(1)
    counter(1)
    assert counter.calls == 1


def test_entry_expires_after_ttl(short_ttl_cache):
    counter = Counter(short_ttl_cache)
    counter(1)
    assert counter.calls == 1
    time.sleep(SHORT_TTL + 1.0)
    counter(1)
    assert counter.calls == 2, "entry must be recomputed once the TTL has passed"


def test_ttl_expiry_is_per_entry(short_ttl_cache):
    counter = Counter(short_ttl_cache)
    counter(1)
    time.sleep(SHORT_TTL + 1.0)
    counter(2)
    assert counter.calls == 2
    counter(2)
    assert counter.calls == 2, "the fresh entry must still be a hit"

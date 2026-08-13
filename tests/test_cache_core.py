"""Unit tests for the backend-independent cache core.

``tests/test_cache_contract.py`` is the black-box spec for the ``@cache()`` decorator and says
nothing about key format; this file tests the key-building functions directly, above all that
a key is a deterministic function of the call rather than of ``hash()``.
"""

import os
import pickle
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from immutabledict import immutabledict

from ztf_viewer.cache.core import (
    KEY_PREFIX,
    UncacheableArgument,
    UncacheableValue,
    cache_key,
    cache_key_for_call,
    decode_value,
    encode_value,
    function_id,
    self_class,
)
from ztf_viewer.util import immutabledefaultdict


def some_function(*args, **kwargs):
    return None


def another_function(*args, **kwargs):
    return None


def key(*args, **kwargs):
    """The key of ``some_function(*args, **kwargs)``."""
    return cache_key(some_function, args, kwargs)


# ------------------------------------------------------------------------------------------
# Function identity
# ------------------------------------------------------------------------------------------


def test_function_id_is_module_and_qualname():
    assert function_id(some_function) == "tests.test_cache_core.some_function"

    class Holder:
        def method(self):
            pass

    expected = "tests.test_cache_core.test_function_id_is_module_and_qualname.<locals>.Holder.method"
    assert function_id(Holder.method) == expected


def test_key_contains_the_function_id():
    assert key(1).startswith(f"{KEY_PREFIX}:")
    assert "tests.test_cache_core.some_function" in key(1)


def test_distinct_functions_get_distinct_keys():
    """The function is part of the key on every backend."""
    assert cache_key(some_function, (1, "dr23")) != cache_key(another_function, (1, "dr23"))


# ------------------------------------------------------------------------------------------
# Determinism — the property that makes a Redis cache actually persistent
# ------------------------------------------------------------------------------------------


_SUBPROCESS_SOURCE = """
from ztf_viewer.cache.core import cache_key

def target(*args, **kwargs):
    pass

print(cache_key(target, ("dr23", frozenset({"a", "b"}), (1, 2)), {"min_mjd": 58000.0}))
"""


def _key_in_subprocess(hash_seed):
    env = dict(os.environ, PYTHONHASHSEED=hash_seed)
    repo_root = Path(__file__).resolve().parent.parent
    out = subprocess.run(
        [sys.executable, "-c", _SUBPROCESS_SOURCE],
        env=env,
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def test_key_is_identical_in_another_process_with_another_hash_seed():
    """``hash()`` of a str/frozenset is salted per interpreter, so keys must not use it.

    This is what makes cross-worker and cross-restart Redis hits possible at all.
    """
    first = _key_in_subprocess("0")
    second = _key_in_subprocess("12345")
    assert first
    assert first == second


def test_key_is_a_deterministic_function_of_the_arguments():
    assert key(1, "dr23", x=None) == key(1, "dr23", x=None)


# ------------------------------------------------------------------------------------------
# Argument encoding: what must collide and what must not
# ------------------------------------------------------------------------------------------


def test_kwarg_names_are_part_of_the_key():
    assert key(min_mjd=58000.0) != key(max_mjd=58000.0)


def test_kwarg_order_is_not_part_of_the_key():
    assert key(a=1, b=2) == key(b=2, a=1)


def test_positional_order_is_part_of_the_key():
    assert key(1, 2) != key(2, 1)


def test_arity_is_part_of_the_key():
    assert key(1) != key(1, 2)
    assert key(1, 2) != key(1, 2, None)


def test_positional_and_keyword_are_distinguished():
    assert key(1) != key(a=1)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ((1,), (1.0,)),
        ((1,), ("1",)),
        ((None,), ("",)),
        ((None,), (False,)),
        ((True,), (1,)),
        (((1, 2),), ([1, 2],)),
        (((1, 2),), (frozenset({1, 2}),)),
        ((immutabledict({"a": 1}),), ({"a": 1},)),
        ((immutabledict({"a": 1}),), (immutabledefaultdict(float, {"a": 1}),)),
        (("a", "bc"), ("ab", "c")),
        ((("a",), ("b", "c")), (("a", "b"), ("c",))),
        # Container boundaries must not be flattened away.
        ((1, [2, 3]), ([1, 2], 3)),
    ],
)
def test_different_arguments_get_different_keys(first, second):
    assert key(*first) != key(*second)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ((frozenset({1, 2, 3}),), (frozenset({3, 2, 1}),)),
        ((frozenset({1, "a", None}),), (frozenset({None, "a", 1}),)),
        ((immutabledict({"a": 1, "b": 2}),), (immutabledict({"b": 2, "a": 1}),)),
        (
            (immutabledict({"antares": immutabledict({"radius_arcsec": 1.0})}),),
            (immutabledict({"antares": immutabledict({"radius_arcsec": 1.0})}),),
        ),
        ((immutabledefaultdict(float, {"zr": 0.1}),), (immutabledefaultdict(float, {"zr": 0.1}),)),
        # The default factory is a fresh lambda every time, so it must not reach the key.
        ((immutabledefaultdict(lambda: np.inf),), (immutabledefaultdict(lambda: np.inf),)),
        (("dr23", [1, {"a": frozenset({"g", "r"})}]), ("dr23", [1, {"a": frozenset({"r", "g"})}])),
    ],
)
def test_equal_arguments_get_equal_keys(first, second):
    """Separately built but equal arguments must reach the same entry."""
    assert key(*first) == key(*second)


def test_immutabledefaultdict_missing_key_lookup_does_not_change_the_key():
    """It caches ``__hash__`` but mutates the underlying dict on a missing-key lookup.

    Keying on content means the key follows the content, so a mapping that has been probed no
    longer keys as the pristine one built by the next callback.  Assert the direction that
    matters: the key is taken before the call, and a freshly built equal mapping keys the same.
    """
    pristine = immutabledefaultdict(float, {"zr": 0.1})
    probed = immutabledefaultdict(float, {"zr": 0.1})
    before = key(probed)
    assert probed["zg"] == 0.0  # inserts "zg" into the underlying defaultdict
    assert before == key(pristine)
    assert before != key(probed)


def test_unhashable_arguments_are_keyed_rather_than_rejected():
    """Neither backend may raise, and content is better than a bypass."""
    assert key([1, 2, 3]) == key([1, 2, 3])
    assert key([1, 2, 3]) != key([1, 2])
    assert key({"a": [1]}) == key({"a": [1]})


def test_arbitrary_picklable_objects_are_keyed_by_content():
    coord = complex(1, 2)
    assert key(coord) == key(complex(1, 2))
    assert key(coord) != key(complex(1, 3))


def test_unencodable_argument_raises_uncacheable_argument():
    with pytest.raises(UncacheableArgument):
        key(lambda: None)


def test_self_referential_argument_raises_uncacheable_argument():
    loop = [1]
    loop.append(loop)
    with pytest.raises(UncacheableArgument):
        key(loop)


# ------------------------------------------------------------------------------------------
# The ``__cache_key__`` opt-out
# ------------------------------------------------------------------------------------------


class Described:
    """An object that says what about it can change a cached result."""

    def __init__(self, name, session):
        self.name = name
        self.session = session

    def __cache_key__(self):
        return self.name


def test_cache_key_protocol_replaces_the_object_content():
    assert key(Described("simbad", object())) == key(Described("simbad", object()))
    assert key(Described("simbad", object())) != key(Described("ned", object()))


def test_cache_key_protocol_does_not_collide_with_its_own_return_value():
    assert key(Described("simbad", object())) != key("simbad")


# ------------------------------------------------------------------------------------------
# ``self``
# ------------------------------------------------------------------------------------------


class Recorder:
    """Stands in for a catalog-query singleton: state that cannot change a result."""

    def __init__(self, session):
        self.session = session

    def find(self, ra, dec):
        pass

    @staticmethod
    def helper(name):
        pass


class OtherRecorder(Recorder):
    pass


def test_self_class_detects_a_method_call():
    instance = Recorder(session=object())
    assert self_class(Recorder.find, Recorder.find, (instance, 10.0, 20.0)) is Recorder


def test_self_class_detects_the_concrete_subclass():
    instance = OtherRecorder(session=object())
    assert self_class(Recorder.find, Recorder.find, (instance, 10.0, 20.0)) is OtherRecorder


def test_self_class_ignores_a_plain_function():
    assert self_class(some_function, some_function, (1, 2)) is None
    assert self_class(some_function, some_function, ()) is None


def test_self_class_ignores_a_staticmethod():
    """``VizierCatalogDetails._query_cds`` is ``@staticmethod`` over ``@cache()``.

    Its first argument is a catalog id, not ``self``; keying it as ``self`` would collapse every
    catalog id onto one entry.
    """
    raw = Recorder.__dict__["helper"].__func__
    assert self_class(raw, raw, ("II/246",)) is None


def test_method_key_ignores_instance_identity_but_not_the_class():
    """Cached methods key on the class."""
    first = Recorder(session=object())
    second = Recorder(session=object())
    other = OtherRecorder(session=object())

    def key_of(instance):
        return cache_key_for_call(Recorder.find, Recorder.find, (instance, 10.0, 20.0))

    assert key_of(first) == key_of(second)
    assert key_of(first) != key_of(other)


def test_method_key_still_separates_arguments_and_methods():
    instance = Recorder(session=object())

    def key_of(func, *args):
        return cache_key_for_call(func, func, (instance,) + args)

    assert key_of(Recorder.find, 10.0, 20.0) != key_of(Recorder.find, 10.0, 21.0)
    assert key_of(Recorder.find, 10.0, 20.0) != key_of(Recorder.__init__, 10.0, 20.0)


class NamedRecorder:
    """A class whose instances are *not* interchangeable, and which says so."""

    def __init__(self, name):
        self.name = name

    def __cache_key__(self):
        return self.name

    def find(self, ra, dec):
        pass


def test_cache_key_protocol_separates_instances_of_one_class():
    def key_of(instance):
        return cache_key_for_call(NamedRecorder.find, NamedRecorder.find, (instance, 10.0, 20.0))

    assert key_of(NamedRecorder("simbad")) == key_of(NamedRecorder("simbad"))
    assert key_of(NamedRecorder("simbad")) != key_of(NamedRecorder("ned"))


# ------------------------------------------------------------------------------------------
# Value codec
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        None,
        0,
        "",
        ["latest", "v1"],
        {"oid": 1, "meta": {"filter": "zr"}},
        ({"oid": 1}, {"oid": 2}),
        immutabledict({"a": (1, 2), "b": immutabledict({"c": 3})}),
    ],
)
def test_value_round_trips(value):
    assert decode_value(encode_value(value)) == value


def test_numpy_value_round_trips():
    value = np.arange(10, dtype=np.float64)
    np.testing.assert_array_equal(decode_value(encode_value(value)), value)


def test_encoded_value_is_bytes_at_the_pinned_protocol():
    blob = encode_value({"a": 1})
    assert isinstance(blob, bytes)
    assert pickle.loads(blob) == {"a": 1}


def test_unserializable_value_raises_uncacheable_value():
    with pytest.raises(UncacheableValue):
        encode_value(lambda: None)

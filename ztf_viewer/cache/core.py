"""Backend-independent core of the cache: key derivation and value codec.

Pure functions only — nothing here talks to Redis, to ``cachetools``, or to the
``@cache()`` decorator.  ``ztf_viewer.cache`` builds the decorators on top of this.

A key is a deterministic function of the call rather than of ``hash()``.  Python
randomizes the hash of ``str``/``bytes``/``frozenset`` per interpreter and derives a plain
object's hash from ``id()``, so hash-based keys cannot be looked up by another process or
after a restart — which quietly turns a persistent Redis cache into a per-boot one.

Arguments are therefore normalized before being pickled: sets and mappings, whose iteration
order follows the salted hashes, are replaced by their items sorted by pickled bytes
(``sorted()`` itself is not usable — a set may hold mutually incomparable items).  An object
may describe itself instead by defining ``__cache_key__()``, returning a small hashable
description of whatever can change the result of a cached call.

Equal calls may still key differently — a numpy scalar does not key as the equal Python
number, and ``dict`` insertion order and pickle back-references leak into the key — which
costs a recompute but never returns a wrong entry.

``module.qualname`` is part of every key, on every backend, so two ``@cache()`` sites can
never read each other's entries.

``self`` is deliberately encoded by neither content nor identity — see ``encode_self``.
"""

import functools
import pickle
from collections.abc import Mapping, Set
from hashlib import blake2b
from inspect import getattr_static
from operator import itemgetter

__all__ = [
    "KEY_PREFIX",
    "KEY_SCHEME_VERSION",
    "UncacheableArgument",
    "UncacheableValue",
    "cache_key",
    "cache_key_for_call",
    "decode_value",
    "encode_arguments",
    "encode_value",
    "function_id",
    "self_class",
]

# Namespace for every key this module produces, so Redis keys are attributable.
KEY_PREFIX = "ztf-viewer"

# Bump whenever the encoding changes; old entries then become unreachable rather than being
# decoded under the wrong assumptions.
KEY_SCHEME_VERSION = "v1"

# Pinned rather than HIGHEST_PROTOCOL so that a Python upgrade does not write entries the
# still-running old workers cannot read.
PICKLE_PROTOCOL = 5

DIGEST_SIZE = 20


class UncacheableArgument(Exception):
    """An argument cannot be encoded into a cache key.

    The caller (the decorator) is expected to bypass the cache and call the function, never to
    let this reach application code: a cache must not turn a legal call into an error.
    """


class UncacheableValue(Exception):
    """A returned value cannot be serialized, so it cannot be stored."""


# ------------------------------------------------------------------------------------------
# Argument encoding
# ------------------------------------------------------------------------------------------


# Tags keeping a normalized container from colliding with a plain tuple of the same content.
# The NUL prefix cannot appear in a type name.
_MAPPING = "\0mapping"
_SET = "\0set"
_SEQUENCE = "\0sequence"
_CACHE_KEY = "\0cache_key"
_CLASS = "\0class"


def _dumps(obj) -> bytes:
    return pickle.dumps(obj, protocol=PICKLE_PROTOCOL)


def _normalize(obj):
    """Rewrite an argument into a structure whose pickling does not depend on ``hash()``.

    Only the containers whose iteration order is hash-dependent are rewritten; everything else
    is left for ``pickle`` to encode.
    """
    cls = type(obj)

    # Opt-in protocol: an object that knows what about it matters describes itself.
    to_cache_key = getattr(cls, "__cache_key__", None)
    if to_cache_key is not None:
        return (_CACHE_KEY, cls.__module__, cls.__qualname__, _normalize(to_cache_key(obj)))

    if isinstance(obj, (str, bytes, bytearray)):
        return obj
    if isinstance(obj, Mapping):
        items = [(_dumps(_normalize(k)), _normalize(v)) for k, v in obj.items()]
        return (_MAPPING, cls.__module__, cls.__qualname__, sorted(items, key=itemgetter(0)))
    if isinstance(obj, (Set, frozenset, set)):
        return (_SET, cls.__module__, cls.__qualname__, sorted(_dumps(_normalize(item)) for item in obj))
    if isinstance(obj, (list, tuple)):
        return (_SEQUENCE, cls.__module__, cls.__qualname__, [_normalize(item) for item in obj])
    return obj


def encode_self(instance):
    """Normalize the ``self`` argument of a cached method.

    **Decision: key on the class, not on the instance.**
    Every cached method in this app lives on a module-level singleton whose per-instance state
    is API sessions, client objects and timeout decorators — none of which change the result of
    a call.  Keying on ``id(self)`` (which is what both backends do today, directly or through
    ``hash()``) makes every method entry private to one process and lost on restart.

    A class whose instances are *not* interchangeable opts out by defining ``__cache_key__``,
    which is then encoded instead; ``_BaseCatalogQuery`` does exactly that, since its instances
    are constructed with a per-catalog name.
    """
    cls = type(instance)
    if getattr(cls, "__cache_key__", None) is not None:
        return _normalize(instance)
    return (_CLASS, cls.__module__, cls.__qualname__)


def encode_arguments(args=(), kwargs=None, *, method_class: type | None = None) -> bytes:
    """Encode a call's arguments into a byte string that is equal iff the calls are equal.

    ``method_class`` is the class of ``args[0]`` when this call is a bound-method call; it makes
    the first argument encode as ``self`` (see ``encode_self``) rather than by content.

    Raises ``UncacheableArgument`` if some argument cannot be encoded.
    """
    kwargs = {} if kwargs is None else kwargs
    try:
        this = None
        if method_class is not None:
            this = encode_self(args[0])
            args = args[1:]
        # Kwargs are sorted by name, and the *name* is part of the encoding: `f(min_mjd=x)` and
        # `f(max_mjd=x)` are different calls.
        keywords = [(name, _normalize(value)) for name, value in sorted(kwargs.items())]
        return _dumps((this, _normalize(tuple(args)), keywords))
    except RecursionError as e:  # only reachable for self-referential arguments
        raise UncacheableArgument("argument structure is too deeply nested") from e
    except Exception as e:  # pickle raises a wide and undocumented set of exceptions
        raise UncacheableArgument(f"cannot encode an argument: {e}") from e


# ------------------------------------------------------------------------------------------
# Keys
# ------------------------------------------------------------------------------------------


def function_id(func) -> str:
    """``module.qualname`` — the identity of a ``@cache()`` site.

    Raises ``TypeError`` for anything it cannot identify that way.
    """
    if isinstance(func, functools.partial):
        raise TypeError(
            f"cache() cannot key {func!r}: a functools.partial's bound arguments are invisible "
            "to key derivation, so two partials of the same function would share one cache "
            "entry. Decorate the underlying function instead and pass those arguments at the "
            "call site."
        )
    module = getattr(func, "__module__", None)
    name = getattr(func, "__qualname__", None)
    if name is None or not hasattr(func, "__name__"):
        raise TypeError(
            f"cache() cannot key {func!r}: the key is derived from module.qualname, which "
            "requires both __name__ and __qualname__, and this callable is missing one."
        )
    return f"{module}.{name}"


def self_class(func, wrapper, args) -> type | None:
    """The class to key ``self`` on, or ``None`` if this is not a bound-method call.

    Whether ``args[0]`` is ``self`` cannot be decided when the decorator runs — inside a class
    body a method is an ordinary function.  It is decided per call instead, by asking whether
    looking the function's name up on the type of the first argument finds this very wrapper.
    ``getattr_static`` is used so that no descriptor or property runs during the lookup, which
    also means a ``@staticmethod`` (whose first argument is not ``self``) does not match: the
    class dict holds a ``staticmethod`` object, not the wrapper.
    """
    if not args:
        return None
    name = getattr(func, "__name__", None)
    if name is None:
        return None
    cls = type(args[0])
    try:
        found = getattr_static(cls, name, None)
    except Exception:  # noqa: BLE001 - exotic metaclasses, pragma: no cover
        return None
    if found is wrapper or found is func:
        return cls
    return None


def cache_key(func, args=(), kwargs=None, *, method_class: type | None = None) -> str:
    """The cache key for calling ``func`` with ``args``/``kwargs``.

    Raises ``UncacheableArgument`` if the arguments cannot be encoded.
    """
    name = function_id(func)
    encoded = encode_arguments(args, kwargs, method_class=method_class)
    digest = blake2b(encoded, digest_size=DIGEST_SIZE, person=b"ztf-viewer-cache").hexdigest()
    return f"{KEY_PREFIX}:{KEY_SCHEME_VERSION}:{name}:{digest}"


def cache_key_for_call(func, wrapper, args=(), kwargs=None) -> str:
    """``cache_key`` with the ``self``/not-``self`` decision made for this call."""
    return cache_key(func, args, kwargs, method_class=self_class(func, wrapper, args))


# ------------------------------------------------------------------------------------------
# Value codec
# ------------------------------------------------------------------------------------------


def encode_value(value) -> bytes:
    """Serialize a cached value.  Raises ``UncacheableValue`` if it cannot be pickled."""
    try:
        return pickle.dumps(value, protocol=PICKLE_PROTOCOL)
    except Exception as e:  # pickle raises a wide and undocumented set of exceptions
        raise UncacheableValue(f"cannot serialize a value of type {type(value).__name__}: {e}") from e


def decode_value(data: bytes):
    """Deserialize a stored value."""
    return pickle.loads(data)

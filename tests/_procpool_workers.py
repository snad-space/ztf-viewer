"""Module-level worker functions for `tests/test_procpool.py`.

Kept in their own module, not inline in the test file, because spawn (macOS default) re-imports
the target module by name in the child process: a function defined inside a test body cannot be
pickled and shipped across that boundary.
"""

import os


def get_pid() -> int:
    return os.getpid()


def raise_value_error() -> None:
    raise ValueError("boom from child")


def die_hard() -> None:
    os._exit(1)

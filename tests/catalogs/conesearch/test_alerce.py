"""Tests for AlerceQuery — covers the fix for issue #574.

ALeRCE sometimes returns non-PEP-440 classifier_version values (e.g. 'beta').
The fix makes __parse_classifier_version fall back to Version('0.0.0') instead
of raising packaging.version.InvalidVersion.
"""

import packaging.version
import pytest


def _parse(s):
    from ztf_viewer.catalogs.conesearch.alerce import AlerceQuery

    return AlerceQuery._AlerceQuery__parse_classifier_version(s)


def _agg(versions):
    from ztf_viewer.catalogs.conesearch.alerce import AlerceQuery

    return AlerceQuery._AlerceQuery__aggregate_max_classifier_version(versions)


@pytest.mark.parametrize(
    "version_string, expected",
    [
        # Normal case: well-formed version suffix
        ("stamp_classifier_1.0.4", packaging.version.Version("1.0.4")),
        ("lc_classifier_2.1.0", packaging.version.Version("2.1.0")),
        # Non-PEP-440 suffix (issue #574): must not raise, returns 0.0.0
        ("lc_classifier_beta", packaging.version.Version("0.0.0")),
        ("some_classifier_dev", packaging.version.Version("0.0.0")),
        # No underscore: treated as unknown, returns 0.0.0
        ("beta", packaging.version.Version("0.0.0")),
        ("1.0.4", packaging.version.Version("0.0.0")),
    ],
)
def test_parse_classifier_version(version_string, expected):
    assert _parse(version_string) == expected


def test_aggregate_max_prefers_higher_version():
    """__aggregate_max_classifier_version picks the numerically highest version."""
    versions = ["stamp_classifier_1.0.4", "stamp_classifier_1.0.2", "stamp_classifier_beta"]
    assert _agg(versions) == "stamp_classifier_1.0.4"


def test_aggregate_max_all_invalid():
    """When all versions are non-PEP-440, any element is returned (all map to 0.0.0)."""
    versions = ["classifier_beta", "classifier_alpha"]
    # Should not raise; result is one of the elements
    result = _agg(versions)
    assert result in versions

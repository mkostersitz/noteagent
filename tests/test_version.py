"""Tests for version reporting."""

from noteagent import __version__, get_version


def test_get_version_matches_package_version():
    assert get_version() == __version__
    assert get_version() == "0.1.6"

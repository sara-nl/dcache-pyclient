"""Tests for ada.utils module."""

from __future__ import annotations

import subprocess
from importlib.metadata import PackageNotFoundError
from unittest.mock import patch

import pytest

from ada.utils import (
    encode_path,
    get_version,
    normalize_path,
    parse_lifetime,
    to_json,
)
from ada.exceptions import AdaValidationError


class TestEncodePath:
    def test_simple_path(self):
        # Slashes are encoded (matching Bash jq @uri behavior)
        assert encode_path("/pnfs/data/test") == "%2Fpnfs%2Fdata%2Ftest"

    def test_path_with_spaces(self):
        result = encode_path("/pnfs/data/my file.txt")
        assert "%20" in result
        assert result == "%2Fpnfs%2Fdata%2Fmy%20file.txt"

    def test_path_with_special_chars(self):
        result = encode_path("/pnfs/data/file#1")
        assert "%23" in result

    def test_encodes_slashes(self):
        # All characters including / are encoded (single URL path segment)
        result = encode_path("/a/b/c/d")
        assert result == "%2Fa%2Fb%2Fc%2Fd"


class TestParseLifetime:
    def test_days(self):
        assert parse_lifetime("7D") == (7, "D")

    def test_hours(self):
        assert parse_lifetime("24H") == (24, "H")

    def test_minutes(self):
        assert parse_lifetime("30M") == (30, "M")

    def test_seconds(self):
        assert parse_lifetime("600S") == (600, "S")

    def test_lowercase(self):
        assert parse_lifetime("7d") == (7, "D")

    def test_invalid_unit(self):
        with pytest.raises(AdaValidationError, match="Invalid lifetime unit"):
            parse_lifetime("7X")

    def test_invalid_value(self):
        with pytest.raises(AdaValidationError, match="Invalid lifetime value"):
            parse_lifetime("abcD")

    def test_empty(self):
        with pytest.raises(AdaValidationError, match="cannot be empty"):
            parse_lifetime("")

    def test_zero(self):
        with pytest.raises(AdaValidationError, match="positive"):
            parse_lifetime("0D")


class TestToJson:
    def test_json_input(self):
        result = to_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_key_value_input(self):
        result = to_json("key1=value1\nkey2=value2")
        assert result == {"key1": "value1", "key2": "value2"}

    def test_comma_separated(self):
        result = to_json("key1=val1,key2=val2")
        assert result == {"key1": "val1", "key2": "val2"}

    def test_quoted_values(self):
        result = to_json("key='value'")
        assert result == {"key": "value"}

    def test_invalid_input(self):
        with pytest.raises(AdaValidationError, match="Cannot parse"):
            to_json("completely invalid input without delimiters")


class TestNormalizePath:
    def test_trailing_slash(self):
        assert normalize_path("/pnfs/data/") == "/pnfs/data"

    def test_double_slash(self):
        assert normalize_path("/pnfs//data") == "/pnfs/data"

    def test_root_preserved(self):
        assert normalize_path("/") == "/"

    def test_whitespace(self):
        assert normalize_path("  /pnfs/data  ") == "/pnfs/data"


def _fake_git_run(args, **kwargs):
    if args[:2] == ["git", "rev-parse"]:
        return subprocess.CompletedProcess(args, 0, stdout="my-branch\n")
    return subprocess.CompletedProcess(args, 0, stdout="abc1234\n")


class TestGetVersion:
    """get_version() must never raise — --version should always print
    something, even when neither the package nor git is available
    (e.g. running from a bare, uninstalled source checkout)."""

    def test_package_version_only_when_not_a_git_checkout(self):
        with patch("ada.utils._pkg_version", return_value="1.2.3"), \
             patch("ada.utils._git_info", return_value=None):
            assert get_version() == "1.2.3"

    def test_appends_git_branch_and_commit_to_package_version(self):
        # Editable dev installs (poetry install) have valid package
        # metadata regardless of which branch is checked out, so the
        # git info is appended rather than only used as a fallback.
        with patch("ada.utils._pkg_version", return_value="1.2.3"), \
             patch("ada.utils.subprocess.run", side_effect=_fake_git_run):
            assert get_version() == "1.2.3 (branch: my-branch, commit: abc1234)"

    def test_falls_back_to_git_info_when_package_not_installed(self):
        with patch("ada.utils._pkg_version", side_effect=PackageNotFoundError), \
             patch("ada.utils.subprocess.run", side_effect=_fake_git_run):
            assert get_version() == "branch: my-branch, commit: abc1234 (development version)"

    def test_falls_back_to_unknown_when_neither_available(self):
        with patch("ada.utils._pkg_version", side_effect=PackageNotFoundError), \
             patch("ada.utils.subprocess.run", side_effect=FileNotFoundError("no git")):
            assert get_version() == "unknown"

    def test_falls_back_to_unknown_when_not_a_git_repo(self):
        with patch("ada.utils._pkg_version", side_effect=PackageNotFoundError), \
             patch(
                 "ada.utils.subprocess.run",
                 side_effect=subprocess.CalledProcessError(128, ["git"]),
             ):
            assert get_version() == "unknown"

"""Tests for ada.utils module."""

from __future__ import annotations

import pytest

from ada.utils import (
    encode_path,
    human_readable_size,
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


class TestHumanReadableSize:
    def test_bytes(self):
        assert human_readable_size(500) == "500 B"

    def test_kib(self):
        assert human_readable_size(1024) == "1.0 KiB"

    def test_mib(self):
        assert human_readable_size(1048576) == "1.0 MiB"

    def test_gib(self):
        assert human_readable_size(1073741824) == "1.0 GiB"

    def test_tib(self):
        assert human_readable_size(1099511627776) == "1.0 TiB"


class TestNormalizePath:
    def test_trailing_slash(self):
        assert normalize_path("/pnfs/data/") == "/pnfs/data"

    def test_double_slash(self):
        assert normalize_path("/pnfs//data") == "/pnfs/data"

    def test_root_preserved(self):
        assert normalize_path("/") == "/"

    def test_whitespace(self):
        assert normalize_path("  /pnfs/data  ") == "/pnfs/data"

"""Tests for ada.cli.formatters module."""

from __future__ import annotations

from ada.cli.formatters import format_stat


class TestFormatStat:
    def test_flat_scalar_fields(self):
        lines = format_stat({"fileType": "REGULAR", "size": 5})

        assert lines == ["fileType: REGULAR", "size:     5"]

    def test_nested_dict_is_dotted(self):
        lines = format_stat({"storageInfo": {"hsm": "osm", "storageClass": "generic:disk"}})

        assert lines == [
            "storageInfo.hsm:          osm",
            "storageInfo.storageClass: generic:disk",
        ]

    def test_list_of_scalars_is_comma_joined(self):
        lines = format_stat({"locations": ["pool1", "pool2"]})

        assert lines == ["locations: pool1, pool2"]

    def test_empty_list_shown_as_dash(self):
        lines = format_stat({"labels": []})

        assert lines == ["labels: -"]

    def test_list_of_dicts_is_indexed_and_dotted(self):
        lines = format_stat(
            {"checksums": [{"type": "ADLER32", "value": "abc"}, {"type": "MD5", "value": "def"}]}
        )

        assert lines == [
            "checksums[0].type:  ADLER32",
            "checksums[0].value: abc",
            "checksums[1].type:  MD5",
            "checksums[1].value: def",
        ]

    def test_future_unknown_field_is_shown_automatically(self):
        # The whole point of this generic formatter: a field this code has
        # never seen before (e.g. added in a future dCache version) is
        # still printed, with no code changes required.
        lines = format_stat({"brandNewFutureField": "surprise"})

        assert lines == ["brandNewFutureField: surprise"]

    def test_epoch_millis_field_gets_formatted_date_appended(self):
        lines = format_stat({"mtime": 1764836149771})

        assert lines == ["mtime: 1764836149771 (2025-12-04T08:15:49.771000+00:00)"]

    def test_future_time_field_also_gets_formatted_automatically(self):
        # Matching by name pattern ("time" in the key), not a hardcoded
        # list of known field names, so a future field like
        # 'modificationTime' is picked up without code changes.
        lines = format_stat({"modificationTime": 1764836149771})

        assert "(2025-12-04T08:15:49.771000+00:00)" in lines[0]

    def test_non_timestamp_large_int_is_not_reinterpreted_as_a_date(self):
        # A field that merely contains a large integer (e.g. a file size)
        # but whose name has nothing to do with time must be left alone.
        lines = format_stat({"size": 1764836149771})

        assert lines == ["size: 1764836149771"]

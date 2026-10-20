"""Tests for ada.services.labels module."""

from __future__ import annotations

from unittest.mock import call

import pytest

from ada.exceptions import AdaPathError, AdaValidationError
from ada.services.labels import LabelService


class TestSet:
    def test_posts_set_label_action(self, mock_api):
        mock_api.get.return_value = {"fileType": "REGULAR"}
        svc = LabelService(mock_api)

        result = svc.set("/data/file.txt", "important")

        assert result == "Label 'important' set on '/data/file.txt'"
        mock_api.post.assert_called_once_with(
            "namespace/%2Fdata%2Ffile.txt",
            json={"action": "set-label", "label": "important"},
        )

    def test_raises_on_directory(self, mock_api):
        mock_api.get.return_value = {"fileType": "DIR"}
        svc = LabelService(mock_api)

        with pytest.raises(AdaPathError, match="directory"):
            svc.set("/data/somedir", "important")


class TestList:
    def test_lists_all_labels(self, mock_api):
        mock_api.get.side_effect = [
            {"fileType": "REGULAR"},
            {"labels": ["a", "b"]},
        ]
        svc = LabelService(mock_api)

        assert svc.list("/data/file.txt") == ["a", "b"]

    def test_specific_label_present(self, mock_api):
        mock_api.get.side_effect = [
            {"fileType": "REGULAR"},
            {"labels": ["a", "b"]},
        ]
        svc = LabelService(mock_api)

        assert svc.list("/data/file.txt", label="a") == ["a"]

    def test_specific_label_missing(self, mock_api):
        mock_api.get.side_effect = [
            {"fileType": "REGULAR"},
            {"labels": ["a", "b"]},
        ]
        svc = LabelService(mock_api)

        assert svc.list("/data/file.txt", label="z") == []


class TestRemove:
    def test_removes_single_label(self, mock_api):
        mock_api.get.return_value = {"fileType": "REGULAR"}
        svc = LabelService(mock_api)

        result = svc.remove("/data/file.txt", label="a")

        assert result == "Label 'a' removed from '/data/file.txt'"
        mock_api.post.assert_called_once_with(
            "namespace/%2Fdata%2Ffile.txt",
            json={"action": "rm-label", "label": "a"},
        )

    def test_removes_all_labels(self, mock_api):
        mock_api.get.side_effect = [
            {"fileType": "REGULAR"},  # remove()'s own _ensure_file
            {"fileType": "REGULAR"},  # _ensure_file inside self.list()
            {"labels": ["a", "b"]},   # labels query inside self.list()
        ]
        svc = LabelService(mock_api)

        result = svc.remove("/data/file.txt", all_labels=True)

        assert result == "All labels removed from '/data/file.txt': a, b"
        assert mock_api.post.call_args_list == [
            call("namespace/%2Fdata%2Ffile.txt", json={"action": "rm-label", "label": "a"}),
            call("namespace/%2Fdata%2Ffile.txt", json={"action": "rm-label", "label": "b"}),
        ]

    def test_removes_all_labels_when_none_set(self, mock_api):
        mock_api.get.side_effect = [
            {"fileType": "REGULAR"},
            {"fileType": "REGULAR"},
            {"labels": []},
        ]
        svc = LabelService(mock_api)

        assert svc.remove("/data/file.txt", all_labels=True) == "No labels to remove."
        mock_api.post.assert_not_called()

    def test_without_label_or_all_raises(self, mock_api):
        mock_api.get.return_value = {"fileType": "REGULAR"}
        svc = LabelService(mock_api)

        with pytest.raises(AdaValidationError):
            svc.remove("/data/file.txt")


class TestFind:
    def test_finds_matching_labels(self, mock_api):
        mock_api.get.side_effect = [
            {"fileType": "DIR"},
            {
                "children": [
                    {"fileName": "a.txt", "fileType": "REGULAR", "labels": ["keep", "ada-test"]},
                    {"fileName": "b.txt", "fileType": "REGULAR", "labels": ["other"]},
                    {"fileName": "sub", "fileType": "DIR"},
                ]
            },
        ]
        svc = LabelService(mock_api)

        result = svc.find("/data", regex="ada-.*")

        assert result == [("/data/a.txt", ["ada-test"])]

    def test_raises_if_path_is_a_file(self, mock_api):
        mock_api.get.return_value = {"fileType": "REGULAR"}
        svc = LabelService(mock_api)

        with pytest.raises(AdaPathError, match="directory"):
            svc.find("/data/file.txt", regex=".*")

    def test_recursive_search_descends_into_subdirs(self, mock_api):
        mock_api.get.side_effect = [
            {"fileType": "DIR"},
            {"children": [{"fileName": "sub", "fileType": "DIR"}]},
            {
                "children": [
                    {"fileName": "nested.txt", "fileType": "REGULAR", "labels": ["ada-nested"]},
                ]
            },
        ]
        svc = LabelService(mock_api)

        result = svc.find("/data", regex="ada-.*", recursive=True)

        assert result == [("/data/sub/nested.txt", ["ada-nested"])]

    def test_non_recursive_skips_subdirs(self, mock_api):
        mock_api.get.side_effect = [
            {"fileType": "DIR"},
            {"children": [{"fileName": "sub", "fileType": "DIR"}]},
        ]
        svc = LabelService(mock_api)

        result = svc.find("/data", regex="ada-.*", recursive=False)

        assert result == []

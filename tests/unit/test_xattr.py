"""Tests for ada.services.xattr module."""

from __future__ import annotations

import pytest

from ada.exceptions import AdaPathError, AdaValidationError
from ada.services.xattr import XattrService


class TestSet:
    def test_posts_set_xattr_action(self, mock_api):
        mock_api.get.return_value = {"fileType": "REGULAR"}
        svc = XattrService(mock_api)

        result = svc.set("/data/file.txt", {"project": "spider", "batch": "42"})

        assert result == "Extended attributes set on '/data/file.txt'"
        mock_api.post.assert_called_once_with(
            "namespace/%2Fdata%2Ffile.txt",
            json={"action": "set-xattr", "attributes": {"project": "spider", "batch": "42"}},
        )

    def test_parses_string_attributes(self, mock_api):
        mock_api.get.return_value = {"fileType": "REGULAR"}
        svc = XattrService(mock_api)

        svc.set("/data/file.txt", "project=spider,batch=42")

        mock_api.post.assert_called_once_with(
            "namespace/%2Fdata%2Ffile.txt",
            json={"action": "set-xattr", "attributes": {"project": "spider", "batch": "42"}},
        )

    def test_raises_on_directory(self, mock_api):
        mock_api.get.return_value = {"fileType": "DIR"}
        svc = XattrService(mock_api)

        with pytest.raises(AdaPathError, match="directory"):
            svc.set("/data/somedir", {"a": "1"})


class TestList:
    def test_lists_all_attributes(self, mock_api):
        mock_api.get.side_effect = [
            {"fileType": "REGULAR"},
            {"extendedAttributes": {"project": "spider", "batch": "42"}},
        ]
        svc = XattrService(mock_api)

        assert svc.list("/data/file.txt") == {"project": "spider", "batch": "42"}

    def test_specific_key_present(self, mock_api):
        mock_api.get.side_effect = [
            {"fileType": "REGULAR"},
            {"extendedAttributes": {"project": "spider", "batch": "42"}},
        ]
        svc = XattrService(mock_api)

        assert svc.list("/data/file.txt", key="project") == {"project": "spider"}

    def test_specific_key_missing(self, mock_api):
        mock_api.get.side_effect = [
            {"fileType": "REGULAR"},
            {"extendedAttributes": {"project": "spider"}},
        ]
        svc = XattrService(mock_api)

        assert svc.list("/data/file.txt", key="nope") == {}


class TestRemove:
    def test_removes_single_key(self, mock_api):
        mock_api.get.return_value = {"fileType": "REGULAR"}
        svc = XattrService(mock_api)

        result = svc.remove("/data/file.txt", key="project")

        assert result == "Extended attribute 'project' removed from '/data/file.txt'"
        mock_api.post.assert_called_once_with(
            "namespace/%2Fdata%2Ffile.txt",
            json={"action": "rm-xattr", "names": ["project"]},
        )

    def test_removes_all_keys_in_a_single_call(self, mock_api):
        mock_api.get.side_effect = [
            {"fileType": "REGULAR"},  # remove()'s own _ensure_file
            {"fileType": "REGULAR"},  # _ensure_file inside self.list()
            {"extendedAttributes": {"project": "spider", "batch": "42"}},
        ]
        svc = XattrService(mock_api)

        result = svc.remove("/data/file.txt", all_keys=True)

        assert result == "All extended attributes removed from '/data/file.txt': project, batch"
        mock_api.post.assert_called_once_with(
            "namespace/%2Fdata%2Ffile.txt",
            json={"action": "rm-xattr", "names": ["project", "batch"]},
        )

    def test_removes_all_keys_when_none_set(self, mock_api):
        mock_api.get.side_effect = [
            {"fileType": "REGULAR"},
            {"fileType": "REGULAR"},
            {"extendedAttributes": {}},
        ]
        svc = XattrService(mock_api)

        assert svc.remove("/data/file.txt", all_keys=True) == "No attributes to remove."
        mock_api.post.assert_not_called()

    def test_without_key_or_all_raises(self, mock_api):
        mock_api.get.return_value = {"fileType": "REGULAR"}
        svc = XattrService(mock_api)

        with pytest.raises(AdaValidationError):
            svc.remove("/data/file.txt")


class TestFind:
    def test_finds_matching_specific_key(self, mock_api):
        mock_api.get.side_effect = [
            {"fileType": "DIR"},
            {
                "children": [
                    {"fileName": "a.txt", "fileType": "REGULAR",
                     "extendedAttributes": {"project": "ada-test"}},
                    {"fileName": "b.txt", "fileType": "REGULAR",
                     "extendedAttributes": {"project": "other"}},
                    {"fileName": "sub", "fileType": "DIR"},
                ]
            },
        ]
        svc = XattrService(mock_api)

        result = svc.find("/data", key="project", regex="ada-.*")

        assert result == [("/data/a.txt", {"project": "ada-test"})]

    def test_finds_matching_all_keys(self, mock_api):
        mock_api.get.side_effect = [
            {"fileType": "DIR"},
            {
                "children": [
                    {"fileName": "a.txt", "fileType": "REGULAR",
                     "extendedAttributes": {"other": "ada-test"}},
                ]
            },
        ]
        svc = XattrService(mock_api)

        result = svc.find("/data", key="", regex="ada-.*", all_keys=True)

        assert result == [("/data/a.txt", {"other": "ada-test"})]

    def test_raises_if_path_is_a_file(self, mock_api):
        mock_api.get.return_value = {"fileType": "REGULAR"}
        svc = XattrService(mock_api)

        with pytest.raises(AdaPathError, match="directory"):
            svc.find("/data/file.txt", key="project", regex=".*")

    def test_recursive_search_descends_into_subdirs(self, mock_api):
        mock_api.get.side_effect = [
            {"fileType": "DIR"},
            {"children": [{"fileName": "sub", "fileType": "DIR"}]},
            {
                "children": [
                    {"fileName": "nested.txt", "fileType": "REGULAR",
                     "extendedAttributes": {"project": "ada-nested"}},
                ]
            },
        ]
        svc = XattrService(mock_api)

        result = svc.find("/data", key="project", regex="ada-.*", recursive=True)

        assert result == [("/data/sub/nested.txt", {"project": "ada-nested"})]

    def test_non_recursive_skips_subdirs(self, mock_api):
        mock_api.get.side_effect = [
            {"fileType": "DIR"},
            {"children": [{"fileName": "sub", "fileType": "DIR"}]},
        ]
        svc = XattrService(mock_api)

        result = svc.find("/data", key="project", regex="ada-.*", recursive=False)

        assert result == []

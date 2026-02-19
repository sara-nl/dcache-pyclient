"""Tests for ada.services.namespace module."""

from __future__ import annotations

import pytest

from ada.exceptions import AdaNotFoundError, AdaPathError, AdaValidationError
from ada.models import FileType
from ada.services.namespace import NamespaceService


class TestList:
    def test_list_directory(self, mock_api, sample_dir_response):
        mock_api.get.return_value = sample_dir_response
        svc = NamespaceService(mock_api)
        result = svc.list("/test/dir")
        assert "file1.txt" in result
        assert "file2.dat" in result
        assert "subdir/" in result  # Dirs get trailing /

    def test_list_file(self, mock_api):
        mock_api.get.return_value = {"fileType": "REGULAR", "fileName": "test.txt"}
        svc = NamespaceService(mock_api)
        result = svc.list("/data/test.txt")
        assert result == ["test.txt"]


class TestStat:
    def test_stat_file(self, mock_api, sample_file_response):
        mock_api.get.return_value = sample_file_response
        svc = NamespaceService(mock_api)
        info = svc.stat("/data/testfile.dat")
        assert info.file_type == FileType.REGULAR
        assert info.size == 4096
        assert info.pnfs_id == "0000FFFF"
        assert "important" in info.labels
        assert info.extended_attributes["project"] == "spider"
        assert len(info.checksums) == 2


class TestMkdir:
    def test_mkdir_simple(self, mock_api):
        # Parent exists, target doesn't
        mock_api.get.side_effect = [
            AdaNotFoundError("not found"),  # target doesn't exist
            {"fileType": "DIR"},  # parent exists
        ]
        mock_api.post.return_value = {"status": "success"}
        svc = NamespaceService(mock_api)
        result = svc.mkdir("/data/newdir")
        assert result == "created"

    def test_mkdir_already_exists(self, mock_api):
        mock_api.get.return_value = {"fileType": "DIR"}
        svc = NamespaceService(mock_api)
        result = svc.mkdir("/data/existing")
        assert result == "already exists"

    def test_mkdir_recursive_limit(self, mock_api):
        svc = NamespaceService(mock_api)
        with pytest.raises(AdaValidationError, match="Maximum number"):
            svc.mkdir("/a/b/c", recursive=True, _depth=11)


class TestMv:
    def test_mv_success(self, mock_api):
        mock_api.get.side_effect = AdaNotFoundError("not found")  # dest doesn't exist
        mock_api.post.return_value = {"status": "success"}
        svc = NamespaceService(mock_api)
        result = svc.mv("/data/old", "/data/new")
        assert result == "moved"

    def test_mv_dest_exists(self, mock_api):
        mock_api.get.return_value = {"fileType": "REGULAR"}  # dest exists
        svc = NamespaceService(mock_api)
        with pytest.raises(AdaPathError, match="already exists"):
            svc.mv("/data/old", "/data/new")


class TestDelete:
    def test_delete_file(self, mock_api):
        mock_api.get.return_value = {"fileType": "REGULAR"}
        svc = NamespaceService(mock_api)
        svc.delete("/data/file.txt")
        mock_api.delete.assert_called_once()

    def test_delete_nonempty_dir_without_recursive(self, mock_api):
        mock_api.get.side_effect = [
            {"fileType": "DIR"},  # get_file_type
            {"fileType": "DIR", "children": [{"fileName": "child"}]},  # _get_children
        ]
        svc = NamespaceService(mock_api)
        with pytest.raises(AdaPathError, match="not empty"):
            svc.delete("/data/mydir")


class TestGetFileType:
    def test_regular_file(self, mock_api):
        mock_api.get.return_value = {"fileType": "REGULAR"}
        svc = NamespaceService(mock_api)
        assert svc.get_file_type("/data/file.txt") == FileType.REGULAR

    def test_directory(self, mock_api):
        mock_api.get.return_value = {"fileType": "DIR"}
        svc = NamespaceService(mock_api)
        assert svc.get_file_type("/data/mydir") == FileType.DIR

"""Tests for ada.services.transfer (upload/download business logic).

WebdavClient itself is mocked out here -- its actual HTTP/redirect
behavior is covered by tests/unit/test_webdav.py. These tests focus on
the decisions TransferService makes: existing-file handling, the
online/tape check before download, and checksum verification.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ada.auth import TokenAuth
from ada.exceptions import AdaNotFoundError, AdaPathError, AdaTransferError
from ada.services.transfer import TransferService


@pytest.fixture
def api(mock_api):
    """mock_api with the extra attributes TransferService relies on."""
    mock_api.auth = TokenAuth("tok")
    mock_api.verify = True
    return mock_api


@pytest.fixture
def webdav_client():
    """Patches out WebdavClient so no real HTTP happens."""
    with patch("ada.services.transfer.WebdavClient") as cls:
        instance = MagicMock()
        cls.return_value = instance
        yield instance


def _not_found(path):
    return AdaNotFoundError(f"not found: {path}")


class TestUpload:
    def test_new_file_uploads(self, tmp_path, api, webdav_client):
        local = tmp_path / "file.txt"
        local.write_bytes(b"hello")
        # target doesn't exist; parent is a dir
        api.get.side_effect = [
            _not_found("/data/file.txt"),  # file_type_or_none(target)
            {"fileType": "DIR"},  # is_dir(parent)
        ]
        svc = TransferService(api)
        result = svc.upload(
            str(local), "https://door.example.org/data/file.txt"
        )
        assert result.status == "uploaded"
        assert result.remote_path == "/data/file.txt"
        webdav_client.upload.assert_called_once()
        args, kwargs = webdav_client.upload.call_args
        assert args[0] == str(local)
        assert args[1] == "/data/file.txt"

    def test_local_file_missing(self, tmp_path, api):
        svc = TransferService(api)
        with pytest.raises(AdaPathError, match="does not exist"):
            svc.upload(str(tmp_path / "nope.txt"), "/data/file.txt")

    def test_target_exists_without_verify_checksum(self, tmp_path, api):
        local = tmp_path / "file.txt"
        local.write_bytes(b"hello")
        api.get.return_value = {"fileType": "REGULAR"}
        svc = TransferService(api)
        with pytest.raises(AdaPathError, match="already exists"):
            svc.upload(str(local), "https://door.example.org/data/file.txt")

    def test_target_exists_with_matching_checksum(self, tmp_path, api):
        local = tmp_path / "file.txt"
        local.write_bytes(b"hello")
        import zlib
        adler = format(zlib.adler32(b"hello") & 0xFFFFFFFF, "08x")
        api.get.side_effect = [
            {"fileType": "REGULAR"},  # file_type_or_none
            {"fileType": "REGULAR"},  # ChecksumService.get()'s internal dir-check
            {"checksums": [{"type": "ADLER32", "value": adler}]},  # checksum lookup
        ]
        svc = TransferService(api)
        result = svc.upload(
            str(local), "https://door.example.org/data/file.txt", verify_checksum=True
        )
        assert result.status == "already-verified"
        assert result.checksum_verified is True

    def test_target_exists_with_checksum_mismatch(self, tmp_path, api):
        local = tmp_path / "file.txt"
        local.write_bytes(b"hello")
        api.get.side_effect = [
            {"fileType": "REGULAR"},
            {"fileType": "REGULAR"},  # ChecksumService.get()'s internal dir-check
            {"checksums": [{"type": "ADLER32", "value": "deadbeef"}]},
        ]
        svc = TransferService(api)
        with pytest.raises(AdaTransferError, match="Checksum mismatch"):
            svc.upload(
                str(local), "https://door.example.org/data/file.txt", verify_checksum=True
            )

    def test_target_is_symlink(self, tmp_path, api):
        local = tmp_path / "file.txt"
        local.write_bytes(b"hello")
        api.get.return_value = {"fileType": "LINK"}
        svc = TransferService(api)
        with pytest.raises(AdaPathError, match="symlink"):
            svc.upload(str(local), "https://door.example.org/data/file.txt")

    def test_target_is_dir_uploads_using_local_filename(self, tmp_path, api, webdav_client):
        local = tmp_path / "file.txt"
        local.write_bytes(b"hello")
        api.get.side_effect = [
            {"fileType": "DIR"},  # target is a dir
            _not_found("/data/file.txt"),  # real target doesn't exist
            {"fileType": "DIR"},  # parent is a dir
        ]
        svc = TransferService(api)
        result = svc.upload(str(local), "https://door.example.org/data/")
        assert result.remote_path == "/data/file.txt"

    def test_parent_missing(self, tmp_path, api):
        local = tmp_path / "file.txt"
        local.write_bytes(b"hello")
        api.get.side_effect = [
            _not_found("/data/sub/file.txt"),
            AdaNotFoundError("no parent"),  # is_dir catches broad Exception -> False
        ]
        svc = TransferService(api)
        with pytest.raises(AdaPathError, match="is not a directory"):
            svc.upload(str(local), "https://door.example.org/data/sub/file.txt")

    def test_verify_checksum_sends_content_md5_header(self, tmp_path, api, webdav_client):
        local = tmp_path / "file.txt"
        local.write_bytes(b"hello")
        api.get.side_effect = [
            _not_found("/data/file.txt"),
            {"fileType": "DIR"},
        ]
        svc = TransferService(api)
        svc.upload(
            str(local), "https://door.example.org/data/file.txt", verify_checksum=True
        )
        _, kwargs = webdav_client.upload.call_args
        assert "Content-MD5" in kwargs["extra_headers"]

    def test_discovers_door_when_not_prefixed(self, tmp_path, api, webdav_client):
        local = tmp_path / "file.txt"
        local.write_bytes(b"hello")
        api.get.side_effect = [
            _not_found("/data/file.txt"),
            {"fileType": "DIR"},
        ]
        with patch(
            "ada.services.transfer.discover_webdav_door", return_value="https://discovered.example.org"
        ) as discover:
            svc = TransferService(api)
            svc.upload(str(local), "/data/file.txt")
            discover.assert_called_once()


class TestDownload:
    def test_fresh_download(self, tmp_path, api, webdav_client):
        local = tmp_path / "out.txt"
        api.get.return_value = {"fileType": "REGULAR", "fileLocality": "ONLINE"}
        svc = TransferService(api)
        result = svc.download("https://door.example.org/data/file.txt", str(local))
        assert result.status == "downloaded"
        webdav_client.download.assert_called_once_with("/data/file.txt", str(local))

    def test_local_target_exists_without_verify(self, tmp_path, api):
        local = tmp_path / "out.txt"
        local.write_bytes(b"existing")
        svc = TransferService(api)
        with pytest.raises(AdaPathError, match="already exists"):
            svc.download("https://door.example.org/data/file.txt", str(local))

    def test_local_target_exists_checksum_matches(self, tmp_path, api):
        local = tmp_path / "out.txt"
        local.write_bytes(b"hello")
        import zlib
        adler = format(zlib.adler32(b"hello") & 0xFFFFFFFF, "08x")
        api.get.return_value = {"checksums": [{"type": "ADLER32", "value": adler}]}
        svc = TransferService(api)
        result = svc.download(
            "https://door.example.org/data/file.txt", str(local), verify_checksum=True
        )
        assert result.status == "already-verified"

    def test_local_target_is_dir_appends_remote_name(self, tmp_path, api, webdav_client):
        api.get.return_value = {"fileType": "REGULAR", "fileLocality": "ONLINE"}
        svc = TransferService(api)
        result = svc.download("https://door.example.org/data/file.txt", str(tmp_path))
        expected = str(tmp_path / "file.txt")
        assert result.local_path == expected
        webdav_client.download.assert_called_once_with("/data/file.txt", expected)

    def test_local_target_in_dir_already_exists(self, tmp_path, api):
        (tmp_path / "file.txt").write_bytes(b"already here")
        svc = TransferService(api)
        with pytest.raises(AdaPathError, match="already exists"):
            svc.download("https://door.example.org/data/file.txt", str(tmp_path))

    def test_parent_missing(self, tmp_path, api):
        local = tmp_path / "does-not-exist-dir" / "out.txt"
        svc = TransferService(api)
        with pytest.raises(AdaPathError, match="does not exist"):
            svc.download("https://door.example.org/data/file.txt", str(local))

    def test_source_missing(self, tmp_path, api):
        local = tmp_path / "out.txt"
        api.get.side_effect = _not_found("/data/file.txt")
        svc = TransferService(api)
        with pytest.raises(AdaNotFoundError):
            svc.download("https://door.example.org/data/file.txt", str(local))

    def test_source_is_directory(self, tmp_path, api):
        local = tmp_path / "out.txt"
        api.get.return_value = {"fileType": "DIR"}
        svc = TransferService(api)
        with pytest.raises(AdaPathError, match="a directory"):
            svc.download("https://door.example.org/data/mydir", str(local))

    def test_source_is_symlink(self, tmp_path, api):
        local = tmp_path / "out.txt"
        api.get.return_value = {"fileType": "LINK"}
        svc = TransferService(api)
        with pytest.raises(AdaPathError, match="symlink"):
            svc.download("https://door.example.org/data/link", str(local))

    def test_source_not_online_refuses_and_suggests_stage(self, tmp_path, api):
        local = tmp_path / "out.txt"
        api.get.return_value = {"fileType": "REGULAR", "fileLocality": "NEARLINE"}
        svc = TransferService(api)
        with pytest.raises(AdaTransferError, match="stage") as exc_info:
            svc.download("https://door.example.org/data/file.txt", str(local))
        assert "ada-cli stage" in str(exc_info.value)

    def test_online_and_nearline_is_allowed(self, tmp_path, api, webdav_client):
        local = tmp_path / "out.txt"
        api.get.return_value = {"fileType": "REGULAR", "fileLocality": "ONLINE_AND_NEARLINE"}
        svc = TransferService(api)
        result = svc.download("https://door.example.org/data/file.txt", str(local))
        assert result.status == "downloaded"

    def test_post_download_checksum_verified(self, tmp_path, api, webdav_client):
        local = tmp_path / "out.txt"

        def write_file(remote, local_path):
            (tmp_path / "out.txt").write_bytes(b"hello")

        webdav_client.download.side_effect = write_file
        import zlib
        adler = format(zlib.adler32(b"hello") & 0xFFFFFFFF, "08x")
        api.get.side_effect = [
            {"fileType": "REGULAR", "fileLocality": "ONLINE"},  # file_type_or_none
            {"fileType": "REGULAR", "fileLocality": "ONLINE"},  # is_online
            {"fileType": "REGULAR"},  # ChecksumService.get()'s internal dir-check
            {"checksums": [{"type": "ADLER32", "value": adler}]},  # post-download verify
        ]
        svc = TransferService(api)
        result = svc.download(
            "https://door.example.org/data/file.txt", str(local), verify_checksum=True
        )
        assert result.checksum_verified is True

    def test_post_download_checksum_mismatch_raises(self, tmp_path, api, webdav_client):
        local = tmp_path / "out.txt"

        def write_file(remote, local_path):
            (tmp_path / "out.txt").write_bytes(b"corrupted")

        webdav_client.download.side_effect = write_file
        api.get.side_effect = [
            {"fileType": "REGULAR", "fileLocality": "ONLINE"},
            {"fileType": "REGULAR", "fileLocality": "ONLINE"},  # is_online
            {"fileType": "REGULAR"},  # ChecksumService.get()'s internal dir-check
            {"checksums": [{"type": "ADLER32", "value": "deadbeef"}]},
        ]
        svc = TransferService(api)
        with pytest.raises(AdaTransferError, match="Checksum mismatch"):
            svc.download(
                "https://door.example.org/data/file.txt", str(local), verify_checksum=True
            )

    def test_discovers_door_when_not_prefixed(self, tmp_path, api, webdav_client):
        local = tmp_path / "out.txt"
        api.get.return_value = {"fileType": "REGULAR", "fileLocality": "ONLINE"}
        with patch(
            "ada.services.transfer.discover_webdav_door", return_value="https://discovered.example.org"
        ) as discover:
            svc = TransferService(api)
            svc.download("/data/file.txt", str(local))
            discover.assert_called_once()


class TestSplitDoorAndPath:
    def test_with_door(self):
        door, path = TransferService._split_door_and_path("https://door.example.org/pnfs/data/file")
        assert door == "https://door.example.org"
        assert path == "/pnfs/data/file"

    def test_without_door(self):
        door, path = TransferService._split_door_and_path("/pnfs/data/file")
        assert door is None
        assert path == "/pnfs/data/file"


class TestLocalChecksums:
    def test_local_adler32(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_bytes(b"hello")
        import zlib
        expected = format(zlib.adler32(b"hello") & 0xFFFFFFFF, "08x")
        assert TransferService._local_adler32(str(f)) == expected

    def test_local_md5(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_bytes(b"hello")
        import hashlib
        expected = hashlib.md5(b"hello").hexdigest()
        assert TransferService._local_md5(str(f)) == expected

    def test_content_md5_header(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_bytes(b"hello")
        import base64
        import hashlib
        expected = base64.b64encode(hashlib.md5(b"hello").digest()).decode("ascii")
        assert TransferService._content_md5_header(str(f)) == expected

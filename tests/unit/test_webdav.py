"""Tests for ada.webdav (WebDAV door discovery and streaming client)."""

from __future__ import annotations

import httpx
import pytest

from ada.auth import TokenAuth, TokenFileAuth
from ada.exceptions import AdaAPIError, AdaTransferError
from ada.webdav import (
    WebdavClient,
    _door_from_config_js,
    _door_from_doors_api,
    _door_from_tokenfile,
    discover_webdav_door,
)


class FakeApi:
    """Minimal stand-in for DcacheAPI, only implementing what door discovery uses."""

    def __init__(self, base_url="https://dcache.example.org/api/v1", doors=None, config_js=None):
        self.base_url = base_url
        self._doors = doors
        self._config_js = config_js

    def get(self, endpoint):
        if endpoint == "doors":
            if self._doors is None:
                raise AdaAPIError("no doors endpoint")
            return self._doors
        raise AdaAPIError(f"unexpected endpoint: {endpoint}")

    def get_absolute(self, url, accept="application/json"):
        if self._config_js is None:
            raise AdaAPIError("config.js not available")
        return self._config_js


# ---- Door discovery ----


class TestDoorFromTokenfile:
    def test_reads_url_line(self, tmp_path):
        tokenfile = tmp_path / "rclone.conf"
        tokenfile.write_text("[remote]\nbearer_token = abc\nurl = https://webdav.example.org:2880\n")
        assert _door_from_tokenfile(str(tokenfile)) == "https://webdav.example.org:2880"

    def test_no_url_line(self, tmp_path):
        tokenfile = tmp_path / "rclone.conf"
        tokenfile.write_text("[remote]\nbearer_token = abc\n")
        assert _door_from_tokenfile(str(tokenfile)) is None

    def test_missing_file(self, tmp_path):
        assert _door_from_tokenfile(str(tmp_path / "nope.conf")) is None


class TestDoorFromConfigJs:
    def test_present(self):
        api = FakeApi(config_js={"dcache-view.endpoints.webdav": "https://webdav.example.org"})
        assert _door_from_config_js(api) == "https://webdav.example.org"

    def test_key_missing(self):
        api = FakeApi(config_js={"some-other-key": "value"})
        assert _door_from_config_js(api) is None

    def test_not_a_dict(self):
        api = FakeApi(config_js="not json")
        assert _door_from_config_js(api) is None

    def test_request_fails(self):
        api = FakeApi(config_js=None)
        assert _door_from_config_js(api) is None


class TestDoorFromDoorsApi:
    def test_picks_best_door(self):
        doors = [
            {
                "protocol": "https", "root": "/", "readPaths": ["/"], "writePaths": ["/"],
                "addresses": ["door-a"], "port": 2880, "tags": ["a"], "load": 0.1,
            },
            {
                # More tags -> preferred over door-a despite non-443 port
                "protocol": "https", "root": "/", "readPaths": ["/"], "writePaths": ["/"],
                "addresses": ["door-b"], "port": 2880, "tags": ["a", "b", "c"], "load": 0.9,
            },
        ]
        api = FakeApi(doors=doors)
        assert _door_from_doors_api(api) == "https://door-b:2880"

    def test_prefers_port_443_when_tags_equal(self):
        doors = [
            {
                "protocol": "https", "root": "/", "readPaths": ["/"], "writePaths": ["/"],
                "addresses": ["door-a"], "port": 2880, "tags": ["a"], "load": 0.5,
            },
            {
                "protocol": "https", "root": "/", "readPaths": ["/"], "writePaths": ["/"],
                "addresses": ["door-b"], "port": 443, "tags": ["a"], "load": 0.5,
            },
        ]
        api = FakeApi(doors=doors)
        assert _door_from_doors_api(api) == "https://door-b:443"

    def test_filters_non_https(self):
        doors = [
            {
                "protocol": "gridftp", "root": "/", "readPaths": ["/"], "writePaths": ["/"],
                "addresses": ["door-a"], "port": 2811, "tags": [], "load": 0,
            },
        ]
        api = FakeApi(doors=doors)
        assert _door_from_doors_api(api) is None

    def test_filters_restricted_paths(self):
        doors = [
            {
                "protocol": "https", "root": "/", "readPaths": ["/restricted"], "writePaths": ["/"],
                "addresses": ["door-a"], "port": 2880, "tags": [], "load": 0,
            },
        ]
        api = FakeApi(doors=doors)
        assert _door_from_doors_api(api) is None

    def test_no_doors(self):
        api = FakeApi(doors=[])
        assert _door_from_doors_api(api) is None

    def test_request_fails(self):
        api = FakeApi(doors=None)
        assert _door_from_doors_api(api) is None


class TestDiscoverWebdavDoor:
    def test_tokenfile_takes_priority(self, tmp_path):
        tokenfile = tmp_path / "rclone.conf"
        tokenfile.write_text("bearer_token = abc\nurl = https://from-tokenfile.example.org\n")
        tokenfile.chmod(0o600)
        auth = TokenFileAuth(str(tokenfile))
        api = FakeApi(
            config_js={"dcache-view.endpoints.webdav": "https://from-config-js.example.org"},
        )
        assert discover_webdav_door(api, auth) == "https://from-tokenfile.example.org"

    def test_falls_back_to_config_js(self):
        auth = TokenAuth("sometoken")
        api = FakeApi(config_js={"dcache-view.endpoints.webdav": "https://from-config-js.example.org"})
        assert discover_webdav_door(api, auth) == "https://from-config-js.example.org"

    def test_falls_back_to_doors_api(self):
        auth = TokenAuth("sometoken")
        doors = [
            {
                "protocol": "https", "root": "/", "readPaths": ["/"], "writePaths": ["/"],
                "addresses": ["door-a"], "port": 443, "tags": [], "load": 0,
            },
        ]
        api = FakeApi(config_js=None, doors=doors)
        assert discover_webdav_door(api, auth) == "https://door-a:443"

    def test_raises_when_nothing_found(self):
        auth = TokenAuth("sometoken")
        api = FakeApi(config_js=None, doors=None)
        with pytest.raises(AdaTransferError, match="Unable to determine"):
            discover_webdav_door(api, auth)


# ---- WebdavClient ----


def _client_with_transport(handler, **kwargs) -> WebdavClient:
    client = WebdavClient(door="https://door.example.org", auth=TokenAuth("tok"), **kwargs)
    client._client = httpx.Client(
        transport=httpx.MockTransport(handler), follow_redirects=False
    )
    return client


class TestWebdavClientUpload:
    def test_successful_upload(self, tmp_path):
        local = tmp_path / "file.txt"
        local.write_bytes(b"hello world")
        requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            assert request.method == "PUT"
            assert request.url == "https://door.example.org/pnfs/data/file.txt"
            assert request.read() == b"hello world"
            return httpx.Response(201)

        client = _client_with_transport(handler)
        client.upload(str(local), "/pnfs/data/file.txt")
        assert len(requests) == 1

    def test_http_error_raises(self, tmp_path):
        local = tmp_path / "file.txt"
        local.write_bytes(b"hello")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, text="forbidden")

        client = _client_with_transport(handler)
        with pytest.raises(AdaAPIError, match="403"):
            client.upload(str(local), "/pnfs/data/file.txt")

    def test_follows_https_redirect(self, tmp_path):
        local = tmp_path / "file.txt"
        local.write_bytes(b"data")
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            if str(request.url) == "https://door.example.org/pnfs/data/file.txt":
                return httpx.Response(
                    307, headers={"Location": "https://pool.example.org/write/file.txt"}
                )
            return httpx.Response(201)

        client = _client_with_transport(handler)
        client.upload(str(local), "/pnfs/data/file.txt")
        assert calls == [
            "https://door.example.org/pnfs/data/file.txt",
            "https://pool.example.org/write/file.txt",
        ]

    def test_refuses_insecure_redirect_by_default(self, tmp_path):
        local = tmp_path / "file.txt"
        local.write_bytes(b"data")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                307, headers={"Location": "http://pool.example.org/write/file.txt"}
            )

        client = _client_with_transport(handler)
        with pytest.raises(AdaTransferError, match="insecure redirect"):
            client.upload(str(local), "/pnfs/data/file.txt")

    def test_allows_insecure_redirect_when_opted_in(self, tmp_path):
        local = tmp_path / "file.txt"
        local.write_bytes(b"data")
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            if str(request.url).startswith("https://"):
                return httpx.Response(
                    307, headers={"Location": "http://pool.example.org/write/file.txt"}
                )
            return httpx.Response(201)

        client = _client_with_transport(handler, allow_insecure_redirects=True)
        client.upload(str(local), "/pnfs/data/file.txt")
        assert calls[-1] == "http://pool.example.org/write/file.txt"

    def test_too_many_redirects(self, tmp_path):
        local = tmp_path / "file.txt"
        local.write_bytes(b"data")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                307, headers={"Location": "https://door.example.org/pnfs/data/file.txt"}
            )

        client = _client_with_transport(handler)
        with pytest.raises(AdaTransferError, match="Too many redirects"):
            client.upload(str(local), "/pnfs/data/file.txt")


class TestWebdavClientDownload:
    def test_successful_download(self, tmp_path):
        local = tmp_path / "out.txt"

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            return httpx.Response(200, content=b"remote content")

        client = _client_with_transport(handler)
        client.download("/pnfs/data/file.txt", str(local))
        assert local.read_bytes() == b"remote content"

    def test_http_error_raises(self, tmp_path):
        local = tmp_path / "out.txt"

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="not found")

        client = _client_with_transport(handler)
        with pytest.raises(AdaAPIError, match="404"):
            client.download("/pnfs/data/file.txt", str(local))

    def test_follows_https_redirect(self, tmp_path):
        local = tmp_path / "out.txt"

        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url) == "https://door.example.org/pnfs/data/file.txt":
                return httpx.Response(
                    302, headers={"Location": "https://pool.example.org/read/file.txt"}
                )
            return httpx.Response(200, content=b"data from pool")

        client = _client_with_transport(handler)
        client.download("/pnfs/data/file.txt", str(local))
        assert local.read_bytes() == b"data from pool"

    def test_refuses_insecure_redirect_by_default(self, tmp_path):
        local = tmp_path / "out.txt"

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                302, headers={"Location": "http://pool.example.org/read/file.txt"}
            )

        client = _client_with_transport(handler)
        with pytest.raises(AdaTransferError, match="insecure redirect"):
            client.download("/pnfs/data/file.txt", str(local))

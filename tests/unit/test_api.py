"""Unit tests for the low-level dCache API client."""

import httpx
import pytest

from ada.api import DcacheAPI
from ada.auth import TokenAuth
from ada.exceptions import AdaNotFoundError
from ada.utils import encode_path

BASE_URL = "https://dcache.example.org:22880/api/v1"


@pytest.fixture
def api(make_jwt_token):
    api = DcacheAPI(BASE_URL, TokenAuth(make_jwt_token()))
    yield api
    api.close()


def _response(status: int, url: str) -> httpx.Response:
    return httpx.Response(status, request=httpx.Request("GET", url))


class TestNotFound:
    def test_namespace_404_shows_dcache_path(self, api):
        # Issue #79: show the dCache path, not the encoded API URL.
        path = "/pnfs/example.org/data/users/me/missing dir"
        url = f"{BASE_URL}/namespace/{encode_path(path)}?optional=true"
        with pytest.raises(AdaNotFoundError) as exc_info:
            api._handle_response(_response(404, url))
        assert str(exc_info.value) == f"Not found: {path}"
        assert exc_info.value.url == url
        assert exc_info.value.status_code == 404

    def test_other_404_shows_url(self, api):
        url = f"{BASE_URL}/bulk-requests/abc123"
        with pytest.raises(AdaNotFoundError) as exc_info:
            api._handle_response(_response(404, url))
        assert str(exc_info.value) == f"Not found: {url}"
        assert exc_info.value.url == url

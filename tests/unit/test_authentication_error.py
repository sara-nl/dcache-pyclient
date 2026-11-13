"""Tests for the error on HTTP 401: dCache's reason, or a hint (#63)."""

import httpx
import pytest

from ada.api import authentication_error
from ada.auth import NetrcAuth, TokenAuth
from ada.exceptions import AdaAuthenticationError
from ada.webdav import WebdavClient

IP_REASON = (
    "macaroon login denied: Invalid macaroon [-:mMMC/TU5]: "
    "Client fails to match IP caveat ip:192.0.2.0/24"
)


def _response_401(reason: str) -> httpx.Response:
    # dCache puts the reason in the status line, the body is empty
    return httpx.Response(
        401,
        request=httpx.Request("GET", "https://dcache.example.org/api/v1/user"),
        extensions={"reason_phrase": reason.encode()},
    )


class TestAuthenticationError:
    def test_specific_reason_is_shown(self):
        error = authentication_error(_response_401(IP_REASON), TokenAuth("tok", source="$BEARER_TOKEN"))
        assert str(error) == f"dCache rejected the credentials (token ($BEARER_TOKEN)): {IP_REASON}"
        assert error.reason == IP_REASON

    @pytest.mark.parametrize("reason", ["login failed", "Unauthorized", ""])
    def test_generic_reason_gives_hint(self, reason):
        error = authentication_error(_response_401(reason), TokenAuth("tok", source="$BEARER_TOKEN"))
        assert str(error).startswith("dCache rejected the credentials (token ($BEARER_TOKEN)). ")
        assert "token is valid" in str(error)
        assert error.reason == reason

    def test_netrc_hint_names_host(self, tmp_path):
        netrcfile = tmp_path / "netrc"
        netrcfile.write_text("machine dcache.example.org login me password secret\n")
        netrcfile.chmod(0o600)
        auth = NetrcAuth(str(netrcfile), hostname="dcache.example.org")
        error = authentication_error(_response_401("login failed"), auth)
        assert str(error) == (
            f"dCache rejected the credentials (netrc ({netrcfile})). "
            "Check the username and password for dcache.example.org in the netrc file."
        )


class TestWebdav401:
    def test_reason_is_shown(self):
        def handler(request):
            return httpx.Response(401, extensions={"reason_phrase": IP_REASON.encode()})

        client = WebdavClient(door="https://door.example.org", auth=TokenAuth("tok"))
        client._client = httpx.Client(transport=httpx.MockTransport(handler))
        with pytest.raises(AdaAuthenticationError, match="Client fails to match IP caveat"):
            client.download("/data/file", "/dev/null")

"""Tests for ada.tokens module."""

from __future__ import annotations

import base64
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx
import pytest

from ada.exceptions import AdaAuthError, AdaTokenExpiredError, AdaTokenPermissionError
from ada.auth import (
    ProxyAuth,
    TokenAuth,
    check_ip_caveat,
    decode_jwt,
    decode_jwt_payload,
    decode_macaroon,
    describe_expiry,
    format_duration,
    get_public_ip,
    is_jwt,
    validate_token,
)
from tests.unit.test_x509util import _build_cert, _pem, _seq, _time, TAG_GENERALIZEDTIME


class TestIsJwt:
    def test_valid_jwt_pattern(self, make_jwt_token):
        token = make_jwt_token()
        assert is_jwt(token) is True

    def test_not_jwt(self):
        assert is_jwt("notajwttoken") is False

    def test_macaroon_like(self):
        assert is_jwt("MDAxY2xvY2F0aW9uIG1hY2Fyb29u") is False


class TestDecodeJwtPayload:
    def test_valid_token(self, make_jwt_token):
        token = make_jwt_token()
        payload = decode_jwt_payload(token)
        assert "exp" in payload
        assert "sub" in payload
        assert payload["sub"] == "testuser"

    def test_invalid_token(self):
        with pytest.raises(AdaAuthError, match="Invalid JWT"):
            decode_jwt_payload("not.a.validtoken!!!")

    def test_two_parts_only(self):
        with pytest.raises(AdaAuthError, match="3 dot-separated"):
            decode_jwt_payload("only.twoparts")


class TestDecodeJwt:
    def test_timestamps_converted(self, make_jwt_token):
        token = make_jwt_token()
        result = decode_jwt(token)
        # exp should be an ISO string now
        assert isinstance(result["exp"], str)
        assert "T" in result["exp"]


class TestValidateToken:
    def test_valid_token(self, make_jwt_token):
        token = make_jwt_token(exp_offset=3600)
        # Should not raise
        validate_token(token)

    def test_expired_token(self, make_jwt_token):
        token = make_jwt_token(exp_offset=-100)
        with pytest.raises(AdaTokenExpiredError, match="expired"):
            validate_token(token)

    def test_about_to_expire(self, make_jwt_token):
        token = make_jwt_token(exp_offset=30)  # Less than MIN_VALID_TIME (60)
        with pytest.raises(AdaTokenExpiredError, match="will expire"):
            validate_token(token)

    def test_stage_without_permission(self, make_jwt_token):
        token = make_jwt_token(scope="storage.read storage.write")
        with pytest.raises(AdaTokenPermissionError, match="storage.stage"):
            validate_token(token, command="stage")

    def test_stage_with_permission(self, make_jwt_token):
        token = make_jwt_token(scope="storage.read storage.write storage.stage")
        # Should not raise
        validate_token(token, command="stage")

    def test_stage_no_storage_claims(self, make_jwt_token):
        token = make_jwt_token(scope="openid profile email")
        # No storage.* claims = everything allowed
        validate_token(token, command="stage")


class TestProxyAuthValidate:
    """ProxyAuth.validate() must check both the X.509 certificate's own
    expiry and (if present) the VOMS attribute certificate's separate
    validity period, since a VOMS server can expire attributes/roles
    independently of the certificate lifetime.
    """

    def _write_proxy(self, tmp_path, *der_certs: bytes) -> str:
        proxyfile = tmp_path / "proxy.pem"
        proxyfile.write_text(_pem(list(der_certs)))
        return str(proxyfile)

    def test_valid_proxy_no_voms(self, tmp_path):
        now = datetime.now(timezone.utc)
        cert = _build_cert(now - timedelta(hours=1), now + timedelta(hours=5))
        proxyfile = self._write_proxy(tmp_path, cert)
        # Should not raise
        ProxyAuth(proxyfile=proxyfile, igtf=False).validate()

    def test_expired_certificate(self, tmp_path):
        now = datetime.now(timezone.utc)
        cert = _build_cert(now - timedelta(hours=2), now - timedelta(hours=1))
        proxyfile = self._write_proxy(tmp_path, cert)
        with pytest.raises(AdaTokenExpiredError, match="certificate in proxy"):
            ProxyAuth(proxyfile=proxyfile, igtf=False).validate()

    def test_valid_proxy_with_voms_both_ok(self, tmp_path):
        now = datetime.now(timezone.utc)
        voms_ac = _seq(
            _time(TAG_GENERALIZEDTIME, now - timedelta(hours=1)),
            _time(TAG_GENERALIZEDTIME, now + timedelta(hours=5)),
        )
        cert = _build_cert(
            now - timedelta(hours=1), now + timedelta(hours=5), voms_ext_content=voms_ac
        )
        proxyfile = self._write_proxy(tmp_path, cert)
        # Should not raise
        ProxyAuth(proxyfile=proxyfile, igtf=False).validate()

    def test_voms_attributes_expired_before_certificate(self, tmp_path):
        """The certificate is still valid, but the VOMS attributes (FQAN/
        role) have already expired -- this is the case a plain X.509
        expiry check would miss.
        """
        now = datetime.now(timezone.utc)
        voms_ac = _seq(
            _time(TAG_GENERALIZEDTIME, now - timedelta(hours=2)),
            _time(TAG_GENERALIZEDTIME, now - timedelta(minutes=5)),
        )
        cert = _build_cert(
            now - timedelta(hours=1), now + timedelta(hours=5), voms_ext_content=voms_ac
        )
        proxyfile = self._write_proxy(tmp_path, cert)
        with pytest.raises(AdaTokenExpiredError, match="VOMS attributes in proxy"):
            ProxyAuth(proxyfile=proxyfile, igtf=False).validate()

    def test_voms_attributes_about_to_expire(self, tmp_path):
        now = datetime.now(timezone.utc)
        voms_ac = _seq(
            _time(TAG_GENERALIZEDTIME, now - timedelta(hours=1)),
            _time(TAG_GENERALIZEDTIME, now + timedelta(seconds=30)),  # < MIN_VALID_TIME
        )
        cert = _build_cert(
            now - timedelta(hours=1), now + timedelta(hours=5), voms_ext_content=voms_ac
        )
        proxyfile = self._write_proxy(tmp_path, cert)
        with pytest.raises(AdaTokenExpiredError, match="VOMS attributes in proxy"):
            ProxyAuth(proxyfile=proxyfile, igtf=False).validate()

    def test_chain_uses_earliest_certificate_expiry(self, tmp_path):
        """The proxy file's chain may contain multiple certificates
        (e.g. the leaf proxy cert plus the signing user cert); the
        effective certificate expiry is the earliest of the chain.
        """
        now = datetime.now(timezone.utc)
        leaf = _build_cert(now - timedelta(hours=1), now + timedelta(minutes=30))
        signer = _build_cert(now - timedelta(days=30), now + timedelta(days=300))
        proxyfile = self._write_proxy(tmp_path, leaf, signer)
        # Should not raise (30 min > MIN_VALID_TIME margin)
        ProxyAuth(proxyfile=proxyfile, igtf=False).validate()

        leaf_expiring_soon = _build_cert(now - timedelta(hours=1), now + timedelta(seconds=30))
        proxyfile2 = self._write_proxy(tmp_path, leaf_expiring_soon, signer)
        with pytest.raises(AdaTokenExpiredError, match="certificate in proxy"):
            ProxyAuth(proxyfile=proxyfile2, igtf=False).validate()

    def test_no_certificates_in_file(self, tmp_path):
        proxyfile = tmp_path / "empty.pem"
        proxyfile.write_text("not a certificate")
        with pytest.raises(AdaAuthError, match="No certificates found"):
            ProxyAuth(proxyfile=str(proxyfile), igtf=False).validate()


class TestDecodeMacaroonRealWorldFormat:
    """Real macaroons (v2 binary format) are base64url-encoded, often
    unpadded, and each caveat line is prefixed with a hex length and a
    'cid ' tag rather than starting with the caveat name directly —
    e.g. '002ecid before:2026-...Z' instead of 'before:2026-...Z'.
    Found by testing against a real macaroon from dCache."""

    @staticmethod
    def _make_real_style_macaroon(before: str, home: str, activity: str, ip: str) -> str:
        lines = [
            "location dcache-macaroon",
            "0018identifier abcdefgh",
            "0015cid iid:xxxxx",
            f"002ecid before:{before}",
            f"0019cid home:{home}",
            f"0058cid activity:{activity}",
            f"002fcid ip:{ip}",
            "signature deadbeefdeadbeef",
        ]
        text = "\n".join(lines)
        encoded = base64.urlsafe_b64encode(b"\x00\x00\x00\x00" + text.encode()).decode()
        return encoded.rstrip("=")  # unpadded, like real macaroons often are

    def test_decodes_unpadded_base64url_with_cid_prefixed_lines(self):
        token = self._make_real_style_macaroon(
            before="2030-01-01T00:00:00.000000000Z",
            home="/users/onno",
            activity="LIST,DOWNLOAD",
            ip="203.0.113.5/32",
        )
        decoded = decode_macaroon(token)
        assert decoded["before"] == "2030-01-01T00:00:00.000000000Z"
        assert decoded["home"] == "/users/onno"
        assert decoded["activity"] == "LIST,DOWNLOAD"
        assert decoded["ip"] == "203.0.113.5/32"

    def test_extracts_location_and_identifier_headers(self):
        token = self._make_real_style_macaroon(
            before="2030-01-01T00:00:00.000000000Z",
            home="/x",
            activity="LIST",
            ip="203.0.113.5",
        )
        decoded = decode_macaroon(token)
        assert decoded["location"] == "dcache-macaroon"
        assert decoded["identifier"] == "abcdefgh"

    def test_does_not_include_a_raw_dump(self):
        token = self._make_real_style_macaroon(
            before="2030-01-01T00:00:00.000000000Z",
            home="/x",
            activity="LIST",
            ip="203.0.113.5",
        )
        assert "raw" not in decode_macaroon(token)

    def test_expiry_status_from_cid_prefixed_line(self):
        before = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 3600))
        token = self._make_real_style_macaroon(
            before=before, home="/x", activity="LIST", ip="203.0.113.5"
        )
        assert TokenAuth(token).expiry_status().startswith("valid")


class TestFormatDuration:
    def test_seconds_only(self):
        assert format_duration(45) == "45s"

    def test_minutes_and_seconds(self):
        assert format_duration(125) == "2m 5s"

    def test_hours_minutes_seconds(self):
        assert format_duration(3661) == "1h 1m 1s"

    def test_days(self):
        assert format_duration(90000) == "1d 1h 0s"


class TestDescribeExpiry:
    """describe_expiry() is informational only — it must never raise,
    even for an already-expired token (unlike validate_token())."""

    def test_valid_token(self):
        result = describe_expiry(int(time.time()) + 3600)
        assert result.startswith("valid, expires in")

    def test_expired_token(self):
        result = describe_expiry(int(time.time()) - 100)
        assert result.startswith("expired")
        assert "ago" in result

    def test_missing_expiry(self):
        assert describe_expiry(None) == "unknown (no expiration field found)"

    def test_long_expired_does_not_raise(self):
        describe_expiry(0)


class TestTokenAuthExpiryStatus:
    def test_valid_jwt(self, make_jwt_token):
        token = make_jwt_token(exp_offset=3600)
        assert TokenAuth(token).expiry_status().startswith("valid")

    def test_expired_jwt_does_not_raise(self, make_jwt_token):
        token = make_jwt_token(exp_offset=-100)
        assert TokenAuth(token).expiry_status().startswith("expired")

    def test_valid_macaroon(self, make_macaroon_token):
        before = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 3600))
        token = make_macaroon_token(before=before)
        assert TokenAuth(token).expiry_status().startswith("valid")

    def test_expired_macaroon_does_not_raise(self, make_macaroon_token):
        before = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 100))
        token = make_macaroon_token(before=before)
        assert TokenAuth(token).expiry_status().startswith("expired")


def _fake_response(text: str, url: str = "https://example.org") -> httpx.Response:
    """Build an httpx.Response with a request attached, so
    raise_for_status() works, the way it does on a real response."""
    return httpx.Response(200, text=text, request=httpx.Request("GET", url))


class TestGetPublicIp:
    def test_returns_first_successful_result(self):
        with patch("ada.auth.httpx.get", return_value=_fake_response("203.0.113.5")) as mock_get:
            assert get_public_ip(4) == "203.0.113.5"
            mock_get.assert_called_once()

    def test_falls_through_to_next_service_on_error(self):
        def side_effect(url, timeout=None):
            if "ipify" in url:
                raise httpx.ConnectError("boom")
            return _fake_response("203.0.113.9", url)

        with patch("ada.auth.httpx.get", side_effect=side_effect):
            assert get_public_ip(4) == "203.0.113.9"

    def test_returns_none_when_all_services_fail(self):
        with patch("ada.auth.httpx.get", side_effect=httpx.ConnectError("boom")):
            assert get_public_ip(4) is None

    def test_ignores_wrong_address_family(self):
        # If a service unexpectedly returns an IPv6 address for an
        # IPv4 lookup, it must not be accepted as a match.
        with patch("ada.auth.httpx.get", return_value=_fake_response("2001:db8::1")):
            assert get_public_ip(4) is None


class TestCheckIpCaveat:
    def test_empty_caveat(self):
        assert "no IP caveat" in check_ip_caveat("")

    def test_unparseable_caveat(self):
        assert "could not parse" in check_ip_caveat("not-an-ip")

    def test_matching_ipv4(self):
        with patch("ada.auth.get_public_ip", side_effect=lambda v: "203.0.113.5" if v == 4 else None):
            result = check_ip_caveat("203.0.113.0/24")
        assert "IPv4 (203.0.113.5) matches" in result

    def test_non_matching_ipv4(self):
        with patch("ada.auth.get_public_ip", side_effect=lambda v: "198.51.100.5" if v == 4 else None):
            result = check_ip_caveat("203.0.113.0/24")
        assert "IPv4 (198.51.100.5) does not match" in result

    def test_ip_undeterminable(self):
        with patch("ada.auth.get_public_ip", return_value=None):
            assert "could not determine" in check_ip_caveat("203.0.113.0/24")

    def test_comma_separated_networks(self):
        with patch("ada.auth.get_public_ip", side_effect=lambda v: "203.0.113.5" if v == 4 else None):
            result = check_ip_caveat("10.0.0.0/8,203.0.113.0/24")
        assert "matches" in result

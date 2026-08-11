"""Tests for ada.tokens module."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ada.exceptions import AdaAuthError, AdaTokenExpiredError, AdaTokenPermissionError
from ada.auth import ProxyAuth, decode_jwt, decode_jwt_payload, is_jwt, validate_token
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

"""Tests for ada.tokens module."""

from __future__ import annotations

import pytest

from ada.exceptions import AdaAuthError, AdaTokenExpiredError, AdaTokenPermissionError
from ada.auth import decode_jwt, decode_jwt_payload, is_jwt, validate_token


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

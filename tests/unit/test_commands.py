"""Tests for CLI command output."""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import patch

from ada.auth import TokenAuth
from ada.cli import commands


def _run_viewtoken(token: str, capsys) -> str:
    auth = TokenAuth(token)
    client = SimpleNamespace(auth=auth, view_token=auth.view_token)
    with patch("ada.cli.commands.__get_client__") as get_client, \
         patch("ada.auth.get_public_ip", return_value=None):
        get_client.return_value.__enter__.return_value = client
        commands.viewtoken(SimpleNamespace(minimal=False))
    return capsys.readouterr().out


class TestViewtokenIpCaveat:
    def test_jwt_has_no_ip_caveat_line(self, make_jwt_token, capsys):
        # OIDC tokens never have IP caveats, so don't warn about it (#69).
        out = _run_viewtoken(make_jwt_token(), capsys)
        assert "IP caveat" not in out

    def test_macaroon_without_ip_caveat_warns(self, make_macaroon_token, capsys):
        before = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 3600))
        out = _run_viewtoken(make_macaroon_token(before=before), capsys)
        assert "IP caveat: empty. Warning: use IP caveats" in out

    def test_macaroon_with_ip_caveat_is_checked(self, make_macaroon_token, capsys):
        before = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 3600))
        out = _run_viewtoken(make_macaroon_token(before=before, ip="203.0.113.0/24"), capsys)
        assert "IP caveat: could not determine" in out
        assert "Warning" not in out

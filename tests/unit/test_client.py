"""Tests for AdaClient's configuration precedence.

The full documented precedence chain (high to low) is:

    CLI/constructor arguments <- environment variables <- ~/.ada/ada.conf
    <- /etc/ada.conf <- <package>/etc/ada.conf

ada.config.load_config() covers the file+env part of that chain
(see test_conf.py::TestConfigCascade). Here we cover the top of the
chain: AdaClient's constructor arguments must win over everything
load_config() already resolved.
"""
from __future__ import annotations

import os

from ada.client import AdaClient


class TestConfigPrecedence:
    def test_constructor_api_overrides_env_and_file(self, tmp_path, monkeypatch, make_jwt_token):
        conf = tmp_path / "ada.conf"
        conf.write_text("api=https://file.example.org/api/v1\n")
        os.chmod(conf, 0o600)
        monkeypatch.setenv("ada_api", "https://env.example.org/api/v1")

        tokenfile = tmp_path / "token"
        tokenfile.write_text(make_jwt_token() + "\n")
        os.chmod(tokenfile, 0o600)

        with AdaClient(
            api="https://constructor.example.org/api/v1",
            tokenfile=str(tokenfile),
            config_paths=[str(conf)],
        ) as client:
            assert client.config.api == "https://constructor.example.org/api/v1"

    def test_env_var_used_when_no_constructor_api_given(self, tmp_path, monkeypatch, make_jwt_token):
        conf = tmp_path / "ada.conf"
        conf.write_text("api=https://file.example.org/api/v1\n")
        os.chmod(conf, 0o600)
        monkeypatch.setenv("ada_api", "https://env.example.org/api/v1")

        tokenfile = tmp_path / "token"
        tokenfile.write_text(make_jwt_token() + "\n")
        os.chmod(tokenfile, 0o600)

        with AdaClient(tokenfile=str(tokenfile), config_paths=[str(conf)]) as client:
            assert client.config.api == "https://env.example.org/api/v1"

    def test_file_used_when_no_constructor_or_env_api_given(self, tmp_path, make_jwt_token):
        conf = tmp_path / "ada.conf"
        conf.write_text("api=https://file.example.org/api/v1\n")
        os.chmod(conf, 0o600)

        tokenfile = tmp_path / "token"
        tokenfile.write_text(make_jwt_token() + "\n")
        os.chmod(tokenfile, 0o600)

        with AdaClient(tokenfile=str(tokenfile), config_paths=[str(conf)]) as client:
            assert client.config.api == "https://file.example.org/api/v1"

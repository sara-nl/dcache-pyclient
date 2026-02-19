"""Tests for ada.config module."""

from __future__ import annotations

import os
import tempfile

import pytest

from ada.config import AdaConfig, load_config, _load_config_file
from ada.exceptions import AdaConfigError


class TestAdaConfig:
    def test_validate_valid_api(self):
        config = AdaConfig(api="https://host.example.com/api/v1")
        config.validate()
        assert config.api == "https://host.example.com/api/v1"

    def test_validate_strips_trailing_slash(self):
        config = AdaConfig(api="https://host.example.com/api/v1/")
        config.validate()
        assert config.api == "https://host.example.com/api/v1"

    def test_validate_rejects_http(self):
        config = AdaConfig(api="http://insecure.example.com/api/v1")
        with pytest.raises(AdaConfigError, match="https://"):
            config.validate()


class TestLoadConfigFile:
    def test_load_key_value(self, tmp_path):
        conf_file = tmp_path / "ada.conf"
        conf_file.write_text("api=https://test.example.com/api/v1\ndebug=true\n")
        os.chmod(conf_file, 0o600)

        config = AdaConfig()
        _load_config_file(config, conf_file)
        assert config.api == "https://test.example.com/api/v1"
        assert config.debug is True

    def test_skip_comments(self, tmp_path):
        conf_file = tmp_path / "ada.conf"
        conf_file.write_text("# comment\napi=https://host/api/v1\n")
        os.chmod(conf_file, 0o600)

        config = AdaConfig()
        _load_config_file(config, conf_file)
        assert config.api == "https://host/api/v1"

    def test_skip_bash_arrays(self, tmp_path):
        conf_file = tmp_path / "ada.conf"
        conf_file.write_text(
            "api=https://host/api/v1\n"
            "curl_options_common=(\n"
            "  -H \"accept: application/json\"\n"
            ")\n"
        )
        os.chmod(conf_file, 0o600)

        config = AdaConfig()
        _load_config_file(config, conf_file)
        assert config.api == "https://host/api/v1"

    def test_quoted_values(self, tmp_path):
        conf_file = tmp_path / "ada.conf"
        conf_file.write_text('api="https://host/api/v1"\n')
        os.chmod(conf_file, 0o600)

        config = AdaConfig()
        _load_config_file(config, conf_file)
        assert config.api == "https://host/api/v1"


class TestLoadConfig:
    def test_env_var_override(self, tmp_path, monkeypatch):
        conf_file = tmp_path / "ada.conf"
        conf_file.write_text("api=https://from-file/api/v1\n")
        os.chmod(conf_file, 0o600)

        monkeypatch.setenv("ada_api", "https://from-env/api/v1")

        config = load_config(paths=[str(conf_file)])
        assert config.api == "https://from-env/api/v1"

    def test_missing_files_ignored(self):
        config = load_config(paths=["/nonexistent/path/ada.conf"])
        assert config.api == ""
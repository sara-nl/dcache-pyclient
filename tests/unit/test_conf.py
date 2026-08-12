"""Tests for ada.config module."""

from __future__ import annotations

import os

import pytest

from ada.config import AdaConfig, load_config, _default_config_paths, _load_config_file
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


class TestConfigCascade:
    """Full file+env precedence chain:

        env vars <- ~/.ada/ada.conf <- /etc/ada.conf <- bundled default

    ``paths`` is always given highest-precedence first, matching
    ``_default_config_paths()``.
    """

    def test_files_cascade_lowest_precedence_first(self, tmp_path):
        """A higher-precedence file only overrides the keys it sets;
        anything it leaves unset falls through to a lower-precedence file."""
        bundled = tmp_path / "bundled.conf"
        bundled.write_text(
            "api=https://bundled.example.org/api/v1\n"
            "igtf=false\n"
            "channel_timeout=100\n"
        )
        system = tmp_path / "system.conf"
        system.write_text("api=https://system.example.org/api/v1\ndebug=true\n")
        user = tmp_path / "user.conf"
        user.write_text("tokenfile=/home/user/token\n")
        for f in (bundled, system, user):
            os.chmod(f, 0o600)

        config = load_config(paths=[str(user), str(system), str(bundled)])

        assert config.api == "https://system.example.org/api/v1"  # system > bundled; user doesn't set it
        assert config.igtf is False  # only bundled sets it
        assert config.channel_timeout == 100  # only bundled sets it
        assert config.debug is True  # only system sets it
        assert config.tokenfile == "/home/user/token"  # only user sets it

    def test_higher_precedence_file_wins_on_conflict(self, tmp_path):
        low = tmp_path / "low.conf"
        low.write_text("api=https://low.example.org/api/v1\n")
        high = tmp_path / "high.conf"
        high.write_text("api=https://high.example.org/api/v1\n")
        for f in (low, high):
            os.chmod(f, 0o600)

        config = load_config(paths=[str(high), str(low)])
        assert config.api == "https://high.example.org/api/v1"

    def test_missing_file_in_chain_is_skipped(self, tmp_path):
        existing = tmp_path / "existing.conf"
        existing.write_text("api=https://existing.example.org/api/v1\n")
        os.chmod(existing, 0o600)

        config = load_config(paths=[str(tmp_path / "missing.conf"), str(existing)])
        assert config.api == "https://existing.example.org/api/v1"

    def test_env_var_overrides_all_files(self, tmp_path, monkeypatch):
        bundled = tmp_path / "bundled.conf"
        bundled.write_text("api=https://bundled.example.org/api/v1\n")
        system = tmp_path / "system.conf"
        system.write_text("api=https://system.example.org/api/v1\n")
        user = tmp_path / "user.conf"
        user.write_text("api=https://user.example.org/api/v1\n")
        for f in (bundled, system, user):
            os.chmod(f, 0o600)
        monkeypatch.setenv("ada_api", "https://env.example.org/api/v1")

        config = load_config(paths=[str(user), str(system), str(bundled)])
        assert config.api == "https://env.example.org/api/v1"

    def test_env_var_only_overrides_the_key_it_sets(self, tmp_path, monkeypatch):
        conf = tmp_path / "ada.conf"
        conf.write_text("api=https://file.example.org/api/v1\ntokenfile=/from/file\n")
        os.chmod(conf, 0o600)
        monkeypatch.setenv("ada_tokenfile", "/from/env")

        config = load_config(paths=[str(conf)])
        assert config.api == "https://file.example.org/api/v1"  # untouched by env
        assert config.tokenfile == "/from/env"


class TestDefaultConfigPaths:
    def test_order_matches_documented_precedence(self):
        """~/.ada/ada.conf > /etc/ada.conf > bundled <package>/etc/ada.conf."""
        paths = _default_config_paths()
        assert paths[0] == "~/.ada/ada.conf"
        assert paths[1] == "/etc/ada.conf"
        assert paths[2].endswith("/etc/ada.conf")
        assert paths[2] not in ("~/.ada/ada.conf", "/etc/ada.conf")

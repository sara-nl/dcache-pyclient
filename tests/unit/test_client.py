"""Tests for AdaClient setup."""

import pytest

from ada.client import AdaClient
from ada.exceptions import AdaConfigError


def test_no_api_gives_clear_error(tmp_path, monkeypatch):
    monkeypatch.delenv("ada_api", raising=False)
    empty_conf = tmp_path / "ada.conf"
    empty_conf.write_text("")
    with pytest.raises(AdaConfigError, match="No dCache API address specified"):
        AdaClient(token="x", config_paths=[str(empty_conf)])

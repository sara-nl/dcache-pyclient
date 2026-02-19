"""Shared fixtures for ADA tests."""

from __future__ import annotations

import base64
import json
import time
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_api():
    """Mocked DcacheAPI for unit testing services."""
    from ada.api import DcacheAPI

    return MagicMock(spec=DcacheAPI)


@pytest.fixture
def sample_dir_response():
    """Sample directory listing response from the dCache API."""
    return {
        "fileType": "DIR",
        "pnfsId": "00001234",
        "children": [
            {
                "fileName": "file1.txt",
                "fileType": "REGULAR",
                "size": 1024,
                "mtime": 1700000000000,
                "pnfsId": "00005678",
                "fileLocality": "ONLINE",
                "currentQos": "disk",
            },
            {
                "fileName": "file2.dat",
                "fileType": "REGULAR",
                "size": 2048000,
                "mtime": 1700100000000,
                "pnfsId": "0000ABCD",
                "fileLocality": "NEARLINE",
                "currentQos": "tape",
            },
            {
                "fileName": "subdir",
                "fileType": "DIR",
            },
        ],
    }


@pytest.fixture
def sample_file_response():
    """Sample file stat response from the dCache API."""
    return {
        "fileName": "testfile.dat",
        "fileType": "REGULAR",
        "size": 4096,
        "mtime": 1700000000000,
        "pnfsId": "0000FFFF",
        "fileLocality": "ONLINE_AND_NEARLINE",
        "currentQos": "disk+tape",
        "labels": ["important", "processed"],
        "extendedAttributes": {"project": "spider", "batch": "42"},
        "checksums": [
            {"type": "ADLER32", "value": "abc12345"},
            {"type": "MD5_TYPE", "value": "d41d8cd98f00b204e9800998ecf8427e"},
        ],
    }


@pytest.fixture
def make_jwt_token():
    """Factory fixture to create JWT tokens for testing."""

    def _make(exp_offset: int = 3600, scope: str = "storage.read storage.write") -> str:
        header = base64.urlsafe_b64encode(
            json.dumps({"alg": "HS256", "typ": "JWT"}).encode()
        ).decode().rstrip("=")
        payload = base64.urlsafe_b64encode(
            json.dumps(
                {
                    "exp": int(time.time()) + exp_offset,
                    "iat": int(time.time()),
                    "sub": "testuser",
                    "scope": scope,
                }
            ).encode()
        ).decode().rstrip("=")
        sig = base64.urlsafe_b64encode(b"fakesignature").decode().rstrip("=")
        return f"{header}.{payload}.{sig}"

    return _make
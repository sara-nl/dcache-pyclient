"""Shared fixtures for ADA tests."""

from __future__ import annotations

import os
import base64
import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ada.api import DcacheAPI
from ada.client import AdaClient



# Fixtures for unit tests

@pytest.fixture
def mock_api():
    """Mocked DcacheAPI for unit testing services."""
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


# Fixtures for integration tests

# define custom addoption with pytest_addoption hook
def pytest_addoption(parser):
  parser.addoption(
    '--target-env',
    action='store',
    default='dev.json',
    help='Path to the target environment config file')
  

# Read input jsonfile for integration test
@pytest.fixture
def target_env(request):
  config_path = request.config.getoption('--target-env')
  with open(config_path) as config_file:
    config_data = json.load(config_file)
  return config_data


@pytest.fixture
def ada_client(target_env):
    client =  AdaClient(api=target_env['api'], tokenfile=target_env['tokenfile'])
    return client

# Create a 1GB file
def generate_file(size_in_mb, file_name):
  mega_byte = 1_000_000
  with open(file_name, 'wb') as file:
    file.write(os.urandom(size_in_mb*mega_byte))

# Function to initialize setup
@pytest.fixture
def setup_data(target_env):
    # Create test data and transfer to dCache:

    tmpfile = "tmpfile"
    testfile = f"{target_env['homedir']}/{target_env['diskdir']}/integration_test/1GBfile"
    generate_file(1000, tmpfile)

    # Get remote name for rclone
    remote = Path(target_env['tokenfile']).stem

    print("\nSetting up resources...")
    print(f"rclone -P copyto --config={target_env['tokenfile']} {tmpfile} {remote}:{testfile}")
    os.system(f"rclone -P copyto --config={target_env['tokenfile']} {tmpfile} {remote}:{testfile}")
    #os.system("rclone -P copyto --config=${token_file} ${PWD}/$testfile  $(basename "${token_file%.*}"):/${disk_path}/${dirname}/${testfile}") 

    yield testfile  # Provide the test filename to the test

    # Teardown: Clean up resources (if any) after the test
    print("\nTearing down resources...")

    # delete local test data

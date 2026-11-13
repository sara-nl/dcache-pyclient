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


###########################
# Fixtures for unit tests #
###########################

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


@pytest.fixture
def make_macaroon_token():
    """Factory fixture to create fake Macaroon tokens for testing.

    Close enough to the real binary format for decode_macaroon_raw():
    4 junk header bytes, followed by newline-separated caveat lines.
    """

    def _make(before: str = "", activity: str = "", ip: str = "") -> str:
        lines = []
        if before:
            lines.append(f"before:{before}")
        if activity:
            lines.append(f"activity:{activity}")
        if ip:
            lines.append(f"ip:{ip}")
        lines.append("signature abcdef1234567890")
        text = "\n".join(lines)
        return base64.b64encode(b"\x00\x00\x00\x00" + text.encode()).decode()

    return _make

##################################
# Fixtures for integration tests #
##################################

@pytest.fixture(scope="session")
def testnames():
    """Initializes and shares a dictionary across all tests."""
    
    # Define test files and directories    
    return {"tmpdir": "integration_tmp", "testfile": "1MBfile", "subdir": "subdir"}


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
  config_data['homedir'] = config_data['homedir'].rstrip('/')
  config_data['testdir'] = config_data['testdir'].rstrip('/')
  return config_data


@pytest.fixture
def ada_client(target_env):
    client =  AdaClient(api=target_env['api'], tokenfile=target_env['tokenfile'])
    return client


@pytest.fixture
def raw_api_get(ada_client, target_env):
    """GET from the dCache API directly, bypassing ADA's services.

    To check ADA's results against what dCache itself returns, e.g. so a
    bug that makes ADA return nothing isn't mistaken for "nothing there".
    Only ADA's credentials and TLS settings are reused.

    Returns a function ``get(endpoint, params=None)`` that returns
    ``(status_code, json_or_None)``.
    """
    import httpx
    from ada.api import build_ssl_kwargs

    auth = ada_client.auth
    client = httpx.Client(timeout=30.0, **build_ssl_kwargs(auth, True))

    def get(endpoint, params=None):
        response = client.get(
            f"{target_env['api']}/{endpoint}",
            params=params,
            headers={**auth.headers(), "Accept": "application/json"},
        )
        body = response.json() if response.status_code == 200 else None
        return response.status_code, body

    yield get
    client.close()

# Create a 1GB file
def generate_file(size_in_mb, file_name):
  mega_byte = 1_000
  with open(file_name, 'wb') as file:
    file.write(os.urandom(size_in_mb*mega_byte))


# Function to initialize test data on dCache
@pytest.fixture
def setup_data(target_env, tmp_path, testnames, ada_client):
    """ Setup: Create test data and transfer to dCache """

    # Temporary folder on dCache should not already exists, as it will be deleted at end of test:
    testfolder = f"{target_env['homedir']}/{target_env['testdir']}/{testnames['tmpdir']}"
    if ada_client.namespace.is_dir(testfolder):
       pytest.exit(f"Temporary testfolder {testfolder} already exists on dCache. Stopping tests.")

    # tmp_path fixture provides a temporary directory unique to each test function.
    tmpfile = tmp_path / "tmpfile"
    dcachefile = f"{target_env['homedir']}/{target_env['testdir']}/{testnames['tmpdir']}/{testnames['testfile']}"
    generate_file(1000, tmpfile)

    # Get remote name for rclone
    remote = Path(target_env['tokenfile']).stem

    print("\nSetting up resources...")
    print(f"rclone -P copyto --config={target_env['tokenfile']} {tmpfile} {remote}:{dcachefile}")
    os.system(f"rclone -P copyto --config={target_env['tokenfile']} {tmpfile} {remote}:{dcachefile}")

    yield dcachefile  # Provide the test filename to the test

    # Teardown: Clean up resources (if any) after the test
    print(f"\nDeleting {testfolder} on dCache ...")

    try:
        # delete temporary test folder on dCache
        ada_client.delete(testfolder, recursive=True, force=True)
    except:
        print(f"Cannot delete {testfolder} on dCache")



@pytest.fixture
def expected_quotas(raw_api_get):
    """The user and group quotas as dCache itself returns them.

    A 404 means that kind of quota is not set. Returns a list of
    ``(quota_type, entry)`` tuples, where entry is the raw JSON object.
    """
    quotas = []
    for quota_type in ("user", "group"):
        status, body = raw_api_get(f"quota/{quota_type}", params={"user": "true"})
        if status == 404:
            continue
        assert status == 200, f"quota/{quota_type}: HTTP {status}"
        quotas.extend((quota_type, entry) for entry in body)
    return quotas


@pytest.fixture
def testdir_path(target_env):
    """The (existing) test directory on dCache."""
    return f"{target_env['homedir']}/{target_env['testdir']}"


@pytest.fixture
def quota_owners(ada_client):
    """Describe whom the user and group quotas apply to, for skip messages.

    dCache lists the primary group first in the ``gids`` of ``/user``.
    """
    me = ada_client.whoami()
    primary_gid = me.gids[0] if me.gids else "?"
    return {
        "user": f"user {me.username} (uid {me.uid})",
        "group": f"primary group of user {me.username} (gid {primary_gid})",
    }

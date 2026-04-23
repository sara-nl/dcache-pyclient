"""Integration tests for ADA CLI:
Put configuration in tests/prod.json and pass to test:
> pytest tests/integration/test_cli.py --target-env tests/prod.json -v
"""

from __future__ import annotations

import os
import subprocess

import pytest


class TestClassSystem:
    """Test system information commands"""

    def test_help(self):
        """Get help"""
        out = subprocess.check_output(["ada-cli", "--help"], text=True)
        assert "usage: ada-cli" in out

    def test_whoami(self, target_env):
        """Authenticate and get userinfo"""
        out = subprocess.check_output(["ada-cli", "--tokenfile", target_env['tokenfile'], "--api", target_env['api'] ,"whoami"], text=True)
        assert "AUTHENTICATED" in out
        assert target_env["user"] in out
        assert target_env["homedir"] in out


class TestClassNamespace:
    """Test namespace commands"""

    def test_mkdir_delete_dir(self, target_env, testnames):
        """Create and delete directory on dCache"""

        # Create directory recursively
        dcache_dir = target_env['homedir'] + '/' + target_env['testdir'] + '/' + testnames['tmpdir'] + '/' + testnames['subdir']
        out = subprocess.check_output(["ada-cli", "--tokenfile", target_env['tokenfile'], "--api", target_env['api'] ,"mkdir", dcache_dir, "--recursive"], text=True)

        assert "created" in out
        # list empty dir
        out = subprocess.check_output(["ada-cli", "--tokenfile", target_env['tokenfile'], "--api", target_env['api'] ,"list", dcache_dir], text=True)
        assert out == ""

        # Delete directory recursively
        dcache_dir = target_env['homedir'] + '/' + target_env['testdir'] + '/' + testnames['tmpdir']
        out = subprocess.check_output(["ada-cli", "--tokenfile", target_env['tokenfile'], "--api", target_env['api'] ,"delete", dcache_dir, "--recursive"], text=True)

        assert "Deleted" in out


    def test_mv_delete_file(self, target_env, setup_data):
        """Move and delete file on dCache"""
        # create testfile on dCache
        dcache_file = setup_data

        # move file on dCache
        tmp_file = dcache_file + '_tmp'
        #out = ada_client.mv(dcache_file, tmp_file )
        out = subprocess.check_output(["ada-cli", "--tokenfile", target_env['tokenfile'], "--api", target_env['api'] ,"mv", dcache_file, tmp_file], text=True)

        assert "moved" in out

        # check if file was moved
        out = subprocess.check_output(["ada-cli", "--tokenfile", target_env['tokenfile'], "--api", target_env['api'] ,"list", tmp_file], text=True)
        assert os.path.basename(tmp_file) in out

        # delete file
        out = subprocess.check_output(["ada-cli", "--tokenfile", target_env['tokenfile'], "--api", target_env['api'] ,"delete", tmp_file], text=True)
        assert "Deleted" in out


    def test_longlist(self, target_env, setup_data, tmp_path):
        """Longlist file(s) on dCache"""

        # create testfile on dCache
        dcache_file = setup_data

        # longlist
        out = subprocess.check_output(["ada-cli", "--tokenfile", target_env['tokenfile'], "--api", target_env['api'] ,"longlist", dcache_file], text=True)
        assert dcache_file in out

        # write file and folder to filelist
        filelist = tmp_path / "file_list"
        with open(filelist, "w", encoding="utf-8") as f:
            f.write(dcache_file + "\n")
            f.write(os.path.dirname(dcache_file))

        out = subprocess.check_output(["ada-cli", "--tokenfile", target_env['tokenfile'], "--api", target_env['api'] ,"longlist", "--from-file", filelist], text=True)
        assert dcache_file in out

        # catch errors when neither path nor from_file are given
        with pytest.raises(subprocess.CalledProcessError):
            subprocess.check_output(["ada-cli", "--tokenfile", target_env['tokenfile'], "--api", target_env['api'] ,"longlist"], text=True)

        # catch errors when both path and from_file are given
        with pytest.raises(subprocess.CalledProcessError):
            subprocess.check_output(["ada-cli", "--tokenfile", target_env['tokenfile'], "--api", target_env['api'] ,"longlist", dcache_file, "--from-file", filelist], text=True)


    def test_checksum(self, target_env, setup_data, tmp_path):
        """Get checksum of file(s) on dCache"""
        # create testfile on dCache
        dcache_file = setup_data

        # checksum
        out = subprocess.check_output(["ada-cli", "--tokenfile", target_env['tokenfile'], "--api", target_env['api'] ,"checksum", dcache_file], text=True)
        assert dcache_file in out

        # write file and folder to filelist
        filelist = tmp_path / "file_list"
        with open(filelist, "w", encoding="utf-8") as f:
            f.write(dcache_file + "\n")
            f.write(os.path.dirname(dcache_file))

        out = subprocess.check_output(["ada-cli", "--tokenfile", target_env['tokenfile'], "--api", target_env['api'] ,"checksum", "--from-file", filelist], text=True)
        assert dcache_file in out

        # catch errors when neither path nor from_file are given
        with pytest.raises(subprocess.CalledProcessError):
            subprocess.check_output(["ada-cli", "--tokenfile", target_env['tokenfile'], "--api", target_env['api'] ,"checksum"], text=True)

        # catch errors when both path and from_file are given
        with pytest.raises(subprocess.CalledProcessError):
            subprocess.check_output(["ada-cli", "--tokenfile", target_env['tokenfile'], "--api", target_env['api'] ,"checksum", dcache_file, "--from-file", filelist], text=True)


class TestStaging:
    """Test (un)staging commands"""

    def test_stage_unstage(self, target_env, setup_data):
        """Stage and unstage file on dCache"""
        # create testfile on dCache
        dcache_file = setup_data

        # stage
        out = subprocess.check_output(["ada-cli", "--tokenfile", target_env['tokenfile'], "--api", target_env['api'] ,"stage", dcache_file], text=True)
        assert "Stage request submitted" in out
        assert "Request URL" in out
        assert "Targets: 1 file" in out

        # unstage
        out = subprocess.check_output(["ada-cli", "--tokenfile", target_env['tokenfile'], "--api", target_env['api'] ,"unstage", dcache_file], text=True)
        assert "Unstage request submitted" in out
        assert "Request URL" in out
        assert "Targets: 1 file" in out


    def test_stage_unstage_from_file(self, target_env, setup_data, tmp_path):
        """Stage and unstage file on dCache from filelist"""
        # create testfile on dCache
        dcache_file = setup_data
        filelist = tmp_path / "file_list"
        with open(filelist, "w", encoding="utf-8") as f:
            f.write(dcache_file + "\n")
            f.write(os.path.dirname(dcache_file))

        # stage
        out = subprocess.check_output(["ada-cli", "--tokenfile", target_env['tokenfile'], "--api", target_env['api'] ,"stage", "--from-file", filelist], text=True)
        assert "Stage request submitted" in out
        assert "Request URL" in out
        assert "Targets: 2 file(s)" in out

        # unstage
        out = subprocess.check_output(["ada-cli", "--tokenfile", target_env['tokenfile'], "--api", target_env['api'] ,"unstage", "--from-file", filelist], text=True)
        assert "Unstage request submitted" in out
        assert "Request URL" in out
        assert "Targets: 2 file(s)" in out


    def test_stage_unstage_errors(self, target_env, setup_data, tmp_path):
        """Stage and unstage file on dCache with errors"""
        # create testfile on dCache
        dcache_file = setup_data
        filelist = tmp_path / "file_list"
        with open(filelist, "w", encoding="utf-8") as f:
            f.write(dcache_file + "\n")
            f.write(os.path.dirname(dcache_file))

        # stage
        # Catch error when both path and from_file are given
        with pytest.raises(subprocess.CalledProcessError):
            subprocess.check_output(["ada-cli", "--tokenfile", target_env['tokenfile'], "--api", target_env['api'] ,"stage", dcache_file, "--from-file", filelist], text=True)
        # Catch error when neither path nor from_file are given
        with pytest.raises(subprocess.CalledProcessError):
            subprocess.check_output(["ada-cli", "--tokenfile", target_env['tokenfile'], "--api", target_env['api'], "stage"], text=True)

        # unstage
        # Catch error when both path and from_file are given
        with pytest.raises(subprocess.CalledProcessError):
            subprocess.check_output(["ada-cli", "--tokenfile", target_env['tokenfile'], "--api", target_env['api'], "unstage", dcache_file, "--from-file", filelist], text=True)
        # Catch error when neither path nor from_file are given
        with pytest.raises(subprocess.CalledProcessError):
            subprocess.check_output(["ada-cli", "--tokenfile", target_env['tokenfile'], "--api", target_env['api'],"unstage"], text=True)

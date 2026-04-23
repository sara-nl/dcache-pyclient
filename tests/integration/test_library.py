"""Integration tests for ADA library:
Put configuration in tests/prod.json and pass to test:
> pytest tests/integration/test_library.py --target-env tests/prod.json -v
"""

from __future__ import annotations

import os
import pytest

from ada.exceptions import AdaValidationError


class TestClassSystem:
    """Test system information commands"""

    def test_whoami(self, ada_client, target_env):
        """Authenticate and get userinfo"""
        userinfo = ada_client.whoami()
        assert 'AUTHENTICATED' == userinfo.status
        assert target_env['user'] == userinfo.username
        assert target_env['homedir'] == userinfo.home


class TestClassNamespace:
    """Test namespace commands"""

    def test_mkdir_delete(self, ada_client, target_env, testnames):
        """Create and delete directory on dCache"""

        # Create directory recursively        
        dcache_dir = target_env['homedir'] + '/' + target_env['testdir'] + '/' + testnames['tmpdir'] + '/' + testnames['subdir']
        out = ada_client.mkdir(dcache_dir, recursive=True)
        assert out == 'created'

        # list empty dir
        out = ada_client.list(dcache_dir)
        assert out == []

        # Delete directory recursively
        out = ada_client.delete(target_env['homedir'] + '/' + target_env['testdir'] + '/' + testnames['tmpdir'], recursive=True)
        assert out is None


    def test_mv_delete_file(self, ada_client, setup_data):
        """Move and delete file on dCache"""

        # create testfile on dCache
        dcache_file = setup_data

        # move file on dCache
        tmp_file = dcache_file + '_tmp'
        out = ada_client.mv(dcache_file, tmp_file )
        assert out == 'moved'

        # check if file was moved
        out = ada_client.list(tmp_file)
        assert out == [os.path.basename(tmp_file)]

        # delete file
        out = ada_client.delete(tmp_file)
        assert out is None


    def test_longlist(self, ada_client, setup_data, tmp_path):
        """Longlist file(s) on dCache"""

        # create testfile on dCache
        dcache_file = setup_data

        out = ada_client.longlist(dcache_file)
        assert out[0].path == dcache_file

        # # write file and folder to filelist
        # filelist = tmp_path / "file_list"
        # with open(filelist, "w", encoding="utf-8") as f:
        #     f.write(dcache_file + "\n")
        #     f.write(os.path.dirname(dcache_file))

        # out = ada_client.longlist(from_file=filelist)
        # print("out", out)
        # assert out[0].path == dcache_file
        # assert 1==0


    def test_checksum(self, ada_client, setup_data, tmp_path):
        """Get checksum of file(s) on dCache"""
    
        # create testfile on dCache
        dcache_file = setup_data

        # checksum
        out = ada_client.checksum(dcache_file)
        assert out[0].path == dcache_file

        # write file and folder to filelist
        filelist = tmp_path / "file_list"
        with open(filelist, "w", encoding="utf-8") as f:
            f.write(dcache_file + "\n")
            f.write(os.path.dirname(dcache_file))

        out = ada_client.checksum(from_file=filelist)
        assert out[0].path == dcache_file

        # Catch error when both path and from_file are given        
        with pytest.raises(AdaValidationError):
            ada_client.checksum(dcache_file, from_file=filelist)
        # Catch error when neither path nor from_file are given
        with pytest.raises(AdaValidationError):
            ada_client.checksum()


class TestStaging:

    def test_stage_unstage(self, ada_client, setup_data):
        """Stage and unstage file on dCache"""
        # create testfile on dCache
        dcache_file = setup_data

        # stage
        out = ada_client.stage(dcache_file)
        assert out.activity == 'PIN'
        assert out.targets[0] ==  dcache_file
        assert out.request_id != ""

        # unstage
        out = ada_client.unstage(dcache_file)
        assert out.activity == 'UNPIN'
        assert out.targets[0] ==  dcache_file
        assert out.request_id != ""


    def test_stage_unstage_from_file(self, ada_client, setup_data, tmp_path):
        """Stage and unstage file on dCache from filelist"""
        # create testfile on dCache
        dcache_file = setup_data
        filelist = tmp_path / "file_list"
        with open(filelist, "w") as f:
            f.write(dcache_file + "\n")
            f.write(os.path.dirname(dcache_file))

        # stage
        out = ada_client.stage(from_file=filelist)
        assert out.activity == 'PIN'
        assert out.targets[0] ==  dcache_file
        assert out.request_id != ""

        # unstage
        out = ada_client.unstage(from_file=filelist)
        assert out.activity == 'UNPIN'
        assert out.targets[0] ==  dcache_file
        assert out.request_id != ""


    def test_stage_unstage_errors(self, ada_client, setup_data, tmp_path):
        """Stage and unstage file on dCache with errors"""
        # create testfile on dCache
        dcache_file = setup_data
        filelist = tmp_path / "file_list"
        with open(filelist, "w") as f:
            f.write(dcache_file + "\n")
            f.write(os.path.dirname(dcache_file))

        # stage
        # Catch error when both path and from_file are given
        with pytest.raises(AdaValidationError):
            out = ada_client.stage(dcache_file, from_file=filelist)
        # Catch error when neither path nor from_file are given
        with pytest.raises(AdaValidationError):
            out = ada_client.stage()            

        # unstage
        # Catch error when both path and from_file are given        
        with pytest.raises(AdaValidationError):
            out = ada_client.unstage(dcache_file, from_file=filelist)
        # Catch error when neither path nor from_file are given
        with pytest.raises(AdaValidationError):
            out = ada_client.unstage()            


"""Integration tests for ADA library:
Put configuration in tests/prod.json and pass to test:
> pytest tests/integration/test_library.py --target-env tests/prod.json -v
"""

from __future__ import annotations

import os


class TestClassSystem:

    def test_whoami(self, ada_client, target_env):
        userinfo = ada_client.whoami()
        assert 'AUTHENTICATED' == userinfo.status
        assert target_env['user'] == userinfo.username
        assert target_env['homedir'] == userinfo.home


class TestClassNamespace:

    def test_mkdir(self, ada_client, target_env, testnames):
        """Create directory on dCache"""
        dcache_dir = target_env['homedir'] + '/' + target_env['testdir'] + '/' + testnames['tmpdir'] + '/' + testnames['subdir']
        out = ada_client.mkdir(dcache_dir, recursive=True)
        assert out == 'created' 

        # list empty dir
        out = ada_client.list(dcache_dir)
        assert out == []


    def test_delete_dir(self, ada_client, target_env, testnames):
        """Delete directory on dCache"""        
        out = ada_client.delete(target_env['homedir'] + '/' + target_env['testdir'] + '/' + testnames['tmpdir'], recursive=True)     
        assert out == None


    def test_mv(self, ada_client, setup_data):
        """Move file on dCache""" 
        # create testfile on dCache
        dcache_file = setup_data

        # move file on dCache
        tmp_file = dcache_file + '_tmp'
        out = ada_client.mv(dcache_file, tmp_file )
        assert out == 'moved'

        # check if file was moved
        out = ada_client.list(tmp_file)
        assert out == [os.path.basename(tmp_file)]

        #move back
        ada_client.mv(tmp_file, dcache_file)
    

    def test_longlist_checksum_delete(self, ada_client, setup_data):    
        """longlist, checksum and delete file on dCache""" 

        # create testfile on dCache
        dcache_file = setup_data
        
        out = ada_client.longlist(dcache_file)
        assert out[0].path == dcache_file

        # checksum
        out = ada_client.checksum(dcache_file)
        assert out[0].path == dcache_file

        # delete file
        out = ada_client.delete(dcache_file)
        assert out == None


class TestStaging:

    def test_stage_unstage(self, ada_client, setup_data):    

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
"""Tests for ada.services.system module."""

from __future__ import annotations

import pytest


# Define test files and directories
dirname = "integration_test"
testfile = "1GBfile"
testdir = "testdir"
subdir = "subdir"


class TestClassSystem:

    def test_whoami(self, ada_client, target_env):
        userinfo = ada_client.whoami()
        assert 'AUTHENTICATED' == userinfo.status
        assert target_env['user'] == userinfo.username
        assert target_env['homedir'] == userinfo.home


class TestClassNamespace:
    def test_mkdir(self, ada_client, target_env):
        out = ada_client.mkdir(target_env['homedir'] + '/' + target_env['diskdir'] + '/' + dirname + '/' + testdir + '/' + subdir, recursive=True)
        assert out == 'created' 
        # check if dir is created


    def test_delete_dir(self, ada_client, target_env):
        out = ada_client.delete(target_env['homedir'] + '/' + target_env['diskdir'] + '/' + dirname + '/' + testdir, recursive=True)  # no force=True needed?           
        assert out == None
        # check if dir is deleted


    def test_mv(self, ada_client, setup_data):

        # create testfile on dCache
        dcache_file = setup_data

        # move file on dCache
        tmp_file = dcache_file + '_tmp'
        out = ada_client.mv(dcache_file, tmp_file )
        assert out == 'moved'
        # check if file is moved

        # move back
        out = ada_client.mv(tmp_file, dcache_file)
        assert out == 'moved'
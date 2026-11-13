"""Integration tests for ADA library:
Put configuration in tests/prod.json and pass to test:
> pytest tests/integration/test_library.py --target-env tests/prod.json -v
"""

from __future__ import annotations

import os
import pytest

from ada.exceptions import AdaValidationError, AdaAPIError, AdaPathError, AdaNotFoundError
from ada.client import AdaClient


class TestClassAuth:
    """Test system information commands"""

    def test_view_token(self, ada_client, target_env):
        """View token"""
        userinfo = ada_client.view_token()
        assert target_env['homedir'] == userinfo['home']
        # The order of activities depends on how the macaroon was created
        expected = {"DOWNLOAD", "UPLOAD", "DELETE", "MANAGE", "LIST",
                    "READ_METADATA", "UPDATE_METADATA", "STAGE"}
        assert expected == set(userinfo['activity'].split(","))

class TestClassSystem:
    """Test system information commands"""

    def test_whoami(self, ada_client, target_env):
        """Authenticate and get userinfo"""
        userinfo = ada_client.whoami()
        assert 'AUTHENTICATED' == userinfo.status
        assert target_env['user'] == userinfo.username
        assert target_env['homedir'] == userinfo.home


class TestSpace:
    """Test pool group space (#67), checked against the raw API"""

    def test_list_poolgroups(self, ada_client, raw_api_get):
        status, body = raw_api_get("poolgroups")
        assert status == 200
        expected = [item["name"] for item in body]
        assert expected, "dCache reports no pool groups"
        assert ada_client.space() == expected

    def test_poolgroups_for_path(self, ada_client, testdir_path):
        poolgroups = ada_client.poolgroups_for_path(testdir_path)
        assert poolgroups
        assert set(poolgroups) <= set(ada_client.space())

    def test_space_of_poolgroup(self, ada_client, raw_api_get, testdir_path):
        for poolgroup in ada_client.poolgroups_for_path(testdir_path):
            info = ada_client.space(poolgroup)
            status, body = raw_api_get(f"poolgroups/{poolgroup}/space")
            assert status == 200
            # free/precious/removable change all the time, total doesn't
            assert info.total == body["groupSpaceData"]["total"]
            assert info.total > 0
            assert 0 <= info.free <= info.total
            assert info.precious >= 0
            assert info.removable >= 0

    def test_space_errors(self, ada_client, testdir_path, setup_data):
        with pytest.raises(AdaAPIError):
            ada_client.space("no-such-poolgroup-ada-test")
        with pytest.raises(AdaNotFoundError):
            ada_client.poolgroups_for_path(f"{testdir_path}/no-such-dir-ada-test")
        # A file's pool group is not reliable, so only directories are accepted
        with pytest.raises(AdaValidationError):
            ada_client.poolgroups_for_path(setup_data)


class TestQuota:
    """Test quotas (#67), checked against the raw API.

    Which tests run depends on the quotas set on the dCache instance;
    the others are skipped, so the report shows which cases were tested.
    """

    @pytest.mark.parametrize("quota_type", ["user", "group"])
    def test_quota_set(self, ada_client, expected_quotas, quota_owners, quota_type):
        expected = [entry for qtype, entry in expected_quotas if qtype == quota_type]
        if not expected:
            pytest.skip(f"No quota set on {quota_owners[quota_type]}")

        quotas = [q for q in ada_client.quota() if q.quota_type == quota_type]
        assert [(q.id, q.custodial_limit, q.replica_limit) for q in quotas] == [
            (entry["id"], entry.get("custodialLimit"), entry.get("replicaLimit"))
            for entry in expected
        ]
        me = ada_client.whoami()
        for q in quotas:
            assert q.id == me.uid if quota_type == "user" else q.id in me.gids
            # Usage can change between the two requests, so don't compare it
            assert q.custodial >= 0
            assert q.replica >= 0

    def test_no_quota_set(self, ada_client, expected_quotas, quota_owners):
        if expected_quotas:
            pytest.skip("Quota is set on " + " and on ".join(
                quota_owners[qtype] for qtype in dict.fromkeys(qtype for qtype, _ in expected_quotas)
            ))
        assert ada_client.quota() == []


class TestClassNamespace:
    """Test namespace commands"""

    def test_stat(self, ada_client, setup_data):
        """Move and delete file on dCache"""

        # create testfile on dCache
        dcache_file = setup_data

        # stat file
        out = ada_client.stat(dcache_file)
        assert out['storageInfo']['map']['path'] == dcache_file

        # stat directory
        out = ada_client.stat(os.path.dirname(dcache_file))
        assert out['storageInfo']['map']['path'] == os.path.dirname(dcache_file)


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
        out = ada_client.delete(target_env['homedir'] + '/' + target_env['testdir'] + '/' + testnames['tmpdir'], recursive=True, force=True)
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

        # write file and folder to filelist
        filelist = tmp_path / "file_list"
        with open(filelist, "w", encoding="utf-8") as f:
            f.write(dcache_file + "\n")
            f.write(os.path.dirname(dcache_file))

        out = ada_client.longlist(from_file=filelist)
        assert out[0].path == dcache_file

        # Catch error when both path and from_file are given        
        with pytest.raises(AdaValidationError):
            ada_client.longlist(dcache_file, from_file=filelist)
        # Catch error when neither path nor from_file are given
        with pytest.raises(AdaValidationError):
            ada_client.longlist()


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


    def test_label(self, ada_client, setup_data):
        """Set label on a file on dCache"""

        # create testfile on dCache
        dcache_file = setup_data

        # set label
        out = ada_client.set_label(dcache_file, "testlabel")
        assert "testlabel" in out

        # find label
        out = ada_client.find_label(os.path.dirname(dcache_file), "test")
        assert dcache_file in out[0]

        # list label
        out = ada_client.list_labels(dcache_file)
        assert "testlabel" in out[0]

        # remove label
        out = ada_client.remove_label(dcache_file, all_labels=True)
        assert "All labels removed from" in out

        # remove non-existing label
        with pytest.raises(AdaAPIError):
            ada_client.remove_label(dcache_file, "testlabel")

        # check if label is removed
        out = ada_client.list_labels(dcache_file)
        assert not out


    def test_xattr(self, ada_client, setup_data):
        """Set extended attribute on a file on dCache"""

        # create testfile on dCache
        dcache_file = setup_data

        # set extended attribute
        attributes = {"test": "attribute"}
        out = ada_client.set_xattr(dcache_file, attributes)
        assert "Extended attributes set" in out

        # find extended attribute
        out = ada_client.find_xattr(os.path.dirname(dcache_file), key="test", regex="attr")
        assert attributes in out[0]

        # list extended attribute
        out = ada_client.list_xattr(dcache_file)
        assert attributes.items() <= out.items()

        # remove extended attribute
        out = ada_client.remove_xattr(dcache_file, all_keys=True)
        assert "All extended attributes removed from" in out

        # remove non-existing extended attribute
        with pytest.raises(AdaAPIError):
            ada_client.remove_xattr(dcache_file, [(dcache_file, attributes)])

        # check if extended attribute is removed
        out = ada_client.list_xattr(dcache_file)
        assert not out


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


class TestConfigPrecedence:
    def test_constructor_api_overrides_env_and_file(self, target_env, tmp_path, monkeypatch):
        conf = tmp_path / "ada.conf"
        conf.write_text("api=https://file.example.org/api/v1\n")
        os.chmod(conf, 0o600)
        monkeypatch.setenv("ada_api", "https://env.example.org/api/v1")
        tokenfile = target_env['tokenfile']

        with AdaClient(
            api="https://constructor.example.org/api/v1",
            tokenfile=str(tokenfile),
            config_paths=[str(conf)],
        ) as client:
            assert client.config.api == "https://constructor.example.org/api/v1"


    def test_env_var_used_when_no_constructor_api_given(self, target_env, tmp_path, monkeypatch):
        conf = tmp_path / "ada.conf"
        conf.write_text("api=https://file.example.org/api/v1\n")
        os.chmod(conf, 0o600)
        monkeypatch.setenv("ada_api", "https://env.example.org/api/v1")
        tokenfile = target_env['tokenfile']

        with AdaClient(tokenfile=str(tokenfile), config_paths=[str(conf)]) as client:
            assert client.config.api == "https://env.example.org/api/v1"


    def test_file_used_when_no_constructor_or_env_api_given(self, target_env, tmp_path):
        conf = tmp_path / "ada.conf"
        conf.write_text("api=https://file.example.org/api/v1\n")
        os.chmod(conf, 0o600)
        tokenfile = target_env['tokenfile']

        with AdaClient(tokenfile=str(tokenfile), config_paths=[str(conf)]) as client:
            assert client.config.api == "https://file.example.org/api/v1"


class TestTransfer:
    def test_donwload_upload(self, ada_client, setup_data, target_env, tmp_path):
        """Stage and unstage file on dCache"""
        # create testfile on dCache
        dcache_file = setup_data

        # write file and folder to filelist
        local_file = tmp_path / "local_file"

        # download
        out = ada_client.download(dcache_file, local_file)
        assert out.status=="downloaded"

        # download with webdav door and into folder 
        out = ada_client.download(target_env["webdav"] + dcache_file, tmp_path)
        assert out.status=="downloaded"

        # raise error when file already exists loally 
        with pytest.raises(AdaPathError):
            out = ada_client.download(dcache_file, local_file)

        # verify checksum by downloading again with --verify-checksum
        out = ada_client.download(dcache_file, local_file, verify_checksum=True) 
        assert out.status=="already-verified"

        # upload
        tmp_file = dcache_file + '_tmp'
        out = ada_client.upload(local_file, tmp_file)
        assert out.status=="uploaded"

        # raise error when file already exists on dCache 
        with pytest.raises(AdaPathError):
            out = ada_client.upload(local_file, tmp_file)

        # verify checksum by downloading again with --verify-checksum
        out = ada_client.upload(local_file, tmp_file, verify_checksum=True)
        assert out.status=="already-verified"

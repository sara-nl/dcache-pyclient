"""Tests for ada.services.system module."""

from __future__ import annotations

import pytest

from ada.exceptions import AdaNotFoundError, AdaValidationError
from ada.models import QuotaInfo, SpaceInfo
from ada.services.system import SystemService


class TestSpace:
    def test_no_poolgroup_lists_names(self, mock_api):
        mock_api.get.return_value = [
            {"name": "generic_writediskpools", "pools": []},
            {"name": "generic_writetapepools", "pools": []},
        ]
        svc = SystemService(mock_api)

        result = svc.space()

        assert result == ["generic_writediskpools", "generic_writetapepools"]
        mock_api.get.assert_called_once_with("poolgroups")

    def test_poolgroup_returns_space_info(self, mock_api):
        mock_api.get.return_value = {
            "groupSpaceData": {
                "total": 120946279055360,
                "free": 117247845146952,
                "precious": 0,
                "removable": 0,
            },
            "costDataForPools": {},
        }
        svc = SystemService(mock_api)

        result = svc.space("generic_writediskpools")

        assert result == SpaceInfo(
            total=120946279055360, free=117247845146952, precious=0, removable=0
        )
        mock_api.get.assert_called_once_with("poolgroups/generic_writediskpools/space")

    def test_poolgroup_missing_group_space_data_defaults_to_zero(self, mock_api):
        mock_api.get.return_value = {"costDataForPools": {}}
        svc = SystemService(mock_api)

        result = svc.space("empty_poolgroup")

        assert result == SpaceInfo(total=0, free=0, precious=0, removable=0)


class TestPoolgroupsForPath:
    """Resolves a namespace path to pool group(s) the same way dCache
    itself does: storage class + HSM -> unit -> unit group -> link(s)
    -> pool group(s). Fixture data mirrors real responses observed
    against a live dCache test server."""

    def test_resolves_single_poolgroup(self, mock_api):
        mock_api.get.side_effect = [
            {"fileType": "DIR", "storageClass": "generic:disk", "hsm": "osm"},
            [
                {
                    "name": "generic_disk",
                    "units": ["generic:disk@osm"],
                    "links": ["generic_writedisklink"],
                },
                {
                    "name": "other_group",
                    "units": ["other:unit@osm"],
                    "links": ["other_link"],
                },
            ],
            [
                {"name": "generic_writedisklink", "poolGroups": ["generic_writediskpools"]},
                {"name": "other_link", "poolGroups": ["other_pools"]},
            ],
        ]
        svc = SystemService(mock_api)

        result = svc.poolgroups_for_path("/users/homer/disk")

        assert result == ["generic_writediskpools"]
        assert mock_api.get.call_args_list[0].args[0] == "namespace/%2Fusers%2Fhomer%2Fdisk"

    def test_resolves_multiple_poolgroups(self, mock_api):
        # A tape directory has separate read and write links/pool groups.
        mock_api.get.side_effect = [
            {"fileType": "DIR", "storageClass": "generic:tape", "hsm": "osm"},
            [
                {
                    "name": "generic_tape",
                    "units": ["generic:tape@osm"],
                    "links": ["generic-readtapelink", "generic-writetapelink"],
                },
            ],
            [
                {"name": "generic-readtapelink", "poolGroups": ["generic_readtapepools"]},
                {"name": "generic-writetapelink", "poolGroups": ["generic_writetapepools"]},
            ],
        ]
        svc = SystemService(mock_api)

        result = svc.poolgroups_for_path("/users/homer/tape")

        assert result == ["generic_readtapepools", "generic_writetapepools"]

    def test_missing_storage_class_raises(self, mock_api):
        mock_api.get.return_value = {"fileType": "DIR"}
        svc = SystemService(mock_api)

        with pytest.raises(AdaNotFoundError, match="storage class"):
            svc.poolgroups_for_path("/some/path")

    def test_no_matching_unit_group_raises(self, mock_api):
        mock_api.get.side_effect = [
            {"fileType": "DIR", "storageClass": "generic:disk", "hsm": "osm"},
            [{"name": "other_group", "units": ["other:unit@osm"], "links": ["other_link"]}],
        ]
        svc = SystemService(mock_api)

        with pytest.raises(AdaNotFoundError, match="No link found"):
            svc.poolgroups_for_path("/users/homer/disk")

    def test_no_matching_poolgroup_raises(self, mock_api):
        mock_api.get.side_effect = [
            {"fileType": "DIR", "storageClass": "generic:disk", "hsm": "osm"},
            [
                {
                    "name": "generic_disk",
                    "units": ["generic:disk@osm"],
                    "links": ["generic_writedisklink"],
                }
            ],
            [{"name": "generic_writedisklink", "poolGroups": []}],
        ]
        svc = SystemService(mock_api)

        with pytest.raises(AdaNotFoundError, match="No pool group found"):
            svc.poolgroups_for_path("/users/homer/disk")

    def test_raises_for_a_file_path(self, mock_api):
        # Pool group info for a file is unreliable: a moved file's storage
        # class/HSM updates to match its new directory, but its data stays
        # in the pool group it was originally written to. So only
        # directories are accepted.
        mock_api.get.return_value = {"fileType": "REGULAR", "storageClass": "generic:disk", "hsm": "osm"}
        svc = SystemService(mock_api)

        with pytest.raises(AdaValidationError, match="is a file"):
            svc.poolgroups_for_path("/users/homer/disk/file.txt")
        mock_api.get.assert_called_once()


class TestQuota:
    def test_returns_user_and_group_quota(self, mock_api):
        mock_api.get.side_effect = [
            [
                {
                    "id": 31029,
                    "type": "USER",
                    "custodial": 1084227602,
                    "replica": 1267496085,
                    "custodialLimit": 1000000000000000,
                    "replicaLimit": 2000000000000,
                }
            ],
            [
                {
                    "id": 31040,
                    "type": "GROUP",
                    "custodial": 1084227589,
                    "replica": 1267496085,
                    "custodialLimit": None,
                    "replicaLimit": 1000000000000,
                }
            ],
        ]
        svc = SystemService(mock_api)

        result = svc.quota()

        assert result == [
            QuotaInfo(
                quota_type="user", id=31029, custodial=1084227602,
                custodial_limit=1000000000000000, replica=1267496085,
                replica_limit=2000000000000,
            ),
            QuotaInfo(
                quota_type="group", id=31040, custodial=1084227589,
                custodial_limit=None, replica=1267496085,
                replica_limit=1000000000000,
            ),
        ]
        assert mock_api.get.call_args_list[0].args[0] == "quota/user"
        assert mock_api.get.call_args_list[0].kwargs == {"params": {"user": "true"}}
        assert mock_api.get.call_args_list[1].args[0] == "quota/group"

    def test_404_for_a_quota_type_is_not_an_error(self, mock_api):
        # Bash treats a 404 as "no quota of this type set", not a failure.
        mock_api.get.side_effect = [
            AdaNotFoundError("no user quota"),
            [{"id": 31040, "type": "GROUP", "custodial": 1, "replica": 2,
              "custodialLimit": None, "replicaLimit": None}],
        ]
        svc = SystemService(mock_api)

        result = svc.quota()

        assert len(result) == 1
        assert result[0].quota_type == "group"

    def test_no_quota_at_all_returns_empty_list(self, mock_api):
        mock_api.get.side_effect = AdaNotFoundError("no quota")
        svc = SystemService(mock_api)

        assert svc.quota() == []

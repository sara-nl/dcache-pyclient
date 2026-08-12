"""Tests for ada.services.system module."""

from __future__ import annotations

import pytest

from ada.exceptions import AdaNotFoundError
from ada.models import SpaceInfo
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
            {"storageClass": "generic:disk", "hsm": "osm"},
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

        result = svc.poolgroups_for_path("/users/onno/disk")

        assert result == ["generic_writediskpools"]
        assert mock_api.get.call_args_list[0].args[0] == "namespace/%2Fusers%2Fonno%2Fdisk"

    def test_resolves_multiple_poolgroups(self, mock_api):
        # A tape directory has separate read and write links/pool groups.
        mock_api.get.side_effect = [
            {"storageClass": "generic:tape", "hsm": "osm"},
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

        result = svc.poolgroups_for_path("/users/onno/tape")

        assert result == ["generic_readtapepools", "generic_writetapepools"]

    def test_missing_storage_class_raises(self, mock_api):
        mock_api.get.return_value = {"fileType": "DIR"}
        svc = SystemService(mock_api)

        with pytest.raises(AdaNotFoundError, match="storage class"):
            svc.poolgroups_for_path("/some/path")

    def test_no_matching_unit_group_raises(self, mock_api):
        mock_api.get.side_effect = [
            {"storageClass": "generic:disk", "hsm": "osm"},
            [{"name": "other_group", "units": ["other:unit@osm"], "links": ["other_link"]}],
        ]
        svc = SystemService(mock_api)

        with pytest.raises(AdaNotFoundError, match="No link found"):
            svc.poolgroups_for_path("/users/onno/disk")

    def test_no_matching_poolgroup_raises(self, mock_api):
        mock_api.get.side_effect = [
            {"storageClass": "generic:disk", "hsm": "osm"},
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
            svc.poolgroups_for_path("/users/onno/disk")

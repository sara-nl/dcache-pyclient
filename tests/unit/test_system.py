"""Tests for ada.services.system module."""

from __future__ import annotations

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

"""Tests for tools/thermal_precheck.py.

The thermal check is the bench's pass line, so its arithmetic and the loss it
inherits from the 100 A budget are pinned here.
"""

from __future__ import annotations

from thermal_precheck import (
    DEVICES,
    RTH_JA_DATASHEET,
    RTH_JA_NO_COPPER,
    TJ_MAX_C,
    junction_temp_c,
    max_ambient_c,
    per_device_sr_loss,
    report,
)


def test_eight_devices_split_the_sr_loss():
    assert DEVICES == 8
    assert per_device_sr_loss(8.0) == 1.0


def test_100a_per_device_loss_matches_the_budget():
    data = report()
    assert data["sr_loss_w_100a"] == data["sr_loss_per_device_w_100a"] * DEVICES
    assert 0.85 < data["sr_loss_per_device_w_100a"] < 0.98
    assert data["sr_loss_per_device_w_95a"] < data["sr_loss_per_device_w_100a"]


def test_junction_temperature_and_ambient_are_inverse():
    p = 0.9173
    for rth in (RTH_JA_DATASHEET, RTH_JA_NO_COPPER):
        tj = junction_temp_c(p, 25.0, rth)
        assert tj == 25.0 + p * rth
        assert max_ambient_c(p, rth) == TJ_MAX_C - p * rth


def test_datasheet_copper_area_passes_at_40c_but_not_without_copper():
    data = report()
    by_key = {(row["ambient_c"], row["rth_ja_k_per_w"]): row for row in data["matrix"]}
    assert by_key[(40.0, RTH_JA_DATASHEET)]["passes_tj_125"] is True
    assert by_key[(60.0, RTH_JA_NO_COPPER)]["passes_tj_125"] is False


def test_max_ambient_reports_both_rth_cases():
    data = report()
    assert data["max_ambient_c_100a"]["rth_50_k_per_w"] > data["max_ambient_c_100a"]["rth_80_k_per_w"]
    assert data["status"] == "design estimate, not hardware validated"

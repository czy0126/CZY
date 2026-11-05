"""P0 bench analog findings must not be hidden by a clean KiCad ERC."""
from __future__ import annotations

from dataclasses import replace

import pytest

import d0_analog_preflight as audit
import make_d0_protection_board as board


def test_gate_summing_would_miss_one_gate_parked_at_three_volts():
    result = audit.build()
    g = result["gate_sum"]
    assert g["one_gate_3v_is_reported_off_drivers_low"]
    assert g["one_gate_3v_is_reported_off_drivers_unpowered"]
    assert g["threshold_at_single_gate_drivers_low_v"] == pytest.approx(4.0, abs=0.03)
    assert g["threshold_at_single_gate_drivers_unpowered_v"] == pytest.approx(
        3.1, abs=0.05)
    assert g["reliable_all_ten_off_proven"] is False


def test_all_high_exceeds_comparator_common_mode_if_clamp_does_not_operate():
    result = audit.build()
    g = result["gate_sum"]
    assert g["all_ten_gates_at_12v_unclamped_gsum_v"] == pytest.approx(6.0)
    assert g["all_ten_gates_at_12v_unclamped_gsum_v"] > (
        g["legacy_lm393_vcc_5v_common_mode_upper_v"])


def test_proposed_zener_is_not_qualified_at_its_only_available_current():
    clamp = audit.build()["clamp"]
    assert clamp["part"] == "BZX84C3V0"
    assert clamp["netlist_wiring_as_proposed"]
    assert clamp["datasheet_zener_test_current_ma"] == pytest.approx(5.0)
    assert clamp["available_current_ma_upper_bound_at_ten_12v_gates"] == pytest.approx(0.3)
    assert clamp["available_current_ma_upper_bound_at_ten_12v_gates"] < (
        clamp["datasheet_zener_test_current_ma"])
    assert clamp["published_test_current_reached"] is False
    assert clamp["low_current_clamp_voltage_guaranteed"] is False
    assert clamp["comparator_common_mode_under_all_conditions_proven"] is False


def test_fast_comparator_not_faster_nor_more_sensitive_than_hard():
    path = audit.build()["ct_fast_path"]
    assert path["fast_trip_peak_a_design"] > path["hard_trip_peak_a_design"]
    assert not path["fast_threshold_lower_than_hard"]
    assert path["fast_path_has_filter_delay"] is True
    assert path["maximum_response_time_with_measured_hardware_proven"] is False


def test_an_updated_ti_package_is_not_a_fabrication_authorization():
    result = audit.build()
    assert result["vendor_reference_package_currently_consistent"] is True
    assert result["status"] == "ANALOG_SAFETY_NOT_QUALIFIED"
    assert result["hardware_protection_approved"] is False
    assert result["power_stage_fabrication_approved"] is False
    assert result["requires_independent_hardware_review"] is True


def test_wrong_package_can_never_be_rescued_by_one_shunt_short(monkeypatch):
    original = board.parts
    def bad_parts():
        return [
            replace(part, footprint="Package_TO_SOT_SMD:SOT-23")
            if part.ref == "U2" else part for part in original()
        ]
    monkeypatch.setattr(board, "parts", bad_parts)
    assert audit.build()["vendor_reference_package_currently_consistent"] is False


def test_a_changed_clamp_part_is_not_silently_certified(monkeypatch):
    original = board.parts
    def changed_parts():
        return [
            replace(part, value="UNQUALIFIED CLAMP")
            if part.ref == "D9" else part for part in original()
        ]
    monkeypatch.setattr(board, "parts", changed_parts)
    result = audit.build()
    assert result["clamp"]["netlist_wiring_as_proposed"] is False
    assert result["clamp"]["low_current_clamp_voltage_guaranteed"] is False
    assert result["hardware_protection_approved"] is False


def test_analog_release_cli_fails_closed(tmp_path):
    report = tmp_path / "d0_analog_report.json"
    assert audit.main(["--require-qualified", "--output", str(report)]) == 1
    assert report.is_file()
    assert "ANALOG_SAFETY_NOT_QUALIFIED" in report.read_text(encoding="utf-8")

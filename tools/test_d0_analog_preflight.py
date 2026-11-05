"""P0 bench analog findings must not be hidden by a clean KiCad ERC.

The two defects issue #36 named are now *retired*, not merely reported: the
tests below pin the replacement's arithmetic, pin the fact that it is still not
a qualification, and pin the trapdoors a later edit could reopen (a Zener
creeping back in, a threshold compared across two nodes without the divider
gain, a review that starts claiming hardware evidence).
"""
from __future__ import annotations

from dataclasses import replace

import pytest

import d0_analog_preflight as audit
import make_d0_protection_board as board


# ------------------------------------------------------- P0-1: the max detector
def test_one_gate_at_three_volts_now_reads_more_than_the_reference():
    """The defect was 0.150 V against a 0.200 V reference, i.e. "off"."""
    d = audit.build()["gate_max_detector"]
    assert d["retired_ten_resistor_sum_one_gate_at_3v_v"] == pytest.approx(0.150, abs=1e-3)
    assert d["retired_sum_would_report_that_gate_off"] is True
    assert d["one_gate_at_3v_sense_v"] == pytest.approx(0.6370, abs=1e-4)
    assert d["one_gate_at_3v_multiple_of_reference"] > 3.0
    assert d["detection_is_independent_of_the_other_nine_gates"] is True


def test_the_detector_trips_inside_the_band_where_the_fet_still_conducts():
    d = audit.build()["gate_max_detector"]
    assert d["trip_gate_voltage_v_ideal_diode"] == pytest.approx(0.9419, abs=1e-4)
    assert d["trip_gate_voltage_v_at_asserted_drop"] == pytest.approx(1.2419, abs=1e-4)
    assert d["headroom_to_sr_vgs_th_min_v"] == pytest.approx(
        d["sr_vgs_th_min_v"] - d["trip_gate_voltage_v_at_asserted_drop"])
    assert d["headroom_to_sr_vgs_th_min_v"] > 0


def test_every_gate_has_a_distinct_branch_so_a_channel_cannot_hide():
    d = audit.build()["gate_max_detector"]
    assert d["detector_diodes"] == 10
    assert d["branches_are_distinct"] is True
    assert d["per_channel_bring_up_rows"] == 10
    assert d["one_open_channel_is_invisible_to_an_all_high_test"] is True
    assert d["can_name_the_failing_gate"] is False


# ------------------------------------------------ P0-2: the clamp is a ratio
def test_all_high_stays_inside_the_comparator_range_without_a_zener():
    d = audit.build()["gate_max_detector"]
    assert d["all_ten_gates_at_12v_sense_v"] == pytest.approx(2.6290, abs=1e-4)
    assert d["all_ten_gates_at_15v_sense_v"] == pytest.approx(3.2862, abs=1e-4)
    assert d["all_ten_inside_common_mode_at_12v"] is True
    assert d["all_ten_inside_common_mode_at_15v"] is True
    assert d["gate_rail_at_the_common_mode_bound_v"] > 15.0
    assert d["bound_is_a_resistor_ratio_not_a_knee_voltage"] is True


def test_the_zener_is_gone_and_its_reason_is_still_on_the_record():
    clamp = audit.build()["clamp"]
    assert clamp["part"] is None
    assert clamp["retired_part"] == "BZX84C3V0"
    assert clamp["datasheet_zener_test_current_ma"] == pytest.approx(5.0)
    assert clamp["retired_available_current_ma_upper_bound"] == pytest.approx(0.3, abs=0.01)
    assert clamp["retired_published_test_current_reached"] is False
    assert clamp["replacement_needs_a_current_to_be_bounded"] is False
    assert not [p for p in board.parts() if p.lib == "Device:D_Zener"]


# ---------------------------------------------------- P0-3: two separate claims
def test_fast_is_earlier_and_less_sensitive_in_the_same_record():
    """One divider gain, applied once.  Without it the fast threshold reads
    42.9 A instead of 29.4 A -- a 46 % inflation in the wrong direction."""
    path = audit.build()["ct_fast_path"]
    assert path["fast_trip_peak_a_design"] == pytest.approx(29.39, abs=0.02)
    assert path["hard_trip_peak_a_design"] == pytest.approx(24.23, abs=0.02)
    assert path["fast_threshold_lower_than_hard"] is False
    assert path["fast_is_earlier_measured"] is True
    assert path["fast_delay_us"] < path["hard_delay_us"]
    assert path["maximum_response_time_with_measured_hardware_proven"] is False


# --------------------------------------------------- the review stays a review
def test_an_updated_ti_package_is_not_a_fabrication_authorization():
    result = audit.build()
    assert result["vendor_reference_package_currently_consistent"] is True
    assert result["status"] == "ANALOG_SAFETY_NOT_QUALIFIED"
    assert result["hardware_protection_approved"] is False
    assert result["power_stage_fabrication_approved"] is False
    assert result["requires_independent_hardware_review"] is True


def test_the_review_lists_what_the_arithmetic_cannot_settle():
    d = audit.build()["gate_max_detector"]
    for key in ("residual_vgs_safe_off_threshold_verified_per_fet",
                "diode_drop_over_temperature_verified",
                "lm393_common_mode_limit_verified"):
        assert d[key] is False, key
    text = " ".join(audit.build()["unqualified_prerequisites"])
    for topic in ("bring-up", "VGS", "common-mode", "TL431"):
        assert topic in text, topic


def test_wrong_package_can_never_be_rescued_by_one_shunt_short(monkeypatch):
    original = board.parts
    def bad_parts():
        return [
            replace(part, footprint="Package_TO_SOT_SMD:SOT-23")
            if part.ref == "U2" else part for part in original()
        ]
    monkeypatch.setattr(board, "parts", bad_parts)
    assert audit.build()["vendor_reference_package_currently_consistent"] is False


def test_a_changed_detector_part_is_not_silently_certified(monkeypatch):
    """Swap the detector diode for a plain one and the wiring check must fail --
    the review recomputes from the part table, it does not remember being right."""
    original = board.parts
    def changed_parts():
        return [
            replace(part, lib="Device:D")
            if part.ref == "D9" else part for part in original()
        ]
    monkeypatch.setattr(board, "parts", changed_parts)
    result = audit.build()
    assert result["gate_max_detector"]["wiring_as_designed"] is False
    assert result["gate_max_detector"]["lm393_common_mode_limit_verified"] is False
    assert result["hardware_protection_approved"] is False


def test_analog_release_cli_fails_closed(tmp_path):
    report = tmp_path / "d0_analog_report.json"
    assert audit.main(["--require-qualified", "--output", str(report)]) == 1
    assert report.is_file()
    assert "ANALOG_SAFETY_NOT_QUALIFIED" in report.read_text(encoding="utf-8")

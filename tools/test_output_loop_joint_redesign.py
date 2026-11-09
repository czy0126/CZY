"""Two-pole 100A output topology must count both return contacts and hot copper."""
from __future__ import annotations

import json

import pytest

from output_loop_budget import CONTACTS_TOTAL, loop_resistance, report as baseline_report
from output_loop_joint_redesign import OUTPUT, OPTIONS, evaluate, report


def test_legacy_4_joint_power_loop_is_not_silently_rewritten():
    a = baseline_report()
    assert CONTACTS_TOTAL == 4
    assert a["number_of_current_rails"] == 2
    assert a["total_unverified_joints"] == 4
    assert a["status"] == "CONCEPT_SCREEN_ONLY_NOT_FOR_FAB"
    assert a["cases"][3]["bars_pair_uohm"] == pytest.approx(18.884, abs=0.002)
    original = loop_resistance(30, 2, 25, 50)
    explicit = loop_resistance(30, 2, 25, 50, contact_count=4)
    assert original == explicit


def test_four_unverified_50uohm_contacts_are_mathematically_impossible():
    report_data = report()
    assert report_data["feasibility_deduction"][
        "four_contacts_each_50uohm_exceed_budget_before_copper"]
    assert report_data["feasibility_deduction"][
        "four_contacts_only_joints_uohm_at_50"] == 200
    assert report_data["feasibility_deduction"][
        "max_even_contact_count_at_50uohm_with_30uohm_pcb_reserve"] == 2
    four = evaluate("4j", 4, 50, 2, 15)
    assert four["joint_scenarios_uohm"]["50"]["passes_resistance_arithmetic_only"] is False
    assert four["joint_scenarios_uohm"]["50"]["total_uohm"] > 200


def test_two_contact_integration_creates_arithmetic_headroom_but_not_fab_permission():
    two = evaluate("2j", 2, 50, 2, 15)
    assert two["assumed_counted_contacts_per_pole"] == 1
    assert two["bar_pair_uohm_at_100c"] == pytest.approx(6.798, abs=.002)
    at50 = two["joint_scenarios_uohm"]["50"]
    assert at50["total_uohm"] == pytest.approx(136.798, abs=.003)
    assert at50["power_w_at_100a"] == pytest.approx(1.36798, abs=.0001)
    assert at50["drop_mv_at_100a"] == pytest.approx(13.6798, abs=.001)
    assert at50["margin_to_150uohm"] == pytest.approx(13.202, abs=.003)
    assert at50["passes_resistance_arithmetic_only"] is True
    assert two["geometry_verified"] is False
    assert two["contact_count_verified"] is False
    assert two["hardware_qualified"] is False


def test_a_two_contact_30mm_bar_is_too_close_to_budget_to_claim_robustness():
    two = evaluate("2j_30mm", 2, 30, 2, 25)
    assert two["joint_scenarios_uohm"]["50"]["margin_to_150uohm"] < 1.2
    assert two["joint_scenarios_uohm"]["50"]["passes_resistance_arithmetic_only"]


@pytest.mark.parametrize("bad_count", [-2, -1, 0, 1, 3, 5, True, 2.5])
def test_odd_or_invalid_contact_count_cannot_drop_one_rail(bad_count):
    with pytest.raises(ValueError):
        loop_resistance(30, 2, 25, 50, contact_count=bad_count)


def test_source_bound_concept_report_has_no_fake_native_design_or_measurements():
    out = report()
    assert len(out["candidates"]) == len(OPTIONS)
    assert out["hardware_qualified"] is False
    assert out["fabrication_approved"] is False
    assert out["design_basis_is_internal_not_regulatory_or_measured"]
    assert "enumerate every transition" in out["next_eda_action"]
    assert "Kelvin 4-wire" in out["required_measurement"]
    assert out["status"].endswith("NOT_FOR_FAB")


def test_committed_joint_redesign_snapshot_matches_generator():
    assert OUTPUT.exists()
    assert json.loads(OUTPUT.read_text(encoding="utf-8")) == report()

"""No-cost-ceiling engineering targets are evidence-derived, never vendor approvals."""
from __future__ import annotations
import csv
import json
import pytest
import performance_first_design as perf


def test_cost_does_not_override_height_or_safety():
    j, rows = perf.build()
    assert j["cost_policy"] == "NO_COST_CEILING_PER_USER_DIRECTION"
    assert j["constraints"]["maximum_assembly_height_mm"] == 10.0
    assert j["constraints"]["no_invented_mpn"]
    assert not j["hardware_continuous_rating_approved"]
    assert j["cad"]["fabrication_gate"] == "NOT_FOR_FAB"
    assert j["cad"]["placeholder_count"] == 61
    assert len(rows) == 9
    assert all(row["decision"] == "PENDING" and
               row["supplier_mpn_or_custom_drawing"] == "" and
               row["manufacturer_datasheet_or_signed_drawing"] == "" for row in rows)


def test_high_margin_lr_eliminates_existing_3turn_without_claiming_new_core():
    d = perf.build()[0]["magnetics"]
    assert d["observed_peak_is_solver_prefix"] is True
    assert d["observed_50v_fault_peak_a"] == pytest.approx(101.262657, abs=1e-5)
    assert d["rfq_current_a"] > 121.0
    assert d["design_flux_limit_t"] == pytest.approx(0.248)
    assert d["existing_three_turn_worst_b_t"] > d["design_flux_limit_t"]
    assert d["three_turn_min_ae_mm2"] > 175
    assert d["preferred_three_turn_amin_mm2"] > d["three_turn_min_ae_mm2"]
    assert d["preferred_three_turn_worst_b_t"] < d["design_flux_limit_t"]
    assert d["optional_four_turn_worst_b_t"] < d["design_flux_limit_t"]


def test_cout_rfq_does_not_promote_unverified_2p5v_ideal_esr():
    j, _ = perf.build()
    c = j["capacitors"]
    assert c["existing_nominal_v_rating_v"] == 2.5
    assert c["output_vrating_min_v"] >= 4.0
    assert c["output_vrating_preferred_v"] >= 6.3
    assert c["output_ripple_target_rms_a"] >= 78.7
    assert c["output_bank_c_min_mf"] >= 7.05
    assert c["output_esr_including_copper_target_mohm"] == pytest.approx(
        c["output_copper_and_joint_budget_mohm"] +
        c["output_cap_bank_esr_budget_mohm"])


def test_every_capacitor_rfq_quotes_the_sizing_point_not_the_rated_one():
    """The RFQ asks suppliers for a rating; asking at the rated point understates it.

    This file is the supplier ask, and it still quoted 52.48 / 5.32 / 9.45 A --
    the rated 100 A points -- after ``cout_bank``, ``cin_bank`` and ``cr_bank``
    had each moved to the 120 A overload.  Those three numbers are 6.8 %, 19.6 %
    and 18.8 % low, so the ask has to follow the bank JSONs rather than the
    rated-point artefacts they replaced.
    """
    _, rows = perf.build()
    by_group = {r["group"]: r for r in rows}
    cout = json.loads((perf.ROOT / "design/v3/bom/cout_bank.json")
                      .read_text(encoding="utf-8"))["requirements"]
    cin = json.loads((perf.ROOT / "design/v3/bom/cin_bank.json")
                     .read_text(encoding="utf-8"))["requirements"]
    cr = json.loads((perf.ROOT / "design/v3/bom/cr_bank.json")
                    .read_text(encoding="utf-8"))["requirements"]
    passive = json.loads((perf.ROOT / "design/v3/bom/passive_requirements.json")
                         .read_text(encoding="utf-8"))
    cases = [
        ("Cout_bank_high_voltage", cout["irms_a"],
         passive["cout_ripple"]["ripple_rms_a"]),
        ("Cin_high_ripple", cin["bridge_ac_rms_a_at_worst_measured_load"],
         cin["bridge_ac_rms_a_at_100a"]),
        ("Cr_resonant_low_loss", cr["irms_a"],
         cr["sizing_points"]["rated_100a"]["i_rms_a"]),
    ]
    for group, worst, rated in cases:
        assert worst > rated, group
        evidence = by_group[group]["evidence"]
        assert f"{worst:.2f}A" in evidence, group
        assert f"({rated:.2f}A at the rated 100A" in evidence, group


def test_the_cout_rfq_ripple_reaches_the_bank_requirement():
    j, rows = perf.build()
    sizing = json.loads((perf.ROOT / "design/v3/bom/cout_bank.json")
                        .read_text(encoding="utf-8"))["requirements"]["irms_a"]
    c = j["capacitors"]
    assert c["output_model_ripple_rms_a"] == pytest.approx(sizing, abs=1e-6)
    assert c["output_model_ripple_rms_rated_a"] < c["output_model_ripple_rms_a"]
    assert c["output_ripple_target_rms_a"] == pytest.approx(
        sizing * perf.COUT_RIPPLE_MARGIN, abs=1e-6)
    cout_row = next(r for r in rows if r["group"] == "Cout_bank_high_voltage")
    assert f"{sizing * perf.COUT_RIPPLE_MARGIN:.2f}Arms" in cout_row["unlimited_cost_request"]


def test_sr_observation_is_low_current_late_latch_not_safe_shutdown():
    p = perf.build()[0]["sr_protection"]
    assert p["48v_A_gates_high_at_end"] == ["1A", "2A", "3A", "4A"]
    assert 1.3 < p["48v_final_high_interval_max_current_a"] < 1.5
    assert p["screening_current_a"] > 375
    assert p["status"] == "HARD_FAULT_INTERLOCK_DESIGN_REQUIRED_NOT_TESTED"


def test_rfqs_and_json_regenerate_exactly():
    expected, rows = perf.build()
    assert json.loads(perf.OUT_JSON.read_text(encoding="utf-8")) == expected
    assert perf.OUT_CSV.read_text(encoding="utf-8") == perf.to_csv(rows)
    with perf.OUT_CSV.open(encoding="utf-8", newline="") as stream:
        supplied = list(csv.DictReader(stream))
    assert len(supplied) == 9
    assert "Lr_custom_flat_magnetic" in {r["group"] for r in supplied}

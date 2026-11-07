"""Independent checks of the T2 hold-energy ODE, not a thermal qualification."""
from __future__ import annotations

import json

import pytest

import reg_hold
import reg_hold_energy as e


def test_the_anchors_are_the_vendored_datasheet_values():
    assert e.IREG_ANCHORS_A == {"short_circuit_13ma": 13e-3,
                                "current_limit_95ma": 95e-3}
    assert e.IREG_ANCHORS_A["current_limit_95ma"] == pytest.approx(reg_hold.IREGLIM_MAX_A)
    assert e.IREG_ANCHORS_A["short_circuit_13ma"] == pytest.approx(reg_hold.IREG_SC_MAX_A)


def test_the_released_capacitor_energy_matches_its_closed_form():
    row = e.finite_capacitor(anchor_a=95e-3)
    expected = 0.5 * e.C_SR_F * (row["v0_v"] ** 2 - row["v_final_v"] ** 2)
    assert row["energy"]["cap_released_j"] == pytest.approx(expected)


def test_the_energy_split_closes():
    for anchor in e.IREG_ANCHORS_A.values():
        energy = e.finite_capacitor(anchor_a=anchor)["energy"]
        parts = (energy["q41_r44_j"] + energy["ucc24624_j"]
                 + energy["r57_discharge_j"] + energy["r58_bleed_j"])
        assert parts == pytest.approx(energy["cap_released_j"], rel=0.02)


def test_the_capacitor_energy_is_independent_of_the_foldback_anchor():
    slow = e.finite_capacitor(anchor_a=13e-3)
    fast = e.finite_capacitor(anchor_a=95e-3)
    # The capacitor releases the same energy either way; only the split moves.
    assert slow["energy"]["cap_released_j"] == pytest.approx(
        fast["energy"]["cap_released_j"], rel=1e-4)
    # At the slow anchor R57 competes for a larger share, so the UCC absorbs less.
    assert fast["energy"]["ucc24624_j"] > slow["energy"]["ucc24624_j"]
    assert slow["energy"]["r57_discharge_j"] > fast["energy"]["r57_discharge_j"]
    # The power is not energy: the fast anchor burns much more watts.
    assert fast["ucc_average_w"] > 3 * slow["ucc_average_w"]


def test_a_larger_anchor_discharges_faster():
    assert e.finite_capacitor(anchor_a=95e-3)["hold_s"] < \
        e.finite_capacitor(anchor_a=13e-3)["hold_s"]


def test_the_regulator_stops_above_the_uvlo_floor():
    row = e.finite_capacitor(anchor_a=95e-3)
    assert row["v_final_v"] >= e.V_UVLO_VDD_V - 1e-3
    assert e.V_UVLO_VDD_V == pytest.approx(3.63 + 0.5)


def test_the_input_delay_energy_is_the_product_of_power_and_delay():
    row = e.input_delay(delay_s=13.36e-6, anchor_a=95e-3, supply_v=15.75)
    assert row["ucc_j"] == pytest.approx(row["ucc_w"] * 13.36e-6)
    assert row["v_reg_v"] == pytest.approx(95e-3 * e.R_CROWBAR_TOTAL_OHM)
    assert row["cap_energy_untouched"] is True


def test_the_continuous_source_is_reported_as_unbounded_and_anchor_dependent():
    low = e.continuous_injection(24.0, 13e-3)
    high = e.continuous_injection(24.0, 95e-3)
    assert low["energy_unbounded"] is True
    assert high["energy_unbounded"] is True
    assert low["within_tj_max"] is True
    assert high["within_tj_max"] is False
    assert high["ucc_w"] > 5 * low["ucc_w"]


def test_tj_uses_the_vendored_thermal_resistance():
    row = e.continuous_injection(24.0, 13e-3, ambient_c=50.0)
    assert row["rise_k"] == pytest.approx(row["ucc_w"] * reg_hold.RTH_JA_C_PER_W)
    assert row["tj_c"] == pytest.approx(50.0 + row["rise_k"])


def test_the_repetition_limit_shrinks_with_a_hotter_ambient():
    energy = e.finite_capacitor(anchor_a=95e-3)["energy"]["ucc24624_j"]
    assert e.repetition_limit_ms(energy, 25.0) < e.repetition_limit_ms(energy, 50.0)
    assert e.repetition_limit_ms(energy, 25.0) > 0


def test_the_report_separates_the_three_scenarios_and_cannot_approve_hardware():
    data = e.report()
    assert data["measured"] is False
    assert data["hardware_qualified"] is False
    assert set(data["results"]) >= {"finite_capacitor", "input_switch_delay",
                                    "continuous_injection", "repetition_limit_ms"}
    assert data["decision"]["continuous_source_conclusion"].startswith("NOT closed")
    assert "do not increase R57" in data["decision"]["required_change"]
    assert data["datasheet_anchors"]["foldback_curve_specified"] is False
    assert data["open"]


def test_the_json_on_disk_is_the_module_output():
    data = json.loads(e.JSON_PATH.read_text(encoding="utf-8"))
    assert data == e.report()

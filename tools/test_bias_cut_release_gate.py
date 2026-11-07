"""Fail-closed protection release tests; synthetic alternatives are NOT hardware evidence."""
from __future__ import annotations

import math
import pytest

import bias_cut_release_gate as gate


def test_current_pcb_and_two_spice_decks_have_same_resistor_and_load():
    inp = gate.design_inputs()
    assert inp["r57_ohm"] == pytest.approx(47)
    assert inp["r57_continuous_rating_w"] == pytest.approx(.25)
    assert inp["c_bank_f"] == pytest.approx(11.1e-6)
    assert inp["normal_vdd_v"] == pytest.approx(15)
    assert inp["reverse_source_v"] == pytest.approx(18)
    assert inp["always_on_during_fault_and_reverse"] is True


def test_47_ohm_resistor_presents_steady_reverse_heat_not_just_a_capacitor_pulse():
    inp = gate.design_inputs()
    env = gate.envelope(
        resistance_ohm=inp["r57_ohm"], capacitance_f=inp["c_bank_f"],
        start_v=inp["normal_vdd_v"], threshold_v=inp["discharge_to_v"],
        reverse_v=inp["reverse_source_v"],
        continuous_w=inp["r57_continuous_rating_w"],
        deadline_s=inp["max_discharge_time_s"])
    assert env["ideal_resistor_power_at_reverse_w"] == pytest.approx(324 / 47)
    assert env["time_to_threshold_s"] == pytest.approx(
        47 * 11.1e-6 * math.log(15 / 3.63))
    assert .7e-3 < env["time_to_threshold_s"] < .8e-3
    assert env["thermal_overrating_factor_at_reverse"] > 25
    assert env["fast_discharge_at_current_r"] is True
    assert env["within_continuous_rating_at_current_r"] is False


def test_no_single_always_on_quarter_watt_resistor_meets_both_requirements():
    inp = gate.design_inputs()
    env = gate.envelope(
        resistance_ohm=47, capacitance_f=11.1e-6,
        start_v=15, threshold_v=3.63,
        reverse_v=18, continuous_w=.25, deadline_s=.001)
    assert 60 < env["r_discharge_max_ohm"] < 70
    assert env["r_continuous_power_min_ohm"] == pytest.approx(1296)
    assert env["incompatible_single_resistor_goals"] is True
    # A 2.2-kohm part could run much cooler but cannot meet the trip timing.
    cool = gate.envelope(
        resistance_ohm=2200, capacitance_f=11.1e-6,
        start_v=15, threshold_v=3.63,
        reverse_v=18, continuous_w=.25, deadline_s=.001)
    assert cool["within_continuous_rating_at_current_r"] is True
    assert cool["fast_discharge_at_current_r"] is False
    assert cool["time_to_threshold_s"] > .030


def test_release_block_remains_even_if_logic_simulation_passes():
    report = gate.assess()
    assert report["status"] == "BLOCKED_NOT_FOR_FAB"
    assert report["simulator_checks_pass"] is True
    assert report["fab_release"] is False
    assert report["hardware_qualified"] is False
    assert report["envelope"]["incompatible_single_resistor_goals"] is True
    assert len(report["blocks"]) >= 4
    assert any("inrush" in x for x in report["blocks"])
    assert any("R57" in x for x in report["blocks"])
    assert any("16V" in x for x in report["blocks"])
    assert report["reverse_mismatch_hypothetical_only"] is True


@pytest.mark.parametrize("inputs", [
    (0, 11.1e-6, 15, 3.63, 18, .25, .001),
    (47, -1, 15, 3.63, 18, .25, .001),
    (47, 11.1e-6, 3.63, 3.63, 18, .25, .001),
    (47, 11.1e-6, 15, 3.63, 18, 0, .001),
])
def test_bad_or_nonphysical_requirements_never_produce_release_numbers(inputs):
    with pytest.raises(ValueError):
        gate.envelope(
            resistance_ohm=inputs[0], capacitance_f=inputs[1],
            start_v=inputs[2], threshold_v=inputs[3],
            reverse_v=inputs[4], continuous_w=inputs[5],
            deadline_s=inputs[6])


def test_release_required_command_refuses_current_unqualified_circuit(monkeypatch):
    monkeypatch.setattr("sys.argv", ["bias_cut_release_gate.py", "--require-release"])
    assert gate.main() == 2

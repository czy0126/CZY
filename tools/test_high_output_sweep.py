"""Boundary tests for the high-output *candidate* sweep."""
from __future__ import annotations

import pytest

import high_output_sweep as hs


def test_never_conflates_approximation_with_a_verified_rating():
    out = hs.sweep()
    assert out["status"] == "SCENARIO_ONLY_NOT_HARDWARE_OR_LTSPICE"
    assert len(out["rows"]) == 18
    assert all(x["source"] == "LOCAL_LINEAR_SENSITIVITY_NOT_SIMULATED"
               and x["rating_approved"] is False for x in out["rows"])


def test_higher_path_resistance_burns_more_power_and_drops_voltage():
    out = hs.sweep()
    rows = [x for x in out["rows"] if x["vin_v"] == 48.0 and x["iout_a"] == 120.0]
    assert len(rows) == 3
    assert rows[0]["v_load_est_v"] > rows[1]["v_load_est_v"] > rows[2]["v_load_est_v"]
    assert rows[0]["p_output_path_est_w"] < rows[1]["p_output_path_est_w"] < rows[2]["p_output_path_est_w"]
    assert rows[0]["i_per_sr_group_if_balanced_a"] == 30


def test_increasing_current_does_not_magically_eliminate_fixed_ratio_droop():
    a = hs.sweep()["rows"]
    base = next(x for x in a if x["vin_v"] == 48.0 and x["iout_a"] == 100
                and x["path_resistance_mohm"] == 0.15)
    high = next(x for x in a if x["vin_v"] == 48.0 and x["iout_a"] == 120
                and x["path_resistance_mohm"] == 0.15)
    assert base["v_load_est_v"] > high["v_load_est_v"]
    assert base["p_load_est_w"] < high["p_load_est_w"]
    assert high["loss_factor_pure_i2r_vs_base"] > 1.4


def test_input_raise_is_an_ideal_ratio_only_not_a_claim_of_regulation():
    rows = hs.sweep()["rows"]
    a = next(x for x in rows if x["vin_v"] == 48 and x["iout_a"] == 100 and x["path_resistance_mohm"] == 0.15)
    b = next(x for x in rows if x["vin_v"] == 50 and x["iout_a"] == 100 and x["path_resistance_mohm"] == 0.15)
    assert b["v_converter_est_v"] - a["v_converter_est_v"] == pytest.approx(2/24, abs=1e-4)
    assert all("NOT_SIMULATED" in x["source"] for x in rows)


@pytest.mark.parametrize("vin,current,path", [(0,100,0.00015), (48,0,0.00015), (48,110,-1e-4), (60,100,0)])
def test_invalid_inputs_rejected(vin,current,path):
    with pytest.raises(ValueError):
        hs.calc(vin,current,path,{"iout_from_v_a":100,"vout_avg_v":1.887},0.0011)

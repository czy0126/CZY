"""Scientific no-claim gates for 48V/2V thin liquid cooled higher-current DCX."""
import json
import math
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
import d1_lane_a_cooled_thin_frontier as m

def test_frozen_source_and_generated_evidence_replay():
    d=m.evaluate()
    assert d["status"].startswith("NOVELTY_AND_THERMAL_ENVELOPE")
    assert m.canon_sha(m.PREV)==m.PREV_CANON_SHA
    s=(ROOT/"hardware/dcx_main/g2/d1_lane_a_liquid_cooled_novelty_tradeoff_20261115_NOT_FOR_FAB.json").read_text("utf8")
    assert json.loads(s)==d

def test_current_efficiency_and_plate_inclusive_density():
    d=m.evaluate()
    cases={x["output_current_a"]:x for x in d["initial_low_profile_geom_and_current_cases"]}
    assert sorted(cases)==[200,400,500,600,800]
    c=cases[600]
    assert c["output_power_w"]==1200
    assert c["module_plus_coldplate_total_height_mm"]==8.0
    assert c["module_only_bbox_cm3"]==4.125
    assert c["coolplate_included_bbox_cm3"]==6.0
    assert math.isclose(c["conditional_module_only_density_w_in3"],4767.1,abs_tol=.05)
    assert math.isclose(c["conditional_coldplate_included_density_w_in3"],3277.4,abs_tol=.05)
    assert c["efficiency_heat_cooling_scenarios"][1]["conditional_electrical_loss_w"]==63.158
    assert c["efficiency_heat_cooling_scenarios"][0]["conditional_electrical_loss_w"]>90
    assert not c["same_full_enclosure_contains_magnetics_drivers_sr_capacitors_terminals_validated"]

def test_400a_and_800a_physics_loss_and_comparison_not_oversold():
    d=m.evaluate(); cs={x["output_current_a"]:x for x in d["initial_low_profile_geom_and_current_cases"]}
    assert cs[400]["output_pair_hot_resistance_scenarios"][1]["pair_I2R_loss_w"]==3.2
    assert cs[800]["output_pair_hot_resistance_scenarios"][1]["pair_I2R_loss_w"]==12.8
    assert cs[800]["module_plus_coldplate_total_height_mm"]>8
    b=d["benchmark_evidence_not_comparable_without_matching_conditions"]
    ref=next(x for x in b if x["vout"]==2)
    assert ref["iout_a"]==800 and ref["full_load_efficiency"]==.898
    assert abs(ref["published_density_w_in3"]-1570.4)<.001
    assert "verify" in ref["density_boundary"]

def test_bulk_coolant_temperature_is_not_hotspot():
    d=m.evaluate()
    s=next(x for x in d["initial_low_profile_geom_and_current_cases"] if x["output_current_a"]==600)
    perf=s["efficiency_heat_cooling_scenarios"][1]
    fluids={c["flow_lpm"]:c for c in perf["coolant_bulk_and_pump_nominal_20kPa"]}
    assert 0.9<fluids[1.]["liquid_water_nominal_temp_rise_k"]<1.
    assert 0.25<fluids[3.]["liquid_water_nominal_temp_rise_k"]<.4
    assert fluids[3.]["external_pump_electric_w_at_25pct_assumed"]==4
    assert all(c["fluid_bulk_rise_NOT_component_hotspot"] for c in fluids.values())
    assert s["real_cfd_temperature_and_pressure_verified"] is False

def test_copper_output_thermal_constraint_and_alternative_thickness():
    d=m.evaluate(); metal=d["two_rail_hot_copper_dc_examples"]
    assert metal[0]["each_rail_copper_thickness_mm"]==.07
    assert metal[0]["pair_copper_hot_P_w_DC_ideal"]>50
    assert metal[2]["each_rail_copper_thickness_mm"]==.8
    assert 4<metal[2]["pair_copper_hot_P_w_DC_ideal"]<6
    assert all(not x["contact_via_spreading_and_AC_losses_included"] for x in metal)

def test_novelty_ablation_groups_and_physical_state():
    d=m.evaluate()
    assert [x["group"] for x in d["comparison_A_B_C_D_design_of_experiments"]]==list("ABCD")
    assert len(d["novelty_hypotheses_not_unpublished_claims"])==3
    assert d["engineering_state"]["new_physical_PCB_completed"] is False
    assert d["engineering_state"]["microchannel_CFD_completed"] is False
    assert d["engineering_state"]["coolant_inlet_to_junction_Rtheta_measured"] is False
    assert d["coolplate_cross_section_policy"]["leak_pressure_and_dielectric_test_done"] is False
    assert d["system_spec"]["total_module_plus_coldplate_height_target_mm_max"]==8.

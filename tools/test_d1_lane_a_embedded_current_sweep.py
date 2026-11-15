"""Avoid geometric density hype: source-locked real V17 / embedded Lr and no fake success."""
import json, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
import d1_lane_a_embedded_current_sweep as m

def test_source_locked_embedded_winding_and_report_stable():
    d=m.evaluate()
    assert d["schema"]=="d1_embedded_winding_current_scaling/1"
    assert d["buried_winding_proof_existing_Lr_only"]["original_embedded_Lr_rms_at_100A_output_a"]>9
    assert d["buried_winding_proof_existing_Lr_only"]["minimum_parallel_ideal_vias_for_one_20_microohm_interlayer_transition"]>=60
    assert m.main(["--check"]) is None

def test_current_scaling_density_arithmetic_not_prototype():
    d=m.evaluate()
    cases=d["current_points_100_to_500A"]
    assert [c["Iout_a"] for c in cases]==[100,150,200,300,400,500]
    assert [c["cells"] for c in cases]==[2,3,4,6,8,10]
    assert all(c["secondary_cell_target_avg_a"]==50 for c in cases)
    c300=next(c for c in cases if c["Iout_a"]==300)
    assert c300["Pout_w"]==600
    assert c300["hypothetical_envelope_cm3"]==2.4
    assert c300["conditional_density_w_in3"]==4096.8
    assert c300["component_packability_confirmed"] is False
    assert c300["coldplate_continuous_heat_path_verified"] is False
    assert d["manufacturable_pcb_finished"] is False

def test_200a_and_400a_critical_loss_grows_quadratically():
    d=m.evaluate()
    c={x["Iout_a"]:x for x in d["current_points_100_to_500A"]}
    for i in (200,300,400):
        r=c[i]
        assert r["copper_output_pair_budget"][0]["pair_hot_resistance_microohm"]==50
        assert r["copper_output_pair_budget"][0]["conditional_loop_loss_w"]==round(i*i*50e-6,3)
    assert c[400]["copper_output_pair_budget"][0]["conditional_loop_loss_w"]==8
    assert c[300]["copper_output_pair_budget"][0]["conditional_loop_loss_w"]==4.5
    assert c[300]["full_load_loss_scenarios"][1]["conditional_total_loss_w"]==18.557
    assert c[400]["full_load_loss_scenarios"][1]["conditional_total_loss_w"]==24.742

def test_output_voltage_ratio_is_not_falsely_validated():
    d=m.evaluate()
    assert all(c["native_dcx_24to1_dc_ratio_unverified"] for c in d["current_points_100_to_500A"])
    assert "half/full bridge" in d["research_requirements"]["effective_24_1_ratio"]
    assert d["full_fem_done_for_this_200_300_400A_architecture"] is False
    assert d["prototype_efficiency_or_density_measured"] is False

def test_copper_skin_depth_and_buried_core_distinction():
    d=m.evaluate()
    assert d["copper_skin_depth_20c_um"]["1000kHz"]<d["copper_skin_depth_20c_um"]["200kHz"]
    assert d["ferrite_core_completely_embedded_inside_laminate"]["status"].startswith("HIGH_RISK")
    assert "LITHOGRAPHIC_COPPER" in d["winding_embedded_in_pcb_feasibility"]["type"]

def test_stackup_geometry_bounds_and_alt6mm_300a():
    d=m.evaluate()
    rows={x["copper_layers"]:x for x in d["theoretical_unqualified_stackup_geometry_bounds"]}
    assert rows[12]["minimum_theoretical_board_build_mm"]==1.72
    assert rows[16]["minimum_theoretical_board_build_mm"]==2.32
    assert rows[24]["minimum_theoretical_board_build_mm"]==3.52
    assert rows[36]["minimum_theoretical_board_build_mm"]==5.32
    assert rows[36]["fits_inside_entire_4mm_box_alone"] is False
    c=next(x for x in d["current_points_100_to_500A"] if x["Iout_a"]==300)
    alt=next(x for x in c["alternative_5_6_8mm_research_envelopes"]
             if x["bounding_mm"]==[24,17,6])
    assert alt["volume_cm3"]==2.448
    assert alt["conditional_density_w_in3"]>4000
    assert alt["actual_pcb_placement_or_ferrite_fit_verified"] is False

def test_research_article_full_load_vs_peak_same_point_not_conflated():
    s=m.evaluate()["published_sources_operating_points_not_equivalent"]
    side=next(x for x in s if x["doi"]=="10.3390/en19092049")
    assert (side["vin_v"],side["vout_v"],side["current_a"],side["power_w"])==(60,6,140,840)
    assert side["full_load_efficiency"]==.975
    assert any(x["vin_v"]==48 and x["current_a"]==300 and x["full_load_efficiency"]<.86 for x in s)
    assert len(s)>=6

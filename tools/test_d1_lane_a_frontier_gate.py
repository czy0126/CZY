"""Frontier challenge must fail closed until actual compact physical hardware exists."""
import json
import math
from pathlib import Path

HERE=Path(__file__).resolve().parents[1]
REPORT=HERE/"hardware/dcx_main/g2/d1_lane_a_frontier_feasibility_20261115_NOT_FOR_FAB.json"
d=json.loads(REPORT.read_text("utf8"))

def test_real_v17_geometry_and_missing_power_path():
    p=d["existing_legacy_verification_platform"]
    assert p["board_mm"]==[155.05,113.05]
    assert p["footprints"]==149 and p["layers_declared"]==12
    assert p["missing_real_magnetics"]==["CT","T1","T2","T3","T4"]
    assert p["density_at_reference_200W_w_in3"]<20
    nn=d["actual_selected_net_geometry"]["nets"]
    for net in ("CR_CT","CT_LR","PRI_T1"):
        assert nn[net]["pad_count"]==1
        assert nn[net]["track_count"]==0

def test_legacy_cout_configuration_cannot_fit_challenge():
    c=d["capacitor_blocker"]
    m=d["targets_not_achieved"]["primary_48v_2v_density_challenge"]
    assert c["oem_units"]==72
    assert math.isclose(c["nominal_courtyard_total_mm2"],72*9.12*5.10,abs_tol=.002)
    assert c["nominal_courtyard_total_mm2"]>15*m["max_footprint_area_mm2"]
    assert c["nominal_parallel_array_capacitance_mF"]==33.84
    assert c["manufacturer_max_seated_height_mm"]==4.3
    assert c["product_4mm_research_envelope_has_single_cap_height_violation_without_recess"] is True

def test_4000_and_6500_are_research_targets_not_results():
    t=d["targets_not_achieved"]
    assert t["primary_48v_2v_density_challenge"]["density_w_in3"]==4000
    assert t["broader_all_ratio_exploratory_challenge"]["density_w_in3"]==6500
    assert t["primary_48v_2v_density_challenge"]["max_module_volume_cm3"]<.83
    assert t["actual_power_density_qualified"] is False
    assert d["release_permission"] is False

def test_150a_product_envelope_is_only_conditional_math():
    c=d['exploratory_150A_product_envelope_NOT_A_CAD']
    assert c['bounding_dimensions_assumed_mm']==[18.0,16.0,4.2]
    assert c['bounding_volume_cm3']==1.2096
    assert c['conditional_density_w_in3']>4000
    assert c['output_pair_loss_at_150A_w']==1.125
    assert c['output_pair_drop_at_150A_mV']==7.5
    assert c['geometry_placement_thermal_and_current_fabrication_validated'] is False

def test_full_load_power_and_heat_laws():
    b=d["loss_budget_at_reference_point"]
    assert math.isclose(b["full_load_97pct"]["loss_watts"],200*(1/.97-1),abs_tol=.001)
    assert math.isclose(b["full_load_98pct"]["loss_watts"],200*(1/.98-1),abs_tol=.001)
    x=d["reference_48_to_2v"]
    assert x["Pout_reference_W"]==200 and x["ratio_reference"]==24

def test_literature_conditions_are_not_collapsed_into_one_record():
    refs=d["published_frontier_operating_points_not_directly_comparable"]
    assert len(refs)>=5
    assert any(x["density_w_in3"]==3548 and x["voltage_output_v"]==6 for x in refs)
    assert any(x["density_w_in3"]==6100 and x["voltage_output_v"]==12 for x in refs)

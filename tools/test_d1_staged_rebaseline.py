"""A staged target does not waive protection, 24 physical magnetic pins or real SOA."""
from copy import deepcopy
import json
import pytest
import d1_staged_rebaseline as m

def test_rebaseline_is_traceable_to_real_spice_and_coldplate_height_screen():
    r=m.evaluate()
    assert r["stages"]["D1_100A"]["observed_sim_current_a"]==pytest.approx(99.82464,abs=.01)
    assert r["stages"]["D1_100A"]["sim_converter_vout_v"]==pytest.approx(1.886686,abs=.002)
    assert r["stages"]["D2_120A"]["observed_sim_current_a"]==pytest.approx(121.66834,abs=.01)
    assert r["stages"]["D2_120A"]["sim_converter_vout_v"]==pytest.approx(1.873692,abs=.002)
    assert r["ohmic_loss_factor_120_over_100_at_equal_path"]==1.44
    elp38=next(x for x in r["elp_core_candidates"] if x["core_id"]=="ELP38_I38")
    assert elp38["three_turn_fault_flux_scenario_t"]==pytest.approx(.23206,abs=.0001)
    assert elp38["remaining_16mm_for_ALL_other_layers_mm"]==pytest.approx(3.65,abs=.001)
    assert elp38["preliminary_combined_16mm_candidate"]
    assert not elp38["full_stack_and_100c_LI_verified"]
    assert not any(x["fab_approved"] for x in r["elp_core_candidates"])
    assert r["numerical_Bage_pair_320us_qualified"]
    assert not r["physical_SR_inhibit_done"]
    assert not r["fabrication_approved"]
    assert json.loads(m.OUT.read_text(encoding="utf-8"))==r

def test_no_silent_safety_or_stage_target_waivers():
    p=json.loads(m.POLICY.read_text(encoding="utf-8"))
    assert not p["hardware_approved"] and not p["production_approved"]
    assert p["safety_invariants"]["must_keep_fabrication_gate"]=="NOT_FOR_FAB"
    assert len(p["safety_invariants"]["must_not_relax"])>=6
    p["production_approved"]=True
    with pytest.raises(ValueError,match="hardware approval"):m.evaluate(policy=p)
    p=json.loads(m.POLICY.read_text(encoding="utf-8"))
    p["stages"][3]["height_limit_mm"]=99
    with pytest.raises(ValueError,match="10mm optimization"):m.evaluate(policy=p)
    p=json.loads(m.POLICY.read_text(encoding="utf-8"))
    p["stages"][1]["load_current_class_a"]=40
    with pytest.raises(ValueError,match="100A-class"):m.evaluate(policy=p)
    gate=json.loads(m.GATE.read_text(encoding="utf-8"))
    gate["release_approved"]=True
    with pytest.raises(ValueError,match="manufacture gate"):m.evaluate(gate=gate)

def test_supplier_failure_fallback_changes_target_not_fab_gate():
    p=json.loads(m.POLICY.read_text(encoding="utf-8"))
    assert any(x["id"]=="MAGNETICS_Z" and "16mm" in x["action"]
               for x in p["stop_loss_rules"])
    assert any(x["id"]=="BAGE_SOLVER" and "no more" in x["action"]
               for x in p["stop_loss_rules"])
    assert p["stages"][1]["fab_release"] is False
    assert p["stages"][2]["fab_release"] is False
    assert p["stages"][3]["fab_release"] is False

def test_legacy_10mm_criteria_remain_reference():
    hi=json.loads(m.HIGH.read_text(encoding="utf-8"))
    assert hi["constraints"]["maximum_assembly_height_mm"]==10
    assert m.evaluate()["legacy_10mm_goal"]=="D3_STRETCH_ONLY"

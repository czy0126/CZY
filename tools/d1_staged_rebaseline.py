"""Rebaseline the D1 prototype target without relaxing physical safety gates.

This is a program decision / feasibility screen; it does NOT generate netted
boards, approve real current rating, or erase the original strict 10mm RFQ.

Stage D0: low-energy hardware protections
Stage D1: 48V / 100A-class / <=16mm preliminary hardware target
Stage D2: 48V / 120A-class / <=16mm power extension
Stage D3: <=10mm optimization, explicitly NOT prerequisite for D1/D2.

Source evidence: actual V3 steady-state SPICE JSON; manufacturer 2019 ELP
catalog dimensions; the frozen 50V/120A fault envelope and current fab gate.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
PP=ROOT/"design/v3/power_priority"
POLICY=PP/"d1_staged_target_policy.json"
OUT=PP/"d1_staged_target_screen.json"
MODELED_100=ROOT/"design/v3/magnetics/magnetics_design.json"
MODELED_120=PP/"operating_point_48v_120a.json"
CORES=PP/"lr_tdk_catalog_core_screen.json"
HIGH=PP/"high_margin_design_gate.json"
GATE=ROOT/"hardware/dcx_main/d1_fabrication_gate.json"
PROTECTION=PP/"prot03_50v_protection_evidence_decision.json"

def read(path:Path)->dict:
    return json.loads(path.read_text(encoding="utf-8"))

def evaluate(policy=None,mag=None,op120=None,cores=None,high=None,gate=None,protect=None)->dict:
    p=read(POLICY) if policy is None else policy
    m=read(MODELED_100) if mag is None else mag
    op=read(MODELED_120) if op120 is None else op120
    core=read(CORES) if cores is None else cores
    high=read(HIGH) if high is None else high
    gate=read(GATE) if gate is None else gate
    protection=read(PROTECTION) if protect is None else protect
    ids=[s["id"] for s in p["stages"]]
    if ids!=["D0_CONTROL","D1_100A","D2_120A","D3_THIN"]:
        raise ValueError("D0/D1/D2/D3 stage sequencing must be explicit")
    if p["safety_invariants"]["must_keep_fabrication_gate"]!="NOT_FOR_FAB":
        raise ValueError("cannot relax NOT_FOR_FAB through program target adjustments")
    if p["hardware_approved"] or p["production_approved"]:
        raise ValueError("rebaseline is not hardware approval")
    # The program-level flags are not sufficient: a stage-local approval
    # erroneously set true would otherwise be silently overwritten by the
    # generated screen's constant False and pass CI.
    if any(stage.get("fab_release") is not False for stage in p["stages"]):
        raise ValueError("stage-local fabrication approval requires independent review")
    if gate["status"]!="NOT_FOR_FAB" or gate["release_approved"]:
        raise ValueError("the live D1 manufacture gate has changed; independent review required")
    if high["constraints"]["maximum_assembly_height_mm"]!=10:
        raise ValueError("original high margin design reference must not be silently overwritten")
    if not protection["B_2fF_agefix"]["completed_matched_pair"]:
        raise ValueError("numerical solver milestone unexpectedly became unresolved")
    if protection["hardware_gate_passed"] or protection["manufacture_approved"]:
        raise ValueError("behavioural Bage fix is not physical protection proof")
    if not 90<=p["stages"][1]["load_current_class_a"]<=100:
        raise ValueError("D1 must retain a meaningful 100A-class demonstration")
    if p["stages"][2]["load_current_class_a"]!=120:
        raise ValueError("D2 is labelled 120A; changing its target requires a program review")
    if p["stages"][1]["height_limit_mm"]!=16 or p["stages"][2]["height_limit_mm"]!=16:
        raise ValueError("D1/D2 mechanical target changed; needs fresh program decision")
    if p["stages"][3]["height_limit_mm"]!=10:
        raise ValueError("10mm optimization remains visible, not deleted")
    if p["electrical_architecture"]["fixed_nominal_ratio"]!=24:
        raise ValueError("architecture changed: 24:1 SPICE results cannot support that target")
    o100=m["operating_point_100a"]
    o120=op
    seen_100=float(o100["Iout_A"])
    seen_120=float(o120["iout_from_v_a"])
    if seen_100<p["stages"][1]["minimum_model_current_a"] or seen_120<p["stages"][2]["minimum_model_current_a"]:
        raise ValueError("modeled current below new stage thresholds")
    v100=float(o100["Vout_V"])
    v120=float(o120["vout_avg_v"])
    if min(v100,v120)<min(p["stages"][1]["min_output_at_converter_v"],
                         p["stages"][2]["min_output_at_converter_v"]):
        raise ValueError("current model does not even support staged converter voltage")
    if any(r["three_turn_joint_pass"] for r in core["cores"]):
        raise ValueError("10mm core screen changed; rerun design review")
    base_b=float(high["magnetics"]["existing_three_turn_worst_b_t"])
    a0=float(high["magnetics"]["existing_core_amin_mm2"])
    b_limit=float(high["magnetics"]["design_flux_limit_t"])
    reserve_mm=float(p["mechanical_planning"]["minimum_reserved_noncore_packaging_mm"])
    if reserve_mm<=0:raise ValueError("a positive non-core mechanical planning allowance is required")
    candidates=[]
    for c in core["cores"]:
        worst=float(c["core_plus_plate_height_max_mm"])
        b3=base_b*a0/float(c["amin_mm2"])
        candidates.append({
            "core_id":c["id"],
            "amin_mm2":int(c["amin_mm2"]),
            "three_turn_fault_flux_scenario_t":round(b3,6),
            "three_turn_flux_screen_pass":b3<=b_limit,
            "manufacturer_bare_core_plus_plate_worst_height_mm":round(worst,2),
            "remaining_16mm_for_ALL_other_layers_mm":round(16-worst,2),
            "bare_core_fits_16mm":worst<=16,
            "planning_noncore_allowance_2mm_screen_pass":16-worst>=reserve_mm,
            "preliminary_combined_16mm_candidate":worst<=16 and b3<=b_limit and 16-worst>=reserve_mm,
            "full_stack_and_100c_LI_verified":False,
            "fab_approved":False,
        })
    elp38=next(x for x in candidates if x["core_id"]=="ELP38_I38")
    if not elp38["preliminary_combined_16mm_candidate"]:
        raise ValueError("ELP38 stage candidate no longer clears preliminary flux and core-only height")
    i2r_factor=round((p["stages"][2]["load_current_class_a"]/
                      p["stages"][1]["load_current_class_a"])**2,4)
    stage_summary={
        "D0_CONTROL":{"status":"LOW_ENERGY_PROTECTION_BOARD_NOT_BUILT",
                       "physical_evidence_pending":True},
        "D1_100A":{"status":"100A_CLASS_MODELED_ONLY_NOT_HARDWARE",
                   "observed_sim_current_a":round(seen_100,6),
                   "sim_converter_vout_v":round(v100,6),
                   "sim_converter_output_w":round(float(o100["Pout_W"]),3) if "Pout_W" in o100
                   else round(v100*seen_100,3),
                   "target_total_height_mm":16,"physical_evidence_pending":True},
        "D2_120A":{"status":"120A_CLASS_MODELED_ONLY_NOT_HARDWARE",
                   "observed_sim_current_a":round(seen_120,6),
                   "sim_converter_vout_v":round(v120,6),
                   "sim_converter_output_w":round(float(o120["pout_w"]),3),
                   "target_total_height_mm":16,"physical_evidence_pending":True},
        "D3_THIN":{"status":"STRETCH_NOT_BLOCKING_D1_D2",
                   "target_total_height_mm":10,"physical_evidence_pending":True}
    }
    return {
        "kind":"D1_STAGED_REBASELINE_LIVE_EVIDENCE_SCREEN",
        "assessment":"DESIGN_ONLY_NEVER_FAB_PERMISSION",
        "policy_source":str(POLICY.relative_to(ROOT)).replace("\\","/"),
        "legacy_10mm_goal":"D3_STRETCH_ONLY",
        "stages":stage_summary,
        "model_only_100_to_120_power_gain_w":round(float(o120["pout_w"])-v100*seen_100,3),
        "ohmic_loss_factor_120_over_100_at_equal_path":i2r_factor,
        "elp_core_candidates":candidates,
        "temporary_noncore_package_reserve_mm":reserve_mm,
        "elp38_initial_16mm_feasibility":"CORE_PLUS_PLATE_ONLY_WITH_3P65MM_LEFT_NOT_A_FULL_STACK",
        "numerical_Bage_pair_320us_qualified":True,
        "physical_SR_inhibit_done":False,
        "magnetic_100c_LI_and_real_pads_done":False,
        "native_board_erc_and_net_pcb_done":False,
        "fabrication_approved":False,
        "next_active_milestones":["D0 ten-gate real inhibit demonstrator",
                                  "ELP38 preliminary 16mm full-stack dimensioned RFQ and 100C L(I)",
                                  "D1 nominal 48V/100A actual load voltage and thermal benchmark"],
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--json",type=Path,default=OUT)
    ap.add_argument("--check",action="store_true")
    a=ap.parse_args()
    res=evaluate()
    text=json.dumps(res,ensure_ascii=False,indent=2)+"\n"
    if a.check:
        if not a.json.is_file() or json.loads(a.json.read_text(encoding="utf-8"))!=res:
            raise SystemExit("outdated staged engineering assessment: "+str(a.json))
    else:
        a.json.parent.mkdir(parents=True,exist_ok=True)
        a.json.write_text(text,encoding="utf-8",newline="\n")
    print("Stages D0 -> D1 100A <=16mm -> D2 120A <=16mm -> D3 10mm stretch.")
    print("ELP38 core-only 16mm screen: preliminary yes; full hardware NOT approved.")
    return 0
if __name__=="__main__":
    raise SystemExit(main())

"""PROT03 50V A/B evidence decision: read latest 1/2/5 fF and 2fF-agefix records.

Never mistake early-terminated control for full-window proof.  The 2fF Bage
model experiment has now run as a matched pair; its qualification lives in its
own section, not in the runner manifest (which hardcodes both flags false).
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
PP=ROOT/"design/v3/power_priority"
A=PP/"protection_candidate_50v_120a_prot_a_paired_shunt_2f.json"
B_OLD=PP/"protection_candidate_50v_120a_prot_b_paired.json"
A_DIAG=PP/"solver_sweep_2f_A_CONTROL_convergence.json"
B_2F_DIAG=PP/"solver_sweep_2f_B_CONTROL_convergence.json"
B_5F=PP/"protection_candidate_50v_120a_prot_b_paired_shunt_5f.json"
B_5F_DIAG=PP/"solver_sweep_5f_B_CONTROL_convergence.json"
AGE_CONTROL=PP/"prot03_bage_agefix_2f_B_CONTROL_vs_v3_3.json"
AGE_CANDIDATE=PP/"prot03_bage_agefix_2f_B_CANDIDATE_vs_v3_3.json"
AGE_PAIR=PP/"protection_candidate_50v_120a_prot_b_paired_agefix_2f.json"
OUT=PP/"prot03_50v_protection_evidence_decision.json"

def _read(path:Path)->dict:
    return json.loads(path.read_text(encoding="utf-8"))

def _deltas_are_all_zero(record:dict)->bool:
    return all(v is None or v==0.0 for v in record["results"]["delta"].values())

def _agefix_section(control:dict,candidate:dict,pair:dict)->dict:
    """The 2 fF B pair re-run on the v3_4 soft Bage rail.

    Completion is the conjunction of three independent records: each role's own
    0-220us model comparison reached the saved stop, and the paired analysis
    covers both full 320us windows with a <=1mV pre-fault V(out) match.  Any
    one missing keeps ``completed_matched_pair`` false; the section is still
    reported so a prefix run is visible instead of silently dropped.
    """
    r=lambda n,p=6:round(n,p)
    c=pair["coverage"]; k=pair["checks"]; rel=pair["results"]["relief"]
    delta=pair["results"]["pre_fault"]["vout_mean_delta_mv"]
    cfull=bool(control["results"]["variant_reached_saved_stop"])
    kfull=bool(candidate["results"]["variant_reached_saved_stop"])
    pair_full=bool(c["base_reached_saved_stop"] and c["candidate_reached_saved_stop"]
                   and k["the_declared_window_is_fully_covered"])
    matched=(cfull and kfull and pair_full
             and bool(k["the_pre_fault_operating_points_match_within_1_mv"])
             and delta<=1.0)
    trig=pair["results"]["trigger"]
    return {
        "sources":{"control":str(AGE_CONTROL.relative_to(ROOT)).replace("\\","/"),
                   "candidate":str(AGE_CANDIDATE.relative_to(ROOT)).replace("\\","/"),
                   "paired":str(AGE_PAIR.relative_to(ROOT)).replace("\\","/")},
        "control_full_320us":cfull,"candidate_full_320us":kfull,
        "completed_matched_pair":matched,
        "pre_fault_vout_delta_mv":delta,
        "shared_window_deltas_are_all_zero":bool(_deltas_are_all_zero(control)
                                                 and _deltas_are_all_zero(candidate)),
        "trigger_us":r(trig["trigger_us"]),"latch_us":r(trig["latch_us"]),
        "base_trip_us":r(trig["base_trip_us"]),
        "trigger_lead_vs_base_us":r(trig["trigger_lead_vs_base_us"]),
        "ipri_peak_a_control":r(pair["results"]["base"]["ipri_peak_a"],3),
        "ipri_peak_a_candidate":r(pair["results"]["candidate"]["ipri_peak_a"],3),
        "sr_peak_a_control":r(pair["results"]["base"]["sr_forward_peak_a"],3),
        "sr_peak_a_candidate":r(pair["results"]["candidate"]["sr_forward_peak_a"],3),
        "ipri_peak_reduction_percent":r(-rel["ipri_peak_rel"]*100,3),
        "sr_peak_reduction_percent":r(-rel["sr_forward_peak_rel"]*100,3),
        "sr_total_i2t_reduction_percent":r(-rel["sr_forward_i2t_total_rel"]*100,3),
        "vout_min_delta_mv":r(rel["vout_min_delta_mv"]),
        "conclusion":("MATCHED_320US_WITH_1P8V_TRIGGER_"
                      f"{r(trig['trigger_lead_vs_base_us'],2)}US_EARLY; "
                      "SOA_REVIEW_STILL_REQUIRED"
                      if matched else "INCOMPLETE_PAIR_NOT_PROMOTED"),
    }

def build(a=None,b=None,diag=None,b2=None,b5=None,d5=None,
          age_control=None,age_candidate=None,age_pair=None)->dict:
    a=_read(A) if a is None else a
    b=_read(B_OLD) if b is None else b
    diag=_read(A_DIAG) if diag is None else diag
    b2=_read(B_2F_DIAG) if b2 is None else b2
    b5=_read(B_5F) if b5 is None else b5
    d5=_read(B_5F_DIAG) if d5 is None else d5
    age_control=_read(AGE_CONTROL) if age_control is None else age_control
    age_candidate=_read(AGE_CANDIDATE) if age_candidate is None else age_candidate
    age_pair=_read(AGE_PAIR) if age_pair is None else age_pair
    age=_agefix_section(age_control,age_candidate,age_pair)
    ac=a["coverage"]; bc=b["coverage"]; f5=b5["coverage"]
    if a["case"]!="prot_a_oc1v_50v" or b["case"]!="prot_b_fast10u_1p8v_50v":
        raise ValueError("wrong A/B protection records")
    if b5["case"]!="prot_b_fast10u_1p8v_50v":
        raise ValueError("5fF B record is not B")
    if not (ac["base_reached_saved_stop"] and ac["candidate_reached_saved_stop"]
            and a["checks"]["the_pre_fault_operating_points_match_within_1_mv"]
            and a["checks"]["the_declared_window_is_fully_covered"]):
        raise ValueError("A 2fF is not a complete matched pair")
    if (bc["base_reached_saved_stop"] or b2["results"]["variant_reached_saved_stop"] or
        f5["base_reached_saved_stop"]):
        raise ValueError("new matched complete B result! Must update decision & rerun tests")
    if b5["checks"]["the_declared_window_is_fully_covered"]:
        raise ValueError("5fF B prefix mislabelled full window")
    if not (b5["checks"]["the_pre_fault_operating_points_match_within_1_mv"]
            and b5["coverage"]["candidate_reached_saved_stop"]):
        raise ValueError("5fF B candidate/prefault evidence changed")
    a_rel=a["results"]["relief"]
    if abs(a_rel["sr_forward_peak_rel"])>.001 or abs(a_rel["ipri_peak_rel"])>.001:
        raise ValueError("A peak relief changed; recompute verdict")
    if a["results"]["pre_fault"]["vout_mean_delta_mv"]>1:
        raise ValueError("A pair no longer within 1mV")
    r=lambda n,p=6:round(n,p)
    peak_us=diag["results"]["variant"]["ipri_peak_ms"]*1000.
    trigger_us=a["results"]["trigger"]["trigger_us"]
    return {
        "kind":"PROT03_50V_120A_EVIDENCE_DECISION",
        "evidence_level":"GIT_COMMITTED_1FF_2FF_5FF_ANALYSIS_ONLY; RAW_CHECKSUMS_PROVENANCE_SEPARATE",
        "A_2fF":{
            "base_full_320us":bool(ac["base_reached_saved_stop"]),
            "candidate_full_320us":bool(ac["candidate_reached_saved_stop"]),
            "pre_fault_vout_delta_mv":a["results"]["pre_fault"]["vout_mean_delta_mv"],
            "trip_us":r(trigger_us),
            "base_ipri_peak_time_us":r(peak_us),
            "trip_after_base_ipri_peak_us":r(trigger_us-peak_us),
            "ipri_peak_a_control":r(a["results"]["base"]["ipri_peak_a"],3),
            "ipri_peak_a_candidate":r(a["results"]["candidate"]["ipri_peak_a"],3),
            "sr_peak_a_control":r(a["results"]["base"]["sr_forward_peak_a"],3),
            "sr_peak_a_candidate":r(a["results"]["candidate"]["sr_forward_peak_a"],3),
            "sr_total_i2t_reduction_percent":r(-a_rel["sr_forward_i2t_total_rel"]*100,3),
            "conclusion":"MATCHED_320US_BUT_NO_INITIAL_PEAK_REDUCTION"},
        "B_previous_1fF":{
            "control_end_us":r(bc["base_t_last_us"]),
            "control_full_320us":bool(bc["base_reached_saved_stop"]),
            "candidate_full_320us":bool(bc["candidate_reached_saved_stop"]),
            "pre_fault_vout_delta_mv":b["results"]["pre_fault"]["vout_mean_delta_mv"],
            "comparison_full_window":bool(b["checks"]["the_declared_window_is_fully_covered"]),
            "nominal_sr_peak_reduction_percent_prefix_only":r(-b["results"]["relief"]["sr_forward_peak_rel"]*100,3),
            "conclusion":"PARTIAL_CONTROL_ONLY_NO_FULL_WINDOW_PEAK_CLAIM"},
        "B_2fF":{
            "source":"design/v3/power_priority/solver_sweep_2f_B_CONTROL_convergence.json",
            "control_end_us":r(b2["results"]["variant_t_last_us"]),
            "control_full_320us":bool(b2["results"]["variant_reached_saved_stop"]),
            "control_numeric_vs_1ff_checks":b2["checks"],
            "solver_failure_identified_in_document":"xsr3:x2:Bage; see docs/D1_EXECUTION_KIT/18_50V成对数值收敛扫参与执行.md",
            "candidate_reported_full_320us_in_document":True,
            "completed_matched_pair":False,
            "conclusion":"SOLVER_FAILED_AT_BAGE_NO_320US_MATCHED_PAIR"},
        "B_5fF":{
            "source":"design/v3/power_priority/protection_candidate_50v_120a_prot_b_paired_shunt_5f.json",
            "control_end_us":r(f5["base_t_last_us"]),
            "control_full_320us":bool(f5["base_reached_saved_stop"]),
            "candidate_full_320us":bool(f5["candidate_reached_saved_stop"]),
            "pre_fault_vout_delta_mv":b5["results"]["pre_fault"]["vout_mean_delta_mv"],
            "comparison_full_window":bool(b5["checks"]["the_declared_window_is_fully_covered"]),
            "control_solver_timeout_reported_in_document":True,
            "numeric_vs_1ff_checks":d5["checks"],
            "conclusion":"CONTROL_EARLY_TIMEOUT_PREFIX_235P890US"},
        "B_cshunt_nonmonotone":True,
        "B_2fF_agefix":age,
        "numeric_solver_next_step":{
            "strategy":"ISOLATE_KNOWN_BAGE_10V_HARD_RAIL_BEFORE_WIDER_SWEEPS",
            "model":"models/sr_timing_v3_4_age_rail.lib",
            "command":"python tools/run_prot03_bage_diagnostic.py --variant shunt_2f --execute --run-id bage_2f_001 --ltspice D:/ADI/LTspice/LTspice.exe",
            "status":"COMPLETE_BOTH_320US" if age["completed_matched_pair"] else "UNRUN",
            "requires_paired_320us":True,
            "requires_pre_fault_vout_delta_mv_max":1,
            "requires_model_vs_v3_3_220us_frozen_metrics":True,
            "still_open":"independent device SOA review; the runner manifest's both_320us_qualified stays false by design"},
        "hardware_gate_passed":False,"manufacture_approved":False}

def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--write",action="store_true")
    p.add_argument("--check",action="store_true")
    a=p.parse_args()
    record=build()
    output=json.dumps(record,ensure_ascii=False,indent=2)+"\n"
    if a.write:OUT.write_text(output,encoding="utf-8",newline="\n")
    elif a.check and (not OUT.is_file() or OUT.read_text(encoding="utf-8")!=output):
        raise SystemExit("stale PROT03 decision: 1/2/5fF or 2fF-agefix evidence changed")
    print("B1fF 254.980us, B2fF 264.515us, B5fF 235.890us: old controls incomplete. "
          f"2fF agefix pair: {record['B_2fF_agefix']['conclusion']}.")
if __name__=="__main__":
    raise SystemExit(main())

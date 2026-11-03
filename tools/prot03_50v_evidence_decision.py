"""Evidence-based 50V PROT-03 go/no-go, not an invented simulation result.

Source JSON is re-read each invocation, so a copied document cannot silently
promote the partial B control run or the ineffective A late trip to hardware.
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
B_2F=PP/"protection_candidate_50v_120a_prot_b_paired_shunt_2f.json"
OUT=PP/"prot03_50v_protection_evidence_decision.json"

def build(a=None,b=None,diag=None,b_2f_override=None):
    if a is None:a=json.loads(A.read_text(encoding="utf-8"))
    if b is None:b=json.loads(B_OLD.read_text(encoding="utf-8"))
    if diag is None:diag=json.loads(A_DIAG.read_text(encoding="utf-8"))
    if a["case"]!="prot_a_oc1v_50v" or b["case"]!="prot_b_fast10u_1p8v_50v":
        raise ValueError("wrong protection comparison cases")
    a_cov=a["coverage"];b_cov=b["coverage"]
    ac=a["checks"];bp=b["checks"]
    if not (a_cov["base_reached_saved_stop"] and a_cov["candidate_reached_saved_stop"] and
            ac["the_pre_fault_operating_points_match_within_1_mv"] and
            ac["the_declared_window_is_fully_covered"]):
        raise ValueError("the claimed 2fF A pair no longer has complete paired evidence")
    if b_cov["base_reached_saved_stop"] or bp["the_declared_window_is_fully_covered"]:
        raise ValueError("B 1fF historical control is no longer the prefix-only record")
    a_rel=a["results"]["relief"]
    base=a["results"]["base"];candidate=a["results"]["candidate"]
    trigger_us=a["results"]["trigger"]["trigger_us"]
    peak_us=diag["results"]["variant"]["ipri_peak_ms"]*1000
    if a["results"]["pre_fault"]["vout_mean_delta_mv"]>1.0:
        raise ValueError("A does not qualify as matched")
    if abs(a_rel["sr_forward_peak_rel"])>0.001 or abs(a_rel["ipri_peak_rel"])>0.001:
        raise ValueError("A has changed: now recompute peak-control verdict")
    if b_2f_override is None and B_2F.is_file():
        b_2f_override=json.loads(B_2F.read_text(encoding="utf-8"))
    bstatus="UNAVAILABLE_NO_COMMITTED_2FF_B_RECORD"
    if b_2f_override is not None:
        cov=b_2f_override["coverage"]
        good=(cov["base_reached_saved_stop"] and cov["candidate_reached_saved_stop"] and
              b_2f_override["checks"]["the_pre_fault_operating_points_match_within_1_mv"] and
              b_2f_override["checks"]["the_declared_window_is_fully_covered"])
        bstatus="MATCHED_FULL_WINDOW_SIMULATED_ONLY" if good else "B_2FF_RECORD_NOT_FULLY_PAIRED"
    return {"kind":"PROT03_50V_120A_EVIDENCE_DECISION",
        "evidence_level":"GIT_COMMITTED_JSON_ONLY; RAW_CHECKSUMS_PROVENANCE_SEPARATE",
        "A_2fF": {
            "base_full_320us":True,"candidate_full_320us":True,
            "pre_fault_vout_delta_mv":a["results"]["pre_fault"]["vout_mean_delta_mv"],
            "trip_us":round(trigger_us,6),
            "base_ipri_peak_time_us":round(peak_us,6),
            "trip_after_base_ipri_peak_us":round(trigger_us-peak_us,6),
            "ipri_peak_a_control":round(base["ipri_peak_a"],3),
            "ipri_peak_a_candidate":round(candidate["ipri_peak_a"],3),
            "sr_peak_a_control":round(base["sr_forward_peak_a"],3),
            "sr_peak_a_candidate":round(candidate["sr_forward_peak_a"],3),
            "sr_total_i2t_reduction_percent":round(-a_rel["sr_forward_i2t_total_rel"]*100,3),
            "conclusion":"NO_INITIAL_PEAK_REDUCTION_LATE_TRIP; VALID_SIM_PAIR_NOT_VALID_HARDWARE"},
        "B_previous_1fF":{
            "base_full_320us":bool(b_cov["base_reached_saved_stop"]),
            "candidate_full_320us":bool(b_cov["candidate_reached_saved_stop"]),
            "base_last_saved_us":round(b_cov["base_t_last_us"],6),
            "nominal_sr_peak_reduction_percent_prefix_only":round(-b["results"]["relief"]["sr_forward_peak_rel"]*100,3),
            "conclusion":"PROMISING_EARLY_BEHAVIORAL_TRIP_BUT_CONTROL_PREFIX_CENSORED"},
        "B_2fF":{"status":bstatus,"source_file":str(B_2F.relative_to(ROOT)).replace("\\","/"),
                 "required_pre_fault_vout_delta_mv_max":1.0,
                 "required_base_and_candidate_saved_stop_us":320.0},
        "next_command":"python tools/run_d1_50v_matched_cases.py --variant shunt_2f --cases B_CONTROL B_CANDIDATE --execute --run-id solver_2f_B_001 --ltspice D:/ADI/LTspice/LTspice.exe",
        "acceptance_rule":"Run both B decks at 2fF; check complete 320us and <=1mV pre-fault, eight SR gates, primary gates, I2t, and independent real gate-drive latency separately",
        "hardware_gate_passed":False,"manufacture_approved":False}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--check",action="store_true")
    p.add_argument("--write",action="store_true")
    opts=p.parse_args()
    obj=build()
    data=json.dumps(obj,ensure_ascii=False,indent=2)+"\n"
    if opts.write:OUT.write_text(data,encoding="utf-8",newline="\n")
    elif opts.check and (not OUT.is_file() or OUT.read_text(encoding="utf-8")!=data):
        raise SystemExit("PROT03 decision record outdated")
    print("A 2fF full pair has 0% peak reduction; B 2fF next test =",obj["B_2fF"]["status"])
    print("hardware gate:",obj["hardware_gate_passed"],"fab:",obj["manufacture_approved"])
if __name__=="__main__":main()

"""Exact one-line SR Bage soft-rail convergence diagnostic, completely UNRUN.

The SR surrogate's age-state current is discontinuous at 10 V in v3_3:
   I=if(Q, if(age<10,-1m,0), age)
V3_4-age-rail replaces ONLY the 10 V hard stop with the existing continuous
9.9-10 V limiter.  The actual on-blank decision is at BON*1e6=0.475 V.
No physical SR silicon, SOA, or automatic full-window convergence is implied.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
SIM=ROOT/"sim/v3"
MODEL_ROOT=ROOT/"models"
ORIGINAL=MODEL_ROOT/"sr_timing_v3_3.lib"
NEW=MODEL_ROOT/"sr_timing_v3_4_age_rail.lib"
OLD='Bage age S I=if(V(Q,S)>.5,if(V(age,S)<10,-1m,0),V(age,S))'
REVISED='Bage age S I=if(V(Q,S)>.5,-1m*limit((10-V(age,S))/0.1,0,1),V(age,S))'
HEADER=(
    "* models/sr_timing_v3_4_age_rail.lib -- post-fault numerical experiment, NOT SILICON.\n"
    "* Exactly ONE behavioural change relative to sr_timing_v3_3.lib: Bage age\n"
    "* timer's 10 V hard step is replaced by the same 9.9-10 V soft limiter\n"
    "* already used for the off-blank timer. Below 9.9 V, I(age) is identical\n"
    "* (-1m while Q high), and the only user of age uses BON=475 ns (0.475 V).\n"
    "* The long-run rail is reached after ~10 us of uninterrupted Q high,\n"
    "* well outside the blanking threshold. Intended for causal diagnostics of\n"
    "* xsr3:x2:Bage convergence, NOT a verified device behaviour or SOA claim.\n"
    "* No other model components, thresholds or parameters may change.\n"
    "*\n")
DECK_HEADER=(
    "* BAGE_SOFT_RAIL_DIAGNOSTIC_ONLY: MODEL NOT SILICON; DECK NOT RUN.\n"
    "* Both control and candidate must reference exactly the same altered SR model.\n")
ROLE_FILES={
    "published":{
        "B_CONTROL":"sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe_prot_b_fast10u_1p8v_thrmute_control.cir",
        "B_CANDIDATE":"sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe_prot_b_fast10u_1p8v.cir"},
    "shunt_2f":{
        "B_CONTROL":"d1_prot03_shunt_2f_B_CONTROL.cir",
        "B_CANDIDATE":"d1_prot03_shunt_2f_B_CANDIDATE.cir"}}
INCLUDE_OLD=".include ../../models/sr_timing_v3_3.lib"
INCLUDE_NEW=".include ../../models/sr_timing_v3_4_age_rail.lib"
OUT=ROOT/"design/v3/power_priority/prot03_bage_soft_rail_plan.json"

def model_content()->str:
    original=ORIGINAL.read_text(encoding="utf-8")
    if original.count(OLD)!=1:
        raise ValueError("Bage expression has changed: independent review required")
    return HEADER+original.replace(OLD,REVISED,1)

def deck_path(variant:str,role:str)->Path:
    if variant not in ROLE_FILES or role not in ROLE_FILES[variant]:
        raise ValueError("unknown paired Bage diagnostic role or variant")
    return SIM/f"d1_prot03_agefix_{variant}_{role}.cir"

def deck_content(variant:str,role:str)->str:
    original=(SIM/ROLE_FILES[variant][role]).read_text(encoding="utf-8")
    if original.count(INCLUDE_OLD)!=1:
        raise ValueError("missing original model reference")
    new=DECK_HEADER+original.replace(INCLUDE_OLD,INCLUDE_NEW,1)
    expected_shunt="1e-15" if variant=="published" else "2e-15"
    if f".options plotwinsize=0 method=gear cshunt={expected_shunt}" not in new:
        raise ValueError("unexpected original solver options")
    if ".tran 0 2320u 2000u 5n uic" not in new:
        raise ValueError("unexpected saved window")
    return new

def plan()->dict:
    rows=[]
    for variant,roles in ROLE_FILES.items():
        for role,parent in roles.items():
            rows.append({"variant":variant,"role":role,
                "source_deck":"sim/v3/"+parent,
                "generated_deck":"sim/v3/"+deck_path(variant,role).name,
                "new_sr_model":"models/sr_timing_v3_4_age_rail.lib",
                "old_sr_model":"models/sr_timing_v3_3.lib",
                "execution_state":"UNRUN",
                "both_320us_qualified":False,
                "pre_fault_1mv_qualified":False,
                "physical_circuit_or_silicon_verified":False})
    return {
        "kind":"PROT03_SRBAGE_SOFT_RAIL_CONTROLLED_DIAGNOSTIC",
        "motivation":"50V B 2fF CONTROL stopped at 264.515 us with LTspice convergence failure instance xsr3:x2:Bage",
        "evidence":"GENERATED_NOT_SIMULATED",
        "original_model":"models/sr_timing_v3_3.lib",
        "new_model":"models/sr_timing_v3_4_age_rail.lib",
        "model_change_count":1,
        "modification":"Bage 10V discontinuous hard upper rail to continuous 9.9-10V soft rail",
        "affects_on_blank_comparator_threshold":False,
        "original_on_blank_threshold_v":0.475,
        "on_state_current_below_age_9p9v_unchanged":True,
        "unmodified_bton_and_btoff_discontinuities_remain":True,
        "compare_rules":["Control and candidate must use same variant, solver options, and v3_4_age_rail model",
                         "Compare v3_3 and v3_4 only over same 0-220us prefix before claiming no operating point drift",
                         "Pass requires both 320us, <=1mV pre-fault Vout, 10-gate state, and independent device SOA review",
                         "Bage age rail smoothing is a numerical surrogate modification, not OEM driver behavior"],
        "records":rows,"fabrication_approved":False}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--write",action="store_true")
    p.add_argument("--check",action="store_true")
    a=p.parse_args()
    files=[(NEW,model_content()),
           *[(deck_path(v,r),deck_content(v,r)) for v,roles in ROLE_FILES.items() for r in roles],
           (OUT,json.dumps(plan(),ensure_ascii=False,indent=2)+"\n")]
    for path,wanted in files:
        if a.write:path.write_text(wanted,encoding="utf-8",newline="\n")
        elif a.check and (not path.is_file() or path.read_text(encoding="utf-8")!=wanted):
            raise SystemExit("Bage evidence artifact stale: "+str(path))
    print("Bage soft-rail 1-line model + 4 paired decks: UNRUN; not silicon or fab proof")

if __name__=="__main__":main()

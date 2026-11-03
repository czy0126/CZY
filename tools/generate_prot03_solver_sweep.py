"""Generate 50V paired solver-parameter diagnostics. NO simulation is run.
Only .options cshunt changes, identically on A/B control and candidate.
Generated deck comparisons should never be mixed with published 1fF results.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
SIM=ROOT/"sim/v3"
RESULT=ROOT/"design/v3/power_priority/prot03_solver_sweep_plan.json"
SOURCE={
"A_CONTROL":"sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe_prot_a_oc1v_thrmute_control.cir",
"A_CANDIDATE":"sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe_prot_a_oc1v.cir",
"B_CONTROL":"sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe_prot_b_fast10u_1p8v_thrmute_control.cir",
"B_CANDIDATE":"sr_tank_dual_v33_ss_hotfault_50v_120a_cshunt_srprobe_prot_b_fast10u_1p8v.cir"}
VARIANTS={"shunt_2f":"2e-15","shunt_5f":"5e-15","shunt_10f":"1e-14"}
ANCHOR=".options plotwinsize=0 method=gear cshunt=1e-15"
HEADER=("* GENERATED DIAGNOSTIC ONLY -- ORIGINAL WORKING CIRCUIT UNCHANGED -- UNRUN\n"
        "* Pair all four decks with identical shunt value. Not an electrical/hardware signoff.\n")

def build(label,case):
    if label not in VARIANTS or case not in SOURCE:raise ValueError("unknown sweep variant or case")
    raw=(SIM/SOURCE[case]).read_text(encoding="utf-8")
    if raw.count(ANCHOR)!=1:raise ValueError("expected exactly one fixed 1fF cshunt options line")
    if ".tran 0 2320u 2000u 5n uic" not in raw:raise ValueError("required 320us save window missing")
    return HEADER+raw.replace(ANCHOR,ANCHOR.replace("1e-15",VARIANTS[label]),1)

def filename(label,case):
    return SIM/f"d1_prot03_{label}_{case}.cir"

def plan():
    rows=[]
    for label,val in VARIANTS.items():
        for case,src in SOURCE.items():
            rows.append({"variant":label,"shunt_farads":val,"case_id":case,
              "source_deck":"sim/v3/"+src,
              "generated_deck":"sim/v3/"+filename(label,case).name,
              "simulation_state":"UNRUN","hardware_state":"NOT_APPROVED",
              "full_window_320us_confirmed":False,"pairing_pre_fault_1mV_confirmed":False})
    return {"kind":"PROT03_MATCHED_NUMERIC_SENSITIVITY_DECKS",
      "evidence":"STATIC_GENERATION_ONLY_NO_NEW_LTSPICE_RUN",
      "variants":[{"name":n,"cshunt_farads":v} for n,v in VARIANTS.items()],
      "baseline_cshunt_farads":"1e-15",
      "control_pairing_limit_vout_millivolt":1,
      "required_saved_window_us":320,
      "source_repo_sha":"c841f5571673017facf7e91c3ca9ccadc18a8f6b",
      "records":rows,"preferred_run_order":["shunt_2f","shunt_5f","shunt_10f"],
      "acceptance":"same solver tweak applied to control & candidate; both 320us plus <=1mV pre-fault Vout; actual physical model SOA separate",
      "not_for_fab":True}
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--check",action="store_true")
    p.add_argument("--write",action="store_true")
    args=p.parse_args()
    for label in VARIANTS:
        for case in SOURCE:
            path=filename(label,case);expect=build(label,case)
            if args.write:path.write_text(expect,encoding="utf-8",newline="\n")
            elif args.check and (not path.exists() or path.read_text(encoding="utf-8")!=expect):
                raise SystemExit("Stale generated numerical diagnostic: "+str(path))
    text=json.dumps(plan(),indent=2,ensure_ascii=False)+"\n"
    if args.write:RESULT.write_text(text,encoding="utf-8",newline="\n")
    elif args.check and (not RESULT.exists() or RESULT.read_text(encoding="utf-8")!=text):
        raise SystemExit("Stale numerical run plan")
    print("12 static, identical solver-only variants: UNRUN and NOT_FOR_FAB")
if __name__=="__main__":main()

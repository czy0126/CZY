"""Run the precise Bage-only PROT-03 paired model experiment safely.

This is NOT the current authoritative power model. Must never promote the
numerical experiment to silicon/OEM evidence. All runs archived by the existing
robust, SHA-256 protected runner. No simulator is called without --execute.

Usage:
 python tools/run_prot03_bage_diagnostic.py --variant shunt_2f
 python tools/run_prot03_bage_diagnostic.py --variant shunt_2f --execute \
   --run-id bage_2f_001 --ltspice 'D:/ADI/LTspice/LTspice.exe'
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

import generate_prot03_bage_diagnostic as g
import run_d1_50v_matched_cases as run

ROLES=("B_CONTROL","B_CANDIDATE")

def validate(variant:str)->dict[str,str]:
    if variant not in g.ROLE_FILES:
        raise ValueError("variant not prepared")
    if g.NEW.read_text(encoding="utf-8")!=g.model_content():
        raise ValueError("unapproved change to Bage experiment model")
    checked={}
    for role in ROLES:
        expected=g.deck_content(variant,role)
        p=g.deck_path(variant,role)
        if p.read_text(encoding="utf-8")!=expected:
            raise ValueError("unapproved deck change: "+str(p))
        checked[role]=p.name
    return checked

def main(argv:list[str]|None=None)->int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--variant",choices=tuple(g.ROLE_FILES),default="shunt_2f")
    ap.add_argument("--execute",action="store_true")
    ap.add_argument("--run-id",default="")
    ap.add_argument("--ltspice",default="")
    ap.add_argument("--timeout-s",type=float,default=1800)
    ap.add_argument("--archive-root",type=Path,default=run.DEFAULT_ARCHIVE)
    args=ap.parse_args(argv)
    decks=validate(args.variant)
    if not args.execute:
        for role,path in decks.items():
            print(f"DRY_RUN {args.variant} {role} sim/v3/{path}")
        print("No simulation run; actual prototype and manufacture NOT_APPROVED")
        return 0
    ltspice=run.find_ltspice(args.ltspice)
    rid=run.check_run_id(args.run_id)
    target=args.archive_root/rid
    if target.exists():
        raise SystemExit("Refuse overwrite Bage diagnostic archive: "+str(target))
    target.mkdir(parents=True)
    observations=[]
    for role in ROLES:
        case_dir=target/role
        case_dir.mkdir()
        stage=run.SIM/f"d1_{rid}_{role}.cir"
        result=run.run_case(role,stage,ltspice,case_dir,args.timeout_s,decks)
        observations.append(result)
        print(role,result["state"],result["tail_us"])
    summary={
        "kind":"SR_BAGE_NUMERIC_DIAGNOSTIC_ONLY",
        "variant":args.variant,
        "run_id":rid,
        "model_source":"models/sr_timing_v3_4_age_rail.lib",
        "model_sha256":run.sha256(g.NEW),
        "solver_model_must_be_compared_against_v3_3":True,
        "circuit_simulator_only":True,
        "both_320us_qualified":False,
        "pre_fault_1mv_qualified":False,
        "physical_device_soA_verified":False,
        "fabrication_approved":False,
        "cases":observations}
    (target/"run_manifest.json").write_text(
        json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n")
    if any(r["state"]!="DURATION_ONLY_PASS" for r in observations):
        raise SystemExit("Incomplete simulation evidence retained in "+str(target))
    print("Both decks reached end; still compare old model on 0-220us, Vout 1mV, all gates, SOA")
    return 0
if __name__=="__main__":
    raise SystemExit(main())

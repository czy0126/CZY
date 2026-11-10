"""Apply the six short, low-current signal nets to a NEW EasyEDA G1 board copy.

Source is the real, reopened post-Lr-repack board. The parent .eprj2 hash must
match its native receipt before any EDA invocation. Never overwrite a previous
trial; native DRC must improve relative to the old board, and never claim a
fabrication release.

Windows EasyEDA Pro host:
  python hardware/dcx_main/g1/apply_lr_signal_stubs.py --check
  python hardware/dcx_main/g1/apply_lr_signal_stubs.py --apply

Only --check runs on source-only CI. --apply needs the Windows lceda-pro.exe
CLI and exclusive editor access, and produces a NEW .eprj2 candidate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import apply_increment as A
import route_lr_signal_stubs as S
import run_driver_drc as D

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=S.SOURCE
TARGET=HERE/S.CANDIDATE
PREFIX="lr_signal"
BEFORE_DRC=HERE/"lr_repack_drc_raw.json"
AFTER_DRC=HERE/(PREFIX+"_drc_raw.json")
DRC_DELTA=HERE/(PREFIX+"_drc_delta.json")


def categories(path: Path) -> dict:
    resp=json.loads(path.read_text(encoding="utf-8"))
    if resp.get("ok") is not True:
        raise ValueError(f"Invalid native DRC result: {path}")
    grps=(resp.get("value") or {}).get("raw")
    if not isinstance(grps,list):
        raise ValueError(f"Native DRC has no real categories: {path}")
    out={}
    for group in grps:
        name=group["name"]
        if name in out:
            raise ValueError("Duplicated DRC category")
        out[name]=sum(len(c.get("list") or []) for c in (group.get("list") or []))
    return out


def compare_drc() -> dict:
    a,b=categories(BEFORE_DRC),categories(AFTER_DRC)
    added={k:v for k,v in b.items() if v and not a.get(k)}
    if added:
        raise ValueError(f"Unexpected native DRC category: {added}")
    if b.get("Connection Error",0) >= a.get("Connection Error",0):
        raise ValueError("Six new wires must reduce DRC open connection count")
    if b.get("Physical Error",0) > 0:
        raise ValueError("New trace introduced a physical collision")
    if b.get("Netlist Error",0) > a.get("Netlist Error",0):
        raise ValueError("Netlist mismatch got worse")
    if any(b.get(k,0)>v for k,v in a.items()):
        raise ValueError("Unexpected DRC regression outside the intended signal routing")
    return {
      "status":"ACTUAL_NATIVE_DRC_IMPROVED_BUT_NOT_FAB",
      "from":a,"to":b,
      "connection_errors_reduced":a["Connection Error"]-b.get("Connection Error",0),
      "physical_drc_errors":0,
      "board_routed_and_erc_complete":False,
      "real_magnetic_terminals_verified":False,
      "fabrication_approved":False,
    }


def apply() -> int:
    preview=S.report()
    if preview["preflight_problems"]:
        raise RuntimeError("Cannot operate native EDA on an unsafe offline signal plan")
    if TARGET.exists():
        raise FileExistsError(f"Refuse to overwrite previously applied EDA candidate {TARGET}")
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest()!=preview["source_sha256"]:
        raise ValueError("Native source file modified between preflight and operation")
    if A.apply(S,SOURCE,PREFIX):
        return 1
    result=subprocess.run([sys.executable,str(HERE/"run_driver_drc.py"),
                           "--board",str(TARGET),"--prefix",PREFIX+"_drc"],
                          check=False)
    if result.returncode:
        return result.returncode
    comparison=compare_drc()
    DRC_DELTA.write_text(json.dumps(comparison,ensure_ascii=False,indent=2)+"\n",
                         encoding="utf-8")
    print(json.dumps(comparison,ensure_ascii=False,indent=2))
    return 0


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    g=parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--check",action="store_true")
    g.add_argument("--apply",action="store_true")
    x=parser.parse_args()
    if x.check:
        payload=S.report()
        print(json.dumps(payload,ensure_ascii=False,indent=2))
        return int(bool(payload["preflight_problems"]))
    return apply()


if __name__=="__main__":
    raise SystemExit(main())

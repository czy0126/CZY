"""One-shot native EasyEDA ECO for the actual G1 199-connection-error board.

Windows EasyEDA Pro workstation, with the 107-line parent board unmodified:
  python hardware/dcx_main/g1/apply_g1_open_batch.py --check
  python hardware/dcx_main/g1/apply_g1_open_batch.py --apply

--apply creates a NEW .eprj2, reopens it and runs ACTUAL EasyEDA DRC.
The batch is accepted only if the connection-error count decreases from 199,
Netlist Error never grows above 1, and no Physical Error is introduced.
No second run on the same candidate; never touch the accepted parent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import apply_increment as A
import route_open_connections as P

HERE=Path(__file__).resolve().parent
TARGET=HERE/P.CANDIDATE
PREFIX="g1_open_batch"
AFTER_DRC=HERE/(PREFIX+"_drc_raw.json")
DELTA=HERE/(PREFIX+"_drc_delta.json")


def compare_actual_drc()->dict:
    before=P.categories(json.loads(P.DRC.read_text(encoding="utf-8")))
    after=P.categories(json.loads(AFTER_DRC.read_text(encoding="utf-8")))
    if before["Connection Error"]!=199 or before["Netlist Error"]!=1:
        raise ValueError("Original native 199/1 DRC baseline changed")
    if after.get("Connection Error",0)>=before["Connection Error"]:
        raise ValueError("Native routing did NOT reduce the 199 open connections")
    if after.get("Netlist Error",0)>1 or after.get("Physical Error",0)>0:
        raise ValueError("Native routing introduced netlist or physical error")
    if any(after.get(k,0)>v for k,v in before.items()):
        raise ValueError("Unexpected new native DRC category/error")
    return {
        "status":"ACTUAL_EASYEDA_COPPER_IMPROVED_NOT_FOR_FAB",
        "parent_sha256":hashlib.sha256(P.SOURCE.read_bytes()).hexdigest(),
        "candidate_sha256":hashlib.sha256(TARGET.read_bytes()).hexdigest(),
        "source_drc":before,"native_reopen_drc":after,
        "native_connection_errors_reduced":
            before["Connection Error"]-after.get("Connection Error",0),
        "native_board_saved_reopened":True,
        "remaining_magnetic_real_terminals_qualified":False,
        "100a_two_rail_copper_qualified":False,
        "full_board_fabrication_approved":False,
    }


def apply()->int:
    plan=P.report()
    if plan["preflight_problems"]:
        raise RuntimeError("Actual 107-line G1 geometry rejects this copper batch")
    if TARGET.exists():
        raise FileExistsError(f"Refusing to overwrite native ECO: {TARGET}")
    before_hash=hashlib.sha256(P.SOURCE.read_bytes()).hexdigest()
    if before_hash!=plan["source_sha256"]:
        raise ValueError("G1 parent modified during routing audit")
    if A.apply(P,P.SOURCE,PREFIX):
        return 1
    result=subprocess.run([sys.executable,str(HERE/"run_driver_drc.py"),
                           "--board",str(TARGET),"--prefix",PREFIX+"_drc"],check=False)
    if result.returncode:
        return result.returncode
    comparison=compare_actual_drc()
    DELTA.write_text(json.dumps(comparison,ensure_ascii=False,indent=2)+"\n",
                     encoding="utf-8",newline="\n")
    print(json.dumps(comparison,ensure_ascii=False,indent=2))
    return 0


def main()->int:
    ap=argparse.ArgumentParser(description=__doc__)
    group=ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--check",action="store_true")
    group.add_argument("--apply",action="store_true")
    arg=ap.parse_args()
    if arg.check:
        d=P.report()
        print(json.dumps(d,ensure_ascii=False,indent=2))
        return int(bool(d["preflight_problems"]))
    return apply()


if __name__=="__main__":
    raise SystemExit(main())

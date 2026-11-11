"""One native EasyEDA Pro command: create the six previously clear control traces.

From the verified PR95 132-line/183-Connection parent, COPY to a new
.eprj2, apply actual PrimitiveLine.create() commands, save, close, reopen,
compare all old copper/pads/vias, run the actual editor DRC, and accept
only if the native Connection Error count falls below 183.

No beta autoRouting; no GPU; no self-hosted runner requirement; no physical
or magnetic power-net autorouting. NOT_FOR_FAB even on successful DRC delta.

On the Windows workstation, with EasyEDA Pro available:
    python hardware/dcx_main/g1/apply_g1_control_direct.py --check
    python hardware/dcx_main/g1/apply_g1_control_direct.py --apply
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import apply_increment as E
import route_g1_control_direct as P
import route_open_connections as OLD

HERE=Path(__file__).resolve().parent
TARGET=HERE/P.CANDIDATE
PREFIX="g1_control_direct"
RAW_DRC=HERE/(PREFIX+"_drc_raw.json")
DELTA=HERE/(PREFIX+"_drc_delta.json")

def sha(path:Path)->str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def compare_native_drc()->dict:
    old=OLD.categories(json.loads(P.BASE_DRC.read_text(encoding="utf-8")))
    new=OLD.categories(json.loads(RAW_DRC.read_text(encoding="utf-8")))
    if (old["Connection Error"],old["Netlist Error"],
        old.get("Physical Error",0))!=(183,1,0):
        raise ValueError("Wrong accepted 132-line native DRC baseline")
    missing=[k for k,n in old.items() if n>0 and k not in new]
    if missing:
        raise ValueError("Native DRC category disappeared; possible truncated report "+repr(missing))
    if new.get("Connection Error",999)>=183:
        raise ValueError("Native direct copper did not reduce the 183 open connections")
    if new.get("Netlist Error",0)>1 or new.get("Physical Error",0)>0:
        raise ValueError("Native direct routing introduced netlist/physical DRC errors")
    if any(new.get(k,0)>old.get(k,0) for k in old.keys()|new.keys()):
        raise ValueError("Additional native DRC errors/categories appeared")
    evidence=json.loads(P.REPORT_OUT.read_text(encoding="utf-8"))
    if (evidence["placement_drift"] or
        evidence["lines"]["coverage_problems"] or
        evidence["vias"]["problems"] or
        not evidence["layout_counts"]["unchanged"]):
        raise ValueError("Actual native trace readback did not match reviewed six pairs")
    if sha(P.SOURCE)!=P.EXPECTED_SHA:
        raise ValueError("The accepted native 132-line parent changed during routing")
    return {
      "status":"ACTUAL_G1_DIRECT_COPPER_DRC_IMPROVED_NOT_FOR_FAB",
      "source_sha256":sha(P.SOURCE),
      "candidate_sha256":sha(TARGET),
      "candidate_drc_sha256":sha(RAW_DRC),
      "native_before_drc":old,"native_after_drc":new,
      "real_connection_errors_removed":183-new["Connection Error"],
      "native_saved_reopened":True,
      "number_of_direct_pad_pairs":6,
      "beta_autorouter_used":False,
      "100a_two_pole_copper_qualified":False,
      "magnet_terminals_qualified":False,
      "real_72_part_Cout_qualified":False,
      "fabrication_approved":False
    }

def apply()->int:
    plan=P.report()
    if plan["preflight_problems"]:
        raise ValueError("Actual 132-line physical copper/magnet clearance check failed")
    if TARGET.exists():
        raise FileExistsError("Refusing to overwrite existing native direct-route candidate "+str(TARGET))
    parent_sha=sha(P.SOURCE)
    if parent_sha!=P.EXPECTED_SHA:
        raise ValueError("Verified 132-line original has changed")
    # Uses the SAME working native EasyEDA PrimitiveLine.create path that
    # produced the accepted 107->132 source in PR95. Does NOT invoke beta.
    if E.apply(P,P.SOURCE,PREFIX):
        raise RuntimeError("Native EasyEDA could not save/reopen/verify direct-route copy")
    if sha(P.SOURCE)!=parent_sha:
        raise ValueError("Source changed during native direct copper creation")
    result=subprocess.run([sys.executable,str(HERE/"run_driver_drc.py"),
                           "--board",str(TARGET),"--prefix",PREFIX+"_drc"],
                          check=False)
    if result.returncode:
        raise RuntimeError("Native DRC command failed; zero changes NOT assumed")
    d=compare_native_drc()
    DELTA.write_text(json.dumps(d,ensure_ascii=False,indent=2)+"\n",
                     encoding="utf-8",newline="\n")
    print(json.dumps(d,ensure_ascii=False,indent=2))
    return 0

def main()->int:
    ap=argparse.ArgumentParser(description=__doc__)
    g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check",action="store_true")
    g.add_argument("--emit-js",action="store_true")
    g.add_argument("--apply",action="store_true")
    args=ap.parse_args()
    if args.check:
        d=P.report()
        print(json.dumps(d,ensure_ascii=False,indent=2))
        return int(bool(d["preflight_problems"]))
    if args.emit_js:
        return P.main_from_native_export() if hasattr(P,"main_from_native_export") else _emit()
    return apply()

def _emit()->int:
    d=P.report()
    if d["preflight_problems"]:return 1
    print(P.R.emit_js(P.copper(),[]))
    return 0

if __name__=="__main__":
    raise SystemExit(main())

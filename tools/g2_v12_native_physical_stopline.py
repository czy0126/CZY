"""Fail-closed exact native EDA DRC blocker for saved V12.

DO NOT use as a fabrication release or as evidence of fixed copper. V12 has
two true native primary resonant traces, but one triggers its own board's
100mil maximum copper track width rule. V11 remains the most recent independently
reopened clean-physical-error candidate.

  python tools/g2_v12_native_physical_stopline.py --write
  python tools/g2_v12_native_physical_stopline.py --check
"""
from __future__ import annotations
import hashlib
import json
import argparse
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
G2=ROOT/"hardware/dcx_main/g2"
BOARD=G2/"dcx_main_board_g2_V12_NATIVE_PRIMARY_RESONANT_LINKS_NOT_FOR_FAB.eprj2"
BOARD_SHA="527280764de6121b3a6f3eb5bbc1bac7ee72f8714e0c4be4f7a7a1f8087d1a4e"
PARENT=G2/"dcx_main_board_g2_V11_NATIVE_SR_GATE_ESCAPE_NOT_FOR_FAB.eprj2"
PARENT_SHA="d90ca22079ad7245e8c3904eb8369da58c705ae39b56574bf7843dad34cad89b"
APPLIED=G2/"g2_v12_primary_copper_native_applied_NOT_FOR_FAB.json"
NATIVE_READBACK=G2/"g2_v12_native_readback_before_drc_NOT_FOR_FAB.json"
NATIVE_DRC=G2/"g2_v12_native_gui_DRC_after_readback_NOT_FOR_FAB.json"
OUT=G2/"g2_v12_primary_width_release_stopline_NOT_FOR_FAB.json"
TRACE_ID="25fcbfaa23a768e3"

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def build():
    if sha(BOARD)!=BOARD_SHA or sha(PARENT)!=PARENT_SHA:
        raise ValueError("Saved native V12 or qualified V11 source changed; new review required")
    applied=json.loads(APPLIED.read_text("utf8"))
    native=json.loads(NATIVE_READBACK.read_text("utf8"))
    drc=json.loads(NATIVE_DRC.read_text("utf8"))
    if (not applied["native_reply"]["all_created"] or
        len(applied["native_reply"]["created"])!=2 or
        any(not x["ok"] for x in applied["native_reply"]["created"]) or
        len(native["value"]["lines"])!=467 or
        native["source_sha256"]!=BOARD_SHA or
        drc["native_categories"]!={"Physical Error":1,"Connection Error":145,"Netlist Error":1}):
        raise ValueError("Actual native V12 source/DRC evidence incomplete or changed")
    physical=next(x for x in drc["response"]["value"]["raw"] if x["name"]=="Physical Error")
    errors=[p for sub in physical["list"] for p in sub["list"]]
    if len(errors)!=1:
        raise ValueError("Physical errors are not exactly known")
    x=errors[0]
    data=x["explanation"]["errData"]
    if (data["obj1"]!=TRACE_ID or x["ruleName"]!="copperThickness1oz" or
        data["maxWidth"]!=10 or data["width"]<=10 or x["layer"]!="Top Layer"):
        raise ValueError("Track rule/affected object not source confirmed")
    pad=next(l for l in native["value"]["lines"] if l["id"]==TRACE_ID)
    if pad["net"]!="PRI_T1" or abs(pad["width"]*.0254-3.)>.0001:
        raise ValueError("Observed 3mm primary track not source confirmed")
    return {
      "schema":"G2_V12_SAVED_NATIVE_TRACK_OVERWIDTH_STOPLINE_V1",
      "status":"NATIVE_V12_HAS_PHYSICAL_ERROR_1_MUST_NOT_RELEASE",
      "saved_native_V12_sha256":BOARD_SHA,
      "last_physically_clean_independently_reopened_native_V11_sha256":PARENT_SHA,
      "native_DRC":drc["native_categories"],
      "connection_error_decrease_from_V11":4,
      "actual_two_native_tracks_created":True,
      "offending_native_trace_id":TRACE_ID,
      "offending_net":"PRI_T1",
      "width_current_mm":round(pad["width"]*.0254,6),
      # EasyEDA DRC errData reports this rule in 10-mil units; UI lists 100mil.
      "width_rule_max_mm":round(data["maxWidth"]*.254,4),
      "width_rule_max_mil":data["maxWidth"]*10,
      "width_proposed_mm":2.5,
      "proposed_solution_method":
         "Modify ONLY existing trace UUID's lineWidth via pcb_PrimitiveLine.modify; do not recreate other traces; use already-alive V12 GUI, require exact old net/geometry and readback",
      "unperformed_native_modify_attempt_proven":False,
      "source_V12_final_DRC_qualified":False,
      "required_release_conditions":[
         "Native lineWidth of PRI_T1 trace set to 2.5mm and real EasyEDA get readback",
         "Fresh V12 native DRC Physical Error 0, Connection Error <=145 and Netlist Error <=1",
         "Saved V12 source hash changes without modifying V11/V10 originals",
         "Independent fresh GUI reopen checks actual PCB and COUT72 schematic, original sessions preserved",
         "Manufacturer magnetics 24 physical terminal/DOT and 100A copper/thermal/16mm/DFM and D0 protection remain separate"
      ],
      "fab_release":"NOT_FOR_FAB",
      "fabrication_approved":False
    }

def main():
    p=argparse.ArgumentParser()
    x=p.add_mutually_exclusive_group(required=True)
    x.add_argument("--write",action="store_true")
    x.add_argument("--check",action="store_true")
    a=p.parse_args()
    raw=json.dumps(build(),ensure_ascii=False,indent=2)+"\n"
    if a.write:OUT.write_text(raw,encoding="utf8",newline="\n")
    elif not OUT.exists() or OUT.read_text("utf8")!=raw:
        raise SystemExit("Native V12 fail-closed DRC stopline stale/missing")
    print(json.dumps({"status":build()["status"],"native_DRC":build()["native_DRC"],
      "trace_id":TRACE_ID,"fab_release":False},ensure_ascii=False,indent=2))
if __name__=="__main__":
    main()

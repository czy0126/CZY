"""Validate saved KiCad V17 OEM-72 and partial primary copper stages without approving fabrication."""
from __future__ import annotations
import argparse
import collections
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
G=Path("hardware/dcx_main/g2")
STAGES=(
("oem","dcx_main_board_g2_V17_OEM_T530_72_INTEGRATED_NOT_FOR_FAB.kicad_pcb","g2_v17_OEM_T530_72_integrated_native_DRC_NOT_FOR_FAB.json",9),
("vin","dcx_main_board_g2_V17_OEM_T530_72_VIN_INPUT_CANDIDATE_NOT_FOR_FAB.kicad_pcb","g2_v17_OEM_T530_72_VIN_input_native_DRC_NOT_FOR_FAB.json",8),
("sw","dcx_main_board_g2_V17_OEM_T530_72_VIN_SW_CANDIDATE_NOT_FOR_FAB.kicad_pcb","g2_v17_OEM_T530_72_VIN_SW_native_DRC_NOT_FOR_FAB.json",7),
)
REPORT=G/"g2_v17_OEM_T530_72_VIN_SW_consolidated_gate_NOT_FOR_FAB.json"
PARENT_SHA="2cbf559bd7fd67c1673d54cb36048dda7cbcf7e742a2fedb6930ed9c7553986f"
OEM_SHA="edddfa63c335de77b9f4c9a09d800bf67a89a9b15a92984e778fe88861b96257"

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def obj(path):
    d=json.loads(path.read_text("utf8"))
    if not isinstance(d,dict):raise ValueError("Expected JSON object")
    return d

def by_net(d):
    counts=collections.Counter()
    for i in d["unconnected_items"]:
        names=set()
        for item in i["items"]:
            m=re.findall(r"\[([^\]]+)\]",item["description"])
            if m:names.add(m[-1])
        if len(names)!=1:raise ValueError(f"Ambiguous unconnected net {names}")
        counts[names.pop()]+=1
    return dict(sorted(counts.items()))

def audit(root=ROOT):
    g=root/G
    parent=g/"dcx_main_board_g2_V17_KICAD_PGND_VOUT_WIP_NOT_FOR_FAB.kicad_pcb"
    oemlib=g/"oem_footprints/CZY_OEM.pretty/KEMET_T530X_7343_43_OEM_B.kicad_mod"
    if sha(parent)!=PARENT_SHA or sha(oemlib)!=OEM_SHA:
        raise ValueError("Frozen parent board or manufacturer land footprint changed")
    receipts=(
        obj(g/"g2_v17_OEM_T530_72_integrated_native_receipt_NOT_FOR_FAB.json"),
        obj(g/"g2_v17_OEM_T530_72_VIN_input_native_receipt_NOT_FOR_FAB.json"),
        obj(g/"g2_v17_OEM_T530_72_VIN_SW_native_receipt_NOT_FOR_FAB.json"),
    )
    stages=[]
    for name,pcb,drc,expected in STAGES:
        path=g/pcb
        dpath=g/drc
        raw=obj(dpath)
        if raw.get("source")!=pcb:raise ValueError(f"{name}: source PCB mismatch")
        if len(raw.get("violations",[]))!=0:raise ValueError(f"{name}: new DRC violations")
        if len(raw.get("unconnected_items",[]))!=expected:raise ValueError(f"{name}: unconnected count changed")
        stages.append({
            "name":name,"board_file":pcb,"board_sha256":sha(path),
            "drc_file":drc,"drc_sha256":sha(dpath),
            "rule_violations":len(raw["violations"]),
            "unconnected":expected,"unconnected_by_net":by_net(raw),
            "ignored_drc_checks":[e.get("key") for e in raw.get("ignored_checks",[])],
        })
    if stages[0]["board_sha256"]!=receipts[0]["candidate_board_sha256"]:
        raise ValueError("OEM merged PCB disagrees with source-locked receipt")
    if stages[1]["board_sha256"]!=receipts[1]["candidate_sha256"]:
        raise ValueError("VIN PCB disagrees with receipt")
    if stages[2]["board_sha256"]!=receipts[2]["candidate_sha256"]:
        raise ValueError("SW PCB disagrees with receipt")
    if receipts[1]["parent_sha256"]!=stages[0]["board_sha256"] or receipts[2]["parent_sha256"]!=stages[1]["board_sha256"]:
        raise ValueError("Input dependencies are not the actual prior candidate")
    if receipts[0]["oem_replaced_count"]!=72 or receipts[0]["oem_180deg_rotated_count"]!=36:
        raise ValueError("OEM array / polarity rotation changed")
    if not receipts[0]["all_original_ref_pin_net_multisets_preserved"]:
        raise ValueError("Net identity parity no longer confirmed")
    if stages[0]["unconnected_by_net"].get("VIN_P")!=2 or stages[-1]["unconnected_by_net"].get("VIN_P")!=1:
        raise ValueError("VIN route not actually closed")
    if stages[0]["unconnected_by_net"].get("SW")!=3 or stages[-1]["unconnected_by_net"].get("SW")!=2:
        raise ValueError("SW route not actually closed")
    return {
        "schema":"d1_v17_oem72_partial_copper_gate/1",
        "status":"WIP_NOT_FOR_FAB",
        "parent_board_sha256":sha(parent),
        "oem_land_sha256":sha(oemlib),
        "replaced_oem_footprints":72,
        "rotated_180_for_net_polarity":36,
        "stages":stages,
        "remaining_current_candidate_unconnected":7,
        "remaining_missing_magnetics":["CT","T1","T2","T3","T4"],
        "remaining_blockers":[
            "Full source schematic-to-PBC parity and physical magnetic windings not verified",
            "Cin positive and complete QH/QL SW hot loop are not closed",
            "SW Cr 0.8mm pad transition current and thermal rating not verified",
            "Five KiCad DRC checks remain ignored, OEM Courtyard and 12-layer fab rules require review",
            "Full 100A dual-pole bus, current sharing, transient protection, EMC and cooling unqualified",
            "Complete-product density at or above 2W/cm3 not demonstrated",
        ],
        "fab_release":False,
    }

def main(argv=None):
    a=argparse.ArgumentParser()
    mx=a.add_mutually_exclusive_group(required=True)
    mx.add_argument("--write",action="store_true")
    mx.add_argument("--check",action="store_true")
    opts=a.parse_args(argv)
    try:
        result=audit()
        expected=json.dumps(result,indent=2,ensure_ascii=False)+"\n"
        target=ROOT/REPORT
        if opts.write:target.write_text(expected,encoding="utf8")
        if opts.check and target.read_text("utf8")!=expected:raise ValueError("Stale artifact; run --write")
        print(json.dumps({"status":result["status"],"oem":result["replaced_oem_footprints"],"unconnected":result["remaining_current_candidate_unconnected"]}))
    except (ValueError,OSError,TypeError,KeyError) as ex:
        print("Invalid native evidence:",ex,file=sys.stderr)
        return 1
    return 0

if __name__=="__main__":sys.exit(main())

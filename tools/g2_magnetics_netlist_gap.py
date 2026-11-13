"""Source-locked native schematic/PCB component inventory reconciliation for G2 D1.

A single Netlist DRC error aggregates discrepancies; the five absent
magnetics are *observed inventory discrepancies*, not proof they are the only
cause. R6 is intentionally unplaced (DNP); Cout72 parts are on a second sheet.
Never clear native Netlist DRC by suppressing/importing wrong footprints.

python tools/g2_magnetics_netlist_gap.py --write
python tools/g2_magnetics_netlist_gap.py --check
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
G2=ROOT/"hardware/dcx_main/g2"
SCHEM=G2/"g2_v12_P1_actual_native_schematic_readonly_NOT_FOR_FAB.json"
PCB=G2/"g2_v11_independent_native_full_readback_NOT_FOR_FAB.json"
PINS=G2/"g2_five_magnetics_24_logical_pin_native_parity_NOT_FOR_FAB.json"
MAG_SCH=G2/"g2_v12_P1_magnetics_native_wires_24pin_readonly_NOT_FOR_FAB.json"
NATIVE_PCB_NETLIST=G2/"g2_v13_PCB_actual_netlist_readonly_NOT_FOR_FAB.json"
EVIDENCE=G2/"g2_five_magnetics_native_netlist_component_gap_NOT_FOR_FAB.json"
SAVED_SHA="d90ca22079ad7245e8c3904eb8369da58c705ae39b56574bf7843dad34cad89b"
MAGNETICS={"CT","T1","T2","T3","T4"}


def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def build():
    schem=json.loads(SCHEM.read_text("utf8"))["value"]
    board=json.loads(PCB.read_text("utf8"))
    pinout=json.loads(PINS.read_text("utf8"))
    magnetic_schematic=json.loads(MAG_SCH.read_text("utf8"))["readback"]
    actual=json.loads(NATIVE_PCB_NETLIST.read_text("utf8"))["readback"]
    native=json.loads(actual["netlist"])
    if board["source_native_sha256"]!=SAVED_SHA or pinout["source_sha256"]["native_V11_saved_eprj2"]!=SAVED_SHA:
        raise ValueError("Native saved PCB origin SHA drift")
    if len(schem["components"])!=83 or schem["wires"]!=280:
        raise ValueError("Actual native P1 symbolic inventory changed")
    if len(board["real_native_data"]["components"])!=149 or actual["components"]!=149 or (
        actual["lineCount"]!=465):
        raise ValueError("Native PCB CAD readback not source bound")
    schematic_refs=[d["ref"] for d in schem["components"]]
    pcb_refs=[d["ref"] for d in board["real_native_data"]["components"]]
    if len(set(schematic_refs))!=83 or len(set(pcb_refs))!=149:
        raise ValueError("Duplicate PCB or P1 designators cannot reconcile safely")
    sch=set(schematic_refs);pcb=set(pcb_refs)
    missing=sch-pcb
    cout=pcb-sch
    if missing!=MAGNETICS|{"R6"} or cout!={f"CHB{i:02d}" for i in range(1,73)}:
        raise ValueError("PCB/P1 delta beyond expected magnetics/R6/COUT72")
    marked=[d for d in magnetic_schematic["devices"] if d["ref"] in MAGNETICS]
    if len(marked)!=5 or any(d["footprint"]!={"uuid":""} for d in marked):
        raise ValueError("Five missing native magnetics have changed, do not stale-report")
    # Independent native PCB Netlist serialization returned 149 actual components,
    # so this is not an offline-only component counting guess.
    if not isinstance(native["components"],dict) or len(native["components"])!=149:
        raise ValueError("Live EDA PCB_Net.getNetlist() disagrees with raw native PCB readback")
    from_netlist={c.get("props",{}).get("Designator") for c in native["components"].values()}
    if from_netlist!=pcb:
        raise ValueError("Native saved board readback disagrees with live PCB Netlist")
    if pinout["real_electrical_pin_count"]!=24 or pinout["vendor_mechanical_pin_numbers_confirmed"]!=0:
        raise ValueError("Vendor 24-pin signoff unresolved or changed")
    return {
      "schema":"D1_G2_FIVE_MAGNETICS_NATIVE_COMPONENT_AND_NETLIST_GAP_V1",
      "status":"NATIVE_DRC_NETLIST_UNRESOLVED_AT_LEAST_FIVE_MISSING_LINKED_DEVICES",
      "provenance_sha256":{"native_P1_readback":digest(SCHEM),
       "native_P1_five_magnetics_symbols_and_wires":digest(MAG_SCH),
       "native_independent_PCB_readback":digest(PCB),
       "native_actual_PCB_netlist":digest(NATIVE_PCB_NETLIST),
       "vendor_request_24pin_manifest":digest(PINS)},
      "schematic_P1_component_count":83,
      "schematic_COUT_T530_72_component_count":72,
      "schematic_combined_component_count":155,
      "intentional_R6_DNP":1,
      "missing_native_magnetic_device_count":5,
      "expected_PCB_components_excluding_DNP_and_unplaced_magnetics":149,
      "actual_saved_native_PCB_component_count":149,
      "actual_EDA_PCB_netlist_component_count":149,
      "absent_from_native_PCB_relative_to_P1":sorted(missing),
      "native_PCB_second_sheet_extra_designators":sorted(cout),
      "magnetics_schematic_pin_count":24,
      "all_24_schematic_native_PCB_raw_landing_net_matches":True,
      "missing_real_magnetics_sch_footprint_associations":sorted(MAGNETICS),
      "vendor_signed_terminal_count":0,
      "native_netlist_Error_existing":1,
      "native_netlist_Error_clearance_proven":False,
      "native_pinout_registration_unverified":True,
      "warning":"Netlist DRC groups all discrepancies; matching counts after replacing five parts cannot guarantee native Import Changes netlist DRC=0. Must independently rerun native PCB DRC after actual real device footprint association.",
      "required_real_release":"Only after five real PCB components and SCH device footprint association, verified 24 terminal pin↔native pad↔vendor drawing, and native PCB DRC Netlist=0, Connection=0 and Physical=0.",
      "fabrication_approved":False
    }


def main():
    p=argparse.ArgumentParser()
    z=p.add_mutually_exclusive_group(required=True)
    z.add_argument("--write",action="store_true")
    z.add_argument("--check",action="store_true")
    a=p.parse_args()
    content=json.dumps(build(),indent=2,ensure_ascii=False)+"\n"
    if a.write:
        if EVIDENCE.exists() and EVIDENCE.read_text("utf8")!=content:
            raise ValueError("Do not overwrite previous netlist gap evidence")
        EVIDENCE.write_text(content,encoding="utf8",newline="\n")
    elif not EVIDENCE.exists() or EVIDENCE.read_text("utf8")!=content:
        raise ValueError("Netlist gap evidence missing or stale")
    result=build()
    print(json.dumps({k:result[k] for k in ("status","missing_native_magnetic_device_count",
         "actual_EDA_PCB_netlist_component_count","native_netlist_Error_existing",
         "fabrication_approved")},ensure_ascii=False))


if __name__=="__main__":
    main()

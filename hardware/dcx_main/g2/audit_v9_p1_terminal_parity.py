"""Reconcile actual G2 V9 native PCB pads against source-validated P1 schematic.

Uses immutable *real* native EasyEDA board readback and historical P1 SCH
captured through sch primitives, not invented reference netlists. The frozen
G1 P1 is a BASELINE, not proof that current V9 P1 has not changed.
Magnetics are 24 bare pads with nets but are NOT native components. Never
turn this diagnostic into manufacturing clearance.

  python hardware/dcx_main/g2/audit_v9_p1_terminal_parity.py --write
  python hardware/dcx_main/g2/audit_v9_p1_terminal_parity.py --check
"""
from __future__ import annotations
import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PCB = HERE / "dcx_main_board_g2_T530_OEM_DENSITY_B_V9_REAL_72_COMPONENT_TRIAL_NOT_FOR_FAB.eprj2"
NATIVE = HERE / "g2_v9_live_native_full_readback_20261112_NOT_FOR_FAB.json"
INDEPENDENT = HERE / "g2_v9_independent_gui_reopen_v2_verified_NOT_FOR_FAB.json"
G1_SCH = ROOT / "hardware/dcx_main/g1/g1_live_netlist.json"
G1_P1 = ROOT / "hardware/dcx_main/g1/dcx_main_board_g1_lr_repack.eprj2"
HISTORICAL_R8_ECO = ROOT / "hardware/dcx_main/gen/r8_eco_run_2026-11-06.json"
R6_V9_NATIVE = HERE / "g2_v9_p1_r6_dnp_native_verification_NOT_FOR_FAB.json"
OUT = HERE / "g2_v9_p1_magnetic_terminal_gap_NOT_FOR_FAB.json"
NATIVE_SHA = "d26197ca04d986d010e9a6af096a6b71edbb188e1b076c41e1ff8e21ce0a43a2"
MAGS = ["T1", "T2", "T3", "T4", "CT"]
PARTS = {"T1":5,"T2":5,"T3":5,"T4":5,"CT":4}
PAD_QTY = 24
CHB = {f"CHB{i:02d}" for i in range(1,73)}


def sha(p:Path):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def source():
    if sha(PCB)!=NATIVE_SHA:
        raise ValueError("Original saved V9 PCB bytes changed; refuse stale audit")
    captured=json.loads(NATIVE.read_text("utf8"))
    a=json.loads(INDEPENDENT.read_text("utf8"))
    if captured.get("source_sha256")!=NATIVE_SHA or captured.get("native_counts")!={
         "components":149,"pads":443,"lines":407,"vias":93,"nets":65
    }:
        raise ValueError("Captured V9 PCB readback does not match saved native CAD")
    if a.get("status")!="INDEPENDENT_NATIVE_GUI_REOPEN_VERIFIED_NOT_FOR_FAB" or a.get("native_drc")!={"Connection Error":168,"Netlist Error":1}:
        raise ValueError("No real independent V9 native reopen+DRC evidence")
    if not a["native_saved_source_unchanged"] or not a["other_gui_preserved"]:
        raise ValueError("Source or GUI state drift in independent verification")
    schematic=json.loads(G1_SCH.read_text("utf8"))
    if schematic.get("page")!="P1" or schematic.get("designators")!=83 or schematic.get("wire_count")!=280:
        raise ValueError("Historical P1 native capture changed or is incomplete")
    if sha(G1_P1)!=schematic["board_sha256"]:
        raise ValueError("P1 schematic historical source CAD SHA mismatch")
    if len(schematic["netlist"])!=83:
        raise ValueError("P1 schematic missing native components")
    return captured["value"],schematic,a


def mm(p):
    return [round(p["X"]*.0254,5),round(-p["Y"]*.0254,5)]


def report():
    pcb,sch,reopen=source()
    expected=sch["netlist"]
    byref=defaultdict(lambda: defaultdict(list))
    pads=pcb["pads"]
    for p in pads:
        if p.get("ref") and p.get("PadNumber"):
            byref[p["ref"]][str(p["PadNumber"])].append(p["Net"])
    refs=set(byref)
    missing=sorted(set(expected)-refs)
    if missing!=sorted(MAGS+["R6"]):
        raise ValueError("Unaccounted source reference gap: "+str(missing))
    if refs-set(expected)!=CHB:
        raise ValueError("Unexpected PCB-only component refs (not Cout72)")
    disagreements=[]
    matching=0
    for ref,physical in expected.items():
        if ref not in byref:continue
        for pin,net in physical.items():
            found=byref[ref].get(str(pin),[])
            if not found or set(found)!={net}:
                disagreements.append({"ref":ref,"pin":str(pin),
                     "expected_net":net,"pcb_nets":sorted(set(found))})
            else:matching+=1
    if disagreements:
        raise ValueError("Existing native P1 pin-net mismatch: "+str(disagreements[:5]))
    bare=[p for p in pads if not p.get("ref")]
    if len(bare)!=PAD_QTY:
        raise ValueError("Unexpected bare pads count: "+str(len(bare)))
    order=["T1"]*5+["T2"]*5+["T3"]*5+["T4"]*5+["CT"]*4
    native_magnet=[]
    for ref,q in zip(order,bare):
        terminal=str(q["PadNumber"])
        expect=expected[ref]
        if terminal not in expect or q["Net"]!=expect[terminal]:
            raise ValueError("Bare magnetic pad cannot be matched to P1 terminal "+
                             str((ref,terminal,q["Net"],expect)))
        native_magnet.append({
            "ref":ref,"terminal":terminal,"net":q["Net"],"xy_mm":mm(q),
            "native_layer":q["Layer"],"pad_shape":q["Pad"],
            "component_owned":False,"physical_drawing_from_vendor_signed":False,
            "terminal_dot_signed":False
        })
    if len({(x["ref"],x["terminal"]) for x in native_magnet})!=24:
        raise ValueError("Duplicated magnetic logical terminal in physical pad arrangement")
    bymag=Counter(x["ref"] for x in native_magnet)
    if dict(bymag)!=PARTS:
        raise ValueError("Incorrect 5 transformer/CT pad totals")
    magnetic_pin_nets={ref:dict(expected[ref]) for ref in MAGS}
    # Full device-by-device pairing of the real second page is independently
    # certified by the V9 reopen; here enforce native footprint pins as well.
    for ref in sorted(CHB):
        q=byref[ref]
        if set(q)!={"1","2"} or q["1"]!=["VOUT"] or q["2"]!=["PGND"]:
            raise ValueError("Native CHB pad/net parity drift at "+ref)
    old_r8=json.loads(HISTORICAL_R8_ECO.read_text("utf8"))
    phase3=old_r8.get("phase_3_reopen",{})
    alias=sch.get("excluded_pullup",{})
    if (phase3.get("status")!="ALREADY_DNP"
        or phase3.get("before")!={"addIntoBom":False,"addIntoPcb":False}
        or old_r8.get("phase_1_verify",{}).get("pin_map",{}).get("pullup",{}).get("pads")!=expected["R6"]
        or alias.get("capture_designator")!="R6"
        or alias.get("historical_designator")!="R8"
        or alias.get("same_wiring_as_historical_r8") is not True):
        raise ValueError("R6 historical R8 DNP/provenance mismatch")
    current=json.loads(R6_V9_NATIVE.read_text("utf8"))
    native_r6=current.get("native_P1",{}).get("R6",{})
    if (current.get("status")!="NATIVE_V9_P1_R6_FLAGS_READBACK_VERIFIED_NOT_FOR_FAB"
        or current.get("source_sha256")!=NATIVE_SHA
        or current.get("source_unchanged") is not True
        or current.get("clone_bytes_unchanged") is not True
        or current.get("original_gui_preserved") is not True
        or current.get("own_verification_GUI_closed") is not True
        or current.get("R6_true_current_DNP") is not True
        or current.get("R6_present_on_real_PCB") is not False
        or current.get("native_P1",{}).get("native_schematic_component_count")!=83
        or native_r6.get("primitive_id")!=phase3.get("primitive_id")
        or native_r6.get("schematic_pin_numbers")!=["1","2"]
        or native_r6.get("addIntoPcb") is not False
        or native_r6.get("addIntoBom") is not False):
        raise ValueError("Current saved V9 native R6 DNP verification inconsistent")
    return {
        "schema":"G2_V9_P1_NATIVE_PAD_TERMINAL_RECONCILIATION_V1",
        "status":"FIVE_MAGNETIC_NATIVE_COMPONENTS_MISSING_R6_CONFIRMED_DNP_NOT_FOR_FAB",
        "v9_source_native_sha256":NATIVE_SHA,
        "historical_p1_source_sha256":sha(G1_P1),
        "historical_p1_netlist_sha256":sha(G1_SCH),
        "cross_version_assumption_not_yet_revalidated":
           "P1 in G2 V9 must be independently recaptured and compared to frozen G1 P1; V9 COUT72 page is independently checked.",
        "p1_schematic_refs":len(expected),
        "p1_schematic_wires":sch["wire_count"],
        "p1_schematic_native_snapshot_source":"G1_P1_83_REF_280_WIRE",
        "real_pcb_component_refs":len(refs),
        "p1_refs_with_matching_real_pcb_component":len(set(expected)&refs),
        "p1_connected_pin_net_matches":matching,
        "p1_connected_pin_net_disagreements":disagreements,
        "p1_reference_missing_native_components":missing,
        "p1_intentional_DNP_ref_no_PCB_component":["R6"],
        "p1_required_native_component_gaps":sorted(MAGS),
        "r6_required_pin_nets":expected["R6"],
        "r6_native_component_present":False,
        "r6_historical_r8_reference_DNP":True,
        "r6_historical_r8_eco_sha256":sha(HISTORICAL_R8_ECO),
        "r6_old_R8_renaming_proven_by_pin_net":True,
        "r6_v9_P1_addIntoPcb_verified":False,
        "r6_v9_P1_addIntoBom_verified":False,
        "r6_must_be_assembled":False,
        "r6_current_native_primitive_id":native_r6["primitive_id"],
        "r6_current_native_readback_sha256":sha(R6_V9_NATIVE),
        "r6_action":"R6 is a proven intentional DNP in saved V9 P1. Keep both native BOM/PCB exclusion flags false and preserve its historical R8 ECO; no physical PCB R6 footprint required.",
        "magnetics_required_pin_nets":magnetic_pin_nets,
        "magnetics_bare_pad_count":len(native_magnet),
        "magnetics_bare_pads_with_matching_pin_and_net":24,
        "magnetics_native_component_instances":0,
        "magnetics_bare_pad_to_component_assignments":native_magnet,
        "cout72_component_and_144_native_pin_pair_verified":True,
        "native_drc_connection_errors":reopen["native_drc"]["Connection Error"],
        "native_drc_netlist_errors":reopen["native_drc"]["Netlist Error"],
        "physical_component_gate_passed":False,
        "magnetic_vendor_terminal_geometry_and_dot_approved":False,
        "r6_real_mpn_footprint_and_position_approved":False,
        "native_new_component_save_and_independent_reopen_verified":False,
        "safety_fault_matrix_verified":False,
        "fabrication_approved":False,
        "next_required_actions":[
            "Native V9 P1 rescan: independently verify no P1 changes since G1 source",
            "Current native V9 R6 DNP flags proven false/false, identical primitive ID to prior R8 ECO; maintain intentional unpopulated R6, do not invent a physical PCB component",
            "Create T1-T4 and CT *native devices* with manufacturer physical pin/DOT proof; reuse actual 24 net-matched pad locations only after approved terminal geometry",
            "Rebuild editable new V11 PCB and synchronize schematic before native DRC",
            "Close remaining native connection and netlist errors and verify independently; four-wire/thermal/DFM and D0 remain separately required"
        ]
    }


def main():
    arg=argparse.ArgumentParser()
    x=arg.add_mutually_exclusive_group(required=True)
    x.add_argument("--write",action="store_true")
    x.add_argument("--check",action="store_true")
    o=arg.parse_args()
    doc=report()
    body=json.dumps(doc,ensure_ascii=False,indent=2)+"\n"
    if o.write:OUT.write_text(body,encoding="utf8",newline="\n")
    elif not OUT.exists() or OUT.read_text("utf8")!=body:
        raise ValueError("Source-locked native P1/PCB terminal reconciliation is stale")
    print(json.dumps({"source_sha":NATIVE_SHA,"expected":doc["p1_schematic_refs"],
      "real_p1_component_refs":doc["p1_refs_with_matching_real_pcb_component"],
      "matching_pins":doc["p1_connected_pin_net_matches"],
      "missing_refs":doc["p1_reference_missing_native_components"],
      "bare_magnetics":doc["magnetics_bare_pad_count"],
      "native_drc":{"Connection Error":doc["native_drc_connection_errors"],
      "Netlist Error":doc["native_drc_netlist_errors"]},
      "fabrication_approved":False},ensure_ascii=False,indent=2))
if __name__=="__main__":
    main()

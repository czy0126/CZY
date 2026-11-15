"""Immutable V17 Lane-A electrical connectivity checkpoint.

This gates an actual saved KiCad 10 PCB and its independent kicad-cli DRC.
A DRC 0/0 is NOT power-on authority: five magnetics + schematic parity,
OEM U1 via-in-pad, high-frequency loop / current / insulation remain open.
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"hardware/dcx_main/g2/dcx_main_board_g2_V17_OEM_T530_72_VIN_SW_CANDIDATE_NOT_FOR_FAB.kicad_pcb"
G=ROOT/"hardware/dcx_main/g2/d1_lane_a_connectivity"
BOARD=G/"six_net_trial_04_NOT_FOR_FAB.kicad_pcb"
DRC=G/"six_net_trial_04_DRC_NOT_FOR_FAB.json"
RECEIPT=G/"six_net_trial_04_NOT_FOR_FAB.receipt.json"
OUT=G/"d1_lane_a_0_0_source_locked_gate_NOT_FOR_FAB.json"
BASE_SHA="4bdb3492959aa08e70716a0f6ca020fe8cf98da66f08c795b72f8172b5ab50f9"
BOARD_SHA="85fff295c2c8bd594266881b711584be02b40b2158e266e8df4a2ba77d6bb76c"
DRC_SHA="53a8655f17712561035c024274944debf4ce7888c41123fda98f87d269a08d2b"
DRC_LF_SHA="47430c409cc6af1df90c403871c3ecb837cbf62c532034c33864adc43407135f"
REQUIRED_IGNORES={"missing_courtyard","track_not_centered_on_via",
                  "tuning_profile_track_geometries",
                  "footprint_filters_mismatch","footprint_type_mismatch"}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def run_audit():
    if sha(BASE)!=BASE_SHA:raise ValueError("Original V17 OEM board hash drift")
    if sha(BOARD)!=BOARD_SHA:raise ValueError("New native KiCad PCB changed: re-run DRC")
    # Git on Windows may write either LF or CRLF for JSON. Accept ONLY
    # the bytewise pinned report in one of those two line-ending forms.
    # Unlike a generic JSON reserialization this does not mask altered DRC.
    drc_bytes=DRC.read_bytes()
    lf=drc_bytes.replace(b"\r\n",b"\n")
    if hashlib.sha256(lf).hexdigest()!=DRC_LF_SHA or b"\r" in lf:
        raise ValueError("Native KiCad 10 DRC evidence changed")
    if hashlib.sha256(drc_bytes).hexdigest() not in (DRC_SHA,DRC_LF_SHA):
        raise ValueError("Unexpected DRC EOL representation")
    d=json.loads(DRC.read_text("utf8"))
    r=json.loads(RECEIPT.read_text("utf8"))
    if d["source"]!=BOARD.name:raise ValueError("DRC refers to a different PCB")
    if d["kicad_version"]!="10.0.6":raise ValueError("KiCad version changed")
    if d["violations"] or d["unconnected_items"]:raise ValueError("DRC is not zero/zero")
    if {x["key"] for x in d["ignored_checks"]}!=REQUIRED_IGNORES:
        raise ValueError("KiCad ignored checks changed")
    if r["source_sha256"]!=BASE_SHA or r["output_sha256"]!=BOARD_SHA:
        raise ValueError("CAD generator receipt does not agree with physical files")
    if set(r["nets"])!={"VIN_P","SW","HB","GH","GH_DRV","OC"}:
        raise ValueError("Expected six routed networks changed")
    if set(r["added_copper"])!={"VIN_P","SW","HB","GH","GH_DRV","OC","RT"}:
        raise ValueError("RT reroute or another net not recorded")
    if not r["reopened"] or not r["original_pin_nets_preserved"]:
        raise ValueError("Saved PCB physical pad parity was not checked")
    if r["fabrication_approved"] or r["current_rated"]:
        raise ValueError("Unsafe claim of electrical current or fabrication approval")
    return {
        "schema":"d1_v17_lane_a_electrical_connectivity/1",
        "status":"DRC_ZERO_ZERO_FOR_PRESENT_V17_KICAD_MODEL_NOT_FOR_FAB",
        "base_sha256":BASE_SHA,
        "board_sha256":BOARD_SHA,
        "native_drc_sha256":DRC_SHA,
        "native_drc_canonical_lf_sha256":DRC_LF_SHA,
        "tool":"KiCad 10.0.6 kicad-cli pcb drc --severity-all --format json",
        "source_native_counts":{"footprints":149,"pads":425,"copper_layers":12,"track_and_via_objects":529},
        "candidate_native_counts":{"footprints":149,"pads":425,"copper_layers":12,"track_and_via_objects":580},
        "routed_net_names":r["nets"],
        "low_current_rt_bottom_layer_rerouted":True,
        "enabled_rule_violations":0,
        "unconnected_in_current_partial_model":0,
        "ignored_drc_checks":sorted(REQUIRED_IGNORES),
        "magnetics_missing":["CT","T1","T2","T3","T4"],
        "schematic_full_parity_signed":False,
        "easyeda_g1_native_146_connection_errors_resolved":False,
        "U1_3_OC_via_in_pad_filled_capped_process_signed":False,
        "power_swich_loop_rms_copper_current_qualified":False,
        "SR_default_off_and_bench_fault_test_signed":False,
        "fabrication_approved":False,
        "power_on_approved":False,
    }
def main(argv=None):
    z=argparse.ArgumentParser()
    gr=z.add_mutually_exclusive_group(required=True)
    gr.add_argument("--write",action="store_true")
    gr.add_argument("--check",action="store_true")
    gr.add_argument("--require-release",action="store_true")
    args=z.parse_args(argv)
    try:
        d=run_audit()
        doc=json.dumps(d,indent=2,ensure_ascii=False)+"\n"
        if args.write:
            OUT.write_text(doc,encoding="utf8")
        if args.check and OUT.read_text("utf8")!=doc:raise ValueError("Stale receipt")
        if args.require_release:
            print("NOT_FOR_FAB / POWER-ON DENIED (magnetics, ERC, protection, current rating)")
            return 2
        print(json.dumps({"status":d["status"],"violations":0,"unconnected":0,
                          "missing_magnetics":len(d["magnetics_missing"])}))
        return 0
    except (OSError,ValueError,KeyError,TypeError) as e:
        print("Lane-A board release gate FAILED: ",e,file=sys.stderr)
        return 1
if __name__=="__main__":sys.exit(main())

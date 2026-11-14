"""Transplant all 72 OEM T530 land patterns into the source-locked V17 KiCad mainboard.

Run with KiCad 10 bundled Python, NOT Anaconda Python. This creates a *new*
editable native PCB and does not edit the original V17 board or EasyEDA file.
No manufacture approval: manufacturer-recommended land is not a qualified
thermal ESR, solderability, assembly, busbar or 100A design.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path
import sys

import pcbnew as pcb

ROOT = Path(__file__).resolve().parents[1]
G2 = ROOT / "hardware/dcx_main/g2"
PARENT = G2 / "dcx_main_board_g2_V17_KICAD_PGND_VOUT_WIP_NOT_FOR_FAB.kicad_pcb"
LIBRARY = G2 / "oem_footprints/CZY_OEM.pretty"
FOOTPRINT_NAME = "KEMET_T530X_7343_43_OEM_B"
OEM_FILE = LIBRARY / (FOOTPRINT_NAME + ".kicad_mod")
OUTPUT = G2 / "dcx_main_board_g2_V17_OEM_T530_72_INTEGRATED_NOT_FOR_FAB.kicad_pcb"
META = G2 / "g2_v17_OEM_T530_72_integrated_native_receipt_NOT_FOR_FAB.json"
DRC = G2 / "g2_v17_OEM_T530_72_integrated_native_DRC_NOT_FOR_FAB.json"
V17_SHA256 = "2cbf559bd7fd67c1673d54cb36048dda7cbcf7e742a2fedb6930ed9c7553986f"
OEM_SHA256 = "edddfa63c335de77b9f4c9a09d800bf67a89a9b15a92984e778fe88861b96257"
MPN = "T530X477M006ATE004"
COUNT = 72
MM = pcb.ToMM

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def fail(message: str):
    raise ValueError(message)

def xy(p):
    return (round(MM(p.x), 5), round(MM(p.y), 5))

def fp_pads(f):
    result = {}
    for pad in f.Pads():
        num = pad.GetNumber()
        if num in result:
            fail(f"Duplicate pad number {num} on {f.GetReference()}")
        result[num] = pad
    return result

def net_contract(board):
    return {
        f.GetReference(): sorted(
            (q.GetNumber(), q.GetNetname()) for q in f.Pads()
        )
        for f in board.GetFootprints()
    }

def native_summary(board):
    fps = list(board.GetFootprints())
    refs = [f.GetReference() for f in fps]
    if len(set(refs)) != len(refs):
        fail("Duplicate footprint references")
    result = {
        "footprints": len(fps),
        "pads": sum(len(list(f.Pads())) for f in fps),
        "tracks_and_vias": len(list(board.GetTracks())),
        "zones": len(list(board.Zones())),
        "copper_layers": board.GetCopperLayerCount(),
    }
    return result

def collect(board):
    fps = {f.GetReference(): f for f in board.GetFootprints()}
    refs = sorted(
        (ref for ref in fps if ref.startswith("CHB")),
        key=lambda ref: int(ref[3:]),
    )
    if refs != [f"CHB{i:02}" for i in range(1, COUNT+1)]:
        fail(f"Expected 72 source-locked CHB references, got {refs}")
    for ref in refs:
        netmap = [(q.GetNumber(), q.GetNetname()) for q in fps[ref].Pads()]
        if sorted(netmap) != [("1", "VOUT"), ("2", "PGND")]:
            fail(f"{ref} wrong net/polarity: {netmap}")
    return fps, refs

def load_oem():
    result = pcb.FootprintLoad(str(LIBRARY), FOOTPRINT_NAME)
    if result is None:
        fail(f"Missing KiCad library {OEM_FILE}")
    pads = fp_pads(result)
    if sorted(pads) != ["1", "2"]:
        fail("OEM footprint pad names changed")
    if abs(MM(pads["1"].GetSize().x) - 2.37) > 0.001:
        fail("OEM 2.37mm pad length drift")
    if abs(MM(pads["1"].GetSize().y) - 2.43) > 0.001:
        fail("OEM 2.43mm pad width drift")
    if abs(MM(pads["1"].GetPosition().x) + 3.12) > .002:
        fail("OEM VOUT pad orientation/position drift")
    if abs(MM(pads["2"].GetPosition().x) - 3.12) > .002:
        fail("OEM PGND pad orientation/position drift")
    return result

def apply():
    if sha(PARENT) != V17_SHA256:
        fail("V17 source KiCad CAD has changed; do not transplant")
    if sha(OEM_FILE) != OEM_SHA256:
        fail("Original OEM land file has changed; re-review datasheet")
    board = pcb.LoadBoard(str(PARENT))
    old_counts = native_summary(board)
    contract = net_contract(board)
    if old_counts != {
        "footprints":149, "pads":425, "tracks_and_vias":524,
        "zones":11,"copper_layers":12,
    }:
        fail(f"V17 source geometry changed {old_counts}")
    fps, refs = collect(board)
    template = load_oem()
    moves = []
    for ref in refs:
        old = fps[ref]
        oldpads = fp_pads(old)
        clone = pcb.FootprintLoad(str(LIBRARY), FOOTPRINT_NAME)
        clone.SetReference(ref)
        clone.SetValue(MPN)
        clone.SetPosition(old.GetPosition())
        # V17 CHB is a mirrored two-bank arrangement: the first 36
        # have pin 1 on the RIGHT even though source footprint angle=0.
        # Rotate the actual OEM land 180deg to preserve *physical* VOUT/PGND.
        # Never infer polarity from CHB number or from a GUI mirror flag.
        pin1_right = oldpads["1"].GetPosition().x > old.GetPosition().x
        pin2_right = oldpads["2"].GetPosition().x > old.GetPosition().x
        if pin1_right == pin2_right:
            fail(f"Cannot determine physical poles on {ref}")
        clone.SetOrientationDegrees(180 if pin1_right else 0)
        clone.Reference().SetVisible(False)
        clone.Value().SetVisible(False)
        newpads = fp_pads(clone)
        for num in ("1","2"):
            qold = oldpads[num]
            qnew = newpads[num]
            qnew.SetNet(qold.GetNet())
            dx=abs(MM(qnew.GetPosition().x-qold.GetPosition().x))
            dy=abs(MM(qnew.GetPosition().y-qold.GetPosition().y))
            if dx>.003 or dy>.003:
                fail(f"OEM {ref}.{num} differs from source pad at {dx:.5f},{dy:.5f}mm")
        moves.append({
            "ref":ref,
            "oem_rotation_deg":180 if pin1_right else 0,
            "xy_mm":list(xy(old.GetPosition())),
            "pad1_vout_xy_mm":list(xy(newpads["1"].GetPosition())),
            "pad2_pgnd_xy_mm":list(xy(newpads["2"].GetPosition())),
        })
        board.Remove(old)
        board.Add(clone)
    if net_contract(board)!=contract:
        fail("Native pin-to-net contract changed during OEM replacement")
    after = native_summary(board)
    if after != old_counts:
        fail(f"Count or layer drift after transplant {after}")
    pcb.ZONE_FILLER(board).Fill(board.Zones())
    pcb.SaveBoard(str(OUTPUT), board)
    reopened = pcb.LoadBoard(str(OUTPUT))
    if net_contract(reopened)!=contract:
        fail("Saved and reopened PCB pin-to-net drift")
    if native_summary(reopened)!=old_counts:
        fail("Saved/reopened board shape/layer count drift")
    # Native binary SHA is the final authoritative source for subsequent DRC.
    return {
        "schema":"g2_v17_t530_oem_integrated_mainboard/1",
        "status":"NATIVE_KICAD_OEM_72_REPLACED_PENDING_FULL_DRC_NOT_FOR_FAB",
        "source":"V17_KICAD_149_AND_T530_VENDOR_LAND_72",
        "source_board_sha256":sha(PARENT),
        "source_oem_footprint_sha256":sha(OEM_FILE),
        "candidate_board_sha256":sha(OUTPUT),
        "kicad_version":pcb.Version(),
        "source_counts":old_counts,
        "after_counts":after,
        "oem_mpn":MPN,
        "oem_replaced_count":len(moves),
        "oem_180deg_rotated_count":sum(x["oem_rotation_deg"]==180 for x in moves),
        "oem_positions":moves,
        "all_original_ref_pin_net_multisets_preserved":True,
        "original_v17_board_unchanged":sha(PARENT)==V17_SHA256,
        "vendor_pad_polarity_unverified_in_production":True,
        "magnetics_CT_T1_to_T4_present":False,
        "full_schematic_parity_proven":False,
        "100a_copper_thermal_current_sharing_proven":False,
        "fabrication_approved":False,
    }

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--create",action="store_true")
    parser.add_argument("--verify",action="store_true")
    args=parser.parse_args()
    if args.create == args.verify:
        parser.error("choose --create or --verify")
    if args.create:
        if OUTPUT.exists() or META.exists():
            fail("Candidate exists; refuse overwrite. Create a fresh named variant.")
        result=apply()
        META.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
        print(json.dumps({k:result[k] for k in ("status","candidate_board_sha256","oem_replaced_count","after_counts")}))
        return
    if not META.exists() or not OUTPUT.exists():
        fail("Missing candidate and receipt")
    data=json.loads(META.read_text("utf-8"))
    if sha(PARENT)!=data["source_board_sha256"] or sha(OEM_FILE)!=data["source_oem_footprint_sha256"]:
        fail("Input SHA drift")
    if sha(OUTPUT)!=data["candidate_board_sha256"]:
        fail("Generated CAD SHA drift")
    b=pcb.LoadBoard(str(OUTPUT))
    fps,refs=collect(b)
    if len(data["oem_positions"])!=COUNT or data["oem_180deg_rotated_count"]!=36:
        fail("Two-bank mirrored placement count drift")
    positions={q["ref"]:q for q in data["oem_positions"]}
    for ref in refs:
        f=fps[ref]
        if f.GetValue()!=MPN:
            fail("An OEM footprint reverted to provisional value")
        recorded=positions[ref]
        if xy(f.GetPosition())!=tuple(recorded["xy_mm"]):
            fail(f"Saved OEM {ref} site drift")
        if abs(f.GetOrientationDegrees()-recorded["oem_rotation_deg"])>.01:
            fail(f"Saved OEM {ref} polarity rotation drift")
        pads=fp_pads(f)
        for number,net,key in (("1","VOUT","pad1_vout_xy_mm"),
                               ("2","PGND","pad2_pgnd_xy_mm")):
            pad=pads[number]
            if pad.GetNetname()!=net or xy(pad.GetPosition())!=tuple(recorded[key]):
                fail(f"Saved OEM {ref}.{number} pad site/net drift")
            if abs(MM(pad.GetSize().x)-2.37)>.001 or abs(MM(pad.GetSize().y)-2.43)>.001:
                fail("Saved OEM pad dimensions drift")
    if native_summary(b)!=data["after_counts"]:
        fail("Saved CAD counts drift")
    print(json.dumps({"status":"VERIFIED_CANDIDATE_NOT_FOR_FAB",
                      "candidate_sha256":sha(OUTPUT),
                      "oem_count":len(refs)}))

if __name__=="__main__":
    try:
        main()
    except (ValueError,RuntimeError,OSError,KeyError) as exc:
        print(f"OEM T530 merge failure: {exc}",file=sys.stderr)
        sys.exit(1)

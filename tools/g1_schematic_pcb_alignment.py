"""Compare the saved native G1 schematic inventory with saved native G1 PCB pads.

The OLD exported November 6 schematic pin-net map is used ONLY as a historical
reference. It is not a fresh ERC/netlist and must never clear the single
native schematic-vs-PCB DRC error. Five magnetics currently use 24 anonymous
PCB free pads, not physical device footprints. The excluded R8 has been
renumbered R6 in the active schematic and must not be silently "fixed" by
placing R8 on the PCB.

python tools/g1_schematic_pcb_alignment.py --write
python tools/g1_schematic_pcb_alignment.py --check

Output is a diagnostic for G1 issue #9, never a manufacturing release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
G1 = ROOT / "hardware/dcx_main/g1"
HW = ROOT / "hardware/dcx_main"
INVENTORY = G1 / "g1_native_inventory_raw.json"
INVENTORY_AUDIT = G1 / "g1_native_inventory_bom_gate.json"
READBACK = G1 / "lr_repack_readback.json"
DRC = G1 / "lr_repack_drc_raw.json"
RECEIPT = G1 / "lr_repack_native_report.json"
BOARD = G1 / "dcx_main_board_g1_lr_repack.eprj2"
OLD_NETLIST = HW / "gen/netlist_export_raw.json"
OUT = G1 / "g1_schematic_pcb_alignment.json"
MAGNETS = ("CT", "T1", "T2", "T3", "T4")


def doc(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def fail_if_bad_native_capture() -> tuple[dict, dict, dict, dict]:
    receipt, inventory, pcb, drc = (doc(x) for x in
                                    (RECEIPT, INVENTORY, READBACK, DRC))
    board_sha = hashlib.sha256(BOARD.read_bytes()).hexdigest()
    if board_sha != receipt.get("candidate_sha256"):
        raise ValueError("Actual native G1 board differs from reopen SHA receipt")
    if receipt.get("candidate") != BOARD.relative_to(ROOT).as_posix():
        raise ValueError("Wrong native G1 candidate")
    if (inventory.get("ok") is not True
            or inventory.get("value", {}).get("status") != "INVENTORY"
            or inventory["value"].get("opened_by") != "path"
            or inventory["value"].get("project_name") != BOARD.stem):
        raise ValueError("Inventory is not from the active path-opened native G1")
    if pcb.get("ok") is not True or drc.get("ok") is not True:
        raise ValueError("Missing successful actual G1 PCB reopen or native DRC")
    read = pcb["value"]
    if (len(read["components"]) != receipt["components"]
            or len(read["pads"]) != receipt["pads"]
            or len(read["lines"]) != receipt["lines"]
            or len(read["nets"]) != receipt["nets"]
            or len(read["vias"]) != receipt["vias"]):
        raise ValueError("Native PCB primitive counts changed; recapture")
    if len(inventory["value"]["components"]) != inventory["value"]["primitive_count"]:
        raise ValueError("Native schematic inventory count changed")
    return receipt, inventory["value"], read, drc["value"]


def compare(components: list[dict], pcb_components: list[dict],
            pads: list[dict], legacy_refs: dict, drc_raw: list[dict]) -> dict:
    schematic_refs = [x["ref"] for x in components]
    pcb_refs = [x["ref"] for x in pcb_components]
    if len(set(schematic_refs)) != len(schematic_refs):
        raise ValueError("Duplicate native schematic designator")
    if len(set(pcb_refs)) != len(pcb_refs):
        raise ValueError("Duplicate native PCB designator")
    sch_by_ref = {x["ref"]: x for x in components}
    s_refs = set(schematic_refs)
    p_refs = set(pcb_refs)
    free_pads, placed_pads = [], []
    for pad in pads:
        ref = pad.get("ref")
        if ref is None or ref == "":
            free_pads.append(pad)
        elif ref in p_refs:
            placed_pads.append(pad)
        else:
            raise ValueError(f"PCB pad with ref {ref!r} has no placed component")

    free_actual = Counter((str(x.get("PadNumber")), x.get("Net"))
                          for x in free_pads)
    free_design = Counter((str(pin), net)
                          for mag in MAGNETS
                          for pin, net in legacy_refs.get(mag, {}).items())
    if len(free_design) != 24 or sum(free_design.values()) != 24:
        raise ValueError("Legacy magnetic logical terminal register changed")
    errors = []
    if free_actual != free_design:
        errors.append("Anonymous magnetic pad network multiset differs from legacy logical netlist")

    legacy_pad_errors = []
    reference_pad_count = 0
    for pad in placed_pads:
        ref, pin, net = pad["ref"], str(pad.get("PadNumber")), pad.get("Net")
        by_pin = legacy_refs.get(ref)
        if by_pin is None:
            legacy_pad_errors.append({"ref": ref, "pin": pin,
                                      "actual": net, "legacy": None})
        elif pin not in by_pin or by_pin[pin] != net:
            legacy_pad_errors.append({"ref": ref, "pin": pin,
                                      "actual": net, "legacy": by_pin.get(pin)})
        else:
            reference_pad_count += 1
    if legacy_pad_errors:
        errors.append("Saved PCB differs from Nov-6 pin/net reference on placed pads")

    groups = {g.get("name"): sum(len(x.get("list") or [])
                                  for x in g.get("list") or [])
              for g in drc_raw}
    return {
        "status": "G1_SAVED_NATIVE_ALIGNMENT_DIAGNOSTIC_NOT_ERC_OR_FAB",
        "native_schematic_component_count": len(components),
        "native_pcb_component_count": len(pcb_components),
        "native_pcb_pad_count": len(pads),
        "native_pcb_placed_pad_count": len(placed_pads),
        "native_pcb_anonymous_magnetic_pad_count": len(free_pads),
        "schematic_only_refs": sorted(s_refs - p_refs),
        "pcb_only_refs": sorted(p_refs - s_refs),
        "unplaced_real_magnetic_footprint_refs": sorted(set(MAGNETS) & (s_refs - p_refs)),
        "unplaced_designators_explicitly_double_dnp": sorted(
            r for r in (s_refs - p_refs)
            if sch_by_ref[r].get("add_into_bom") is False
            and sch_by_ref[r].get("add_into_pcb") is False),
        "historical_schematic_ref_renamed_or_missing": sorted(set(legacy_refs) - s_refs),
        "native_schematic_refs_not_in_legacy_export": sorted(s_refs - set(legacy_refs)),
        "anonymous_pad_matches_legacy_magnetic_net_multiset": free_actual == free_design,
        "anonymous_pad_is_not_a_physical_magnet_footprint": True,
        "placed_pads_matching_legacy_netlist": reference_pad_count,
        "placed_pads_mismatching_legacy_netlist": legacy_pad_errors,
        "native_drc": {
            "connection_errors": groups.get("Connection Error", 0),
            "netlist_errors": groups.get("Netlist Error", 0),
            "physical_errors": groups.get("Physical Error", 0),
        },
        "detected_data_disagreements": errors,
        "current_schematic_netlist_reexported_from_same_board": False,
        "netlist_drc_error_root_cause_proven": False,
        "required_next_cad_actions": [
            "Open Import Changes / schematic-PCB difference on THIS native board; export exact per-ref netlist change report. Do not blindly apply all changes.",
            "Replace 24 anonymous T1-T4/CT pads with validated independent real device footprints and correct physical terminal/DOT maps.",
            "Keep the double-DNP R6 (original R8) excluded; recheck source-to-RUN wiring on a newly exported live schematic netlist.",
            "Resolve the actual existing 1 Netlist Error, then rerun genuine EasyEDA ERC/DRC on the new saved/reopened PCB.",
        ],
        "fabrication_approved": False,
        "limitations": [
            "Old November 6 schematic pin-net file is HISTORICAL, not a live active-G1 netlist.",
            "Exact root cause of the single EasyEDA netlist error cannot be deduced from the summary DRC category.",
            "Free-pad multiset matching cannot establish physical DOT, winding connections, insulation or mechanical assembly.",
            "Native inventory component names are read from schematic; native PCB components come from a separate PCB readback within the same saved archive.",
        ],
    }


def report() -> dict:
    receipt, schematic, pcb, drc = fail_if_bad_native_capture()
    old = doc(OLD_NETLIST)
    if old.get("ok") is not True or not isinstance(old.get("value", {}).get("refs"), dict):
        raise ValueError("Historical schematic export missing")
    audit = doc(INVENTORY_AUDIT)
    if (audit.get("snapshot_source") != INVENTORY.relative_to(ROOT).as_posix()
            or audit.get("r8_capture_designator") != "R6"
            or audit.get("original_r8_in_bom") is not False
            or audit.get("original_r8_in_pcb") is not False):
        raise ValueError("G1 actual inventory DNP capture changed, re-review safety")
    result = compare(schematic["components"], pcb["components"], pcb["pads"],
                     old["value"]["refs"], drc["raw"])
    if (result["native_drc"]["netlist_errors"] < 1
            or result["current_schematic_netlist_reexported_from_same_board"]):
        raise ValueError("Native netlist gate changed; do not reuse historic diagnosis")
    result["native_board_sha256"] = receipt["candidate_sha256"]
    result["native_inventory_capture_path"] = INVENTORY.relative_to(ROOT).as_posix()
    result["historical_netlist_path"] = OLD_NETLIST.relative_to(ROOT).as_posix()
    result["pcb_readback_path"] = READBACK.relative_to(ROOT).as_posix()
    result["native_drc_path"] = DRC.relative_to(ROOT).as_posix()
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--write", action="store_true")
    args = ap.parse_args()
    data = report()
    if args.write:
        OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    elif not OUT.is_file() or doc(OUT) != data:
        raise SystemExit("Native G1 diagnostic is stale; rerun after REAL native CAD recapture")
    print(json.dumps({
        "sch": data["native_schematic_component_count"],
        "pcb": data["native_pcb_component_count"],
        "unplaced": data["schematic_only_refs"],
        "historical_pad_net_disagreements": len(data["placed_pads_mismatching_legacy_netlist"]),
        "native_netlist_drc_errors": data["native_drc"]["netlist_errors"],
        "fab_approved": data["fabrication_approved"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

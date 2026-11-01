"""Fail-closed, regenerable D1 electrical fabrication readiness report.

Checks evidence actually present in the repository. Do NOT equate a passing
subset-of-pads netlist diff, offline pytest, a machine-generated placement PCB,
or simulated current with a fabrication release.

Usage:
  python tools/d1_fabrication_gate.py --write
  python tools/d1_fabrication_gate.py --require-release
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HW = ROOT / "hardware/dcx_main"
OUT = HW / "d1_fabrication_gate.json"
GOLDEN = ROOT / "design/v3/pcb/board_netlist.csv"
NETLIST = HW / "netlist_compare.json"
CONTRACT = HW / "magnetics_symbol_contract.json"
REVIEW = HW / "pin_footprint_review.csv"
BOM = ROOT / "design/v3/bom/bom_draft.csv"

# No such files have been delivered in the current main branch. Do not turn
# these checks green until the native EDA evidence has been independently
# exported and checked, including real pad numbers and layer stack-up.
NATIVE_ERC = HW / "native_erc_approved.json"
PCB_NET_DIFF = HW / "pcb_to_schematic_verified.json"
FAB_APPROVAL = HW / "fabrication_approval.json"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _manual_gate(path: Path, required: tuple[str, ...]) -> dict:
    try:
        display = path.relative_to(ROOT).as_posix()
    except ValueError:
        display = path.as_posix()
    if not path.is_file():
        return {"passed": False, "reason": "evidence file absent", "path": display}
    try:
        doc = _read(path)
    except (ValueError, OSError) as exc:
        return {"passed": False, "reason": f"invalid evidence: {type(exc).__name__}",
                "path": display}
    # A status without a cited external original is not evidence. Requiring all
    # nonempty strings makes accidentally generated 'approved=true' insufficient.
    ok = doc.get("approved") is True and all(
        isinstance(doc.get(k), str) and doc[k].strip() for k in required
    )
    return {"passed": bool(ok), "path": display,
            "reason": "complete, subject to human verification" if ok else
                      "approval and source evidence fields incomplete"}


def build() -> dict:
    golden = _csv(GOLDEN)
    net = _read(NETLIST)
    magnets = _read(CONTRACT)["symbols"]
    placement = _read(HW / "placement_plan.json")
    review = _csv(REVIEW)
    bom = _csv(BOM)

    gold_refs = {x["ref"] for x in golden}
    present = set(placement["refs"])
    missing_refs = sorted(gold_refs - present)
    incomplete_magnets = sorted(
        m["ref"] for m in magnets
        if not m.get("native_symbol_present") or not m.get("physical_pad_map_verified")
        or any(not p.get("physical_pad") for p in m.get("pins", []))
    )
    placeholders = sorted({x["ref"] for x in review if "PLACEHOLDER" in x.get("note", "")})
    undecided_bom = [
        {"ref": x["ref"], "mpn": x["mpn"], "status": x["status"]}
        for x in bom if x["mpn"] in {"TO SELECT", "TO BUILD", "TO ASSIGN"}
                     or x["status"] in {"TO SELECT", "TO BUILD"}
    ]
    native_erc = _manual_gate(NATIVE_ERC, ("report_path", "reviewer", "revision"))
    pcb_diff = _manual_gate(PCB_NET_DIFF, ("report_path", "reviewer", "revision"))
    fab_signoff = _manual_gate(FAB_APPROVAL, ("gerber_path", "bom_path", "pcb_drc_path",
                                               "stackup_path", "reviewer", "revision"))

    logical_ok = (
        bool(net.get("subset_ok")) and not net.get("missing_or_wrong")
        and not net.get("unexpected_nets")
        and not net.get("unexpected_refs")
    )
    # "ok" in a subset report is explicitly NOT a release decision.
    all_placed = not missing_refs and not net.get("not_placed") and not incomplete_magnets
    all_values_frozen = not placeholders and not undecided_bom
    checks = {
        "native_editable_project_present": (HW / "dcx_main_board.eprj2").is_file(),
        "golden_subnet_matches": logical_ok,
        "all_golden_refs_and_magnetic_physical_pads_verified": all_placed,
        "no_electrical_placeholders_or_unselected_bom": all_values_frozen,
        "native_erc_evidence": native_erc["passed"],
        "routed_pcb_to_schematic_evidence": pcb_diff["passed"],
        "manufacturing_package_evidence": fab_signoff["passed"],
    }
    blockers = [key for key, passed in checks.items() if not passed]
    return {
        "gate": "D1_ELECTRICAL_FABRICATION",
        "release_approved": not blockers,
        "status": "APPROVED_WITH_DOCUMENTED_EVIDENCE" if not blockers else "NOT_FOR_FAB",
        "checks": checks,
        "counts": {
            "golden_references": len(gold_refs),
            "golden_logical_pins": len(golden),
            "placed_references": len(present),
            "golden_pads_checked_by_subnet": net.get("pads_checked"),
            "unplaced_references": missing_refs,
            "magnetics_missing_physical_pads": incomplete_magnets,
            "refs_with_placeholders": placeholders,
            "bom_rows_not_selected": undecided_bom,
        },
        "manual_evidence": {
            "native_erc": native_erc,
            "pcb_to_schematic": pcb_diff,
            "fab_approval": fab_signoff,
        },
        "blockers": blockers,
        "limitations": [
            "Subset netlist check is NOT a complete schematic pin or footprint check",
            "The golden netlist was derived from a SPICE deck, not all physical components",
            "A JSON approval record must refer to genuine independently reviewed native EDA/DFM evidence",
            "Power and efficiency from LTspice do not constitute hardware continuous rating",
            "Thermal and cold plate design intentionally deferred; continuous rating stays unapproved",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--require-release", action="store_true")
    args = parser.parse_args()
    result = build()
    serial = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.write:
        OUT.write_text(serial, encoding="utf-8", newline="\n")
    elif OUT.is_file() and OUT.read_text(encoding="utf-8") != serial:
        raise SystemExit("D1 report is stale: run --write and commit the difference")
    print(f"D1 {result['status']}: {len(result['blockers'])} blocker categories")
    for row in result["blockers"]:
        print(f"  BLOCKED {row}")
    return 1 if args.require_release and not result["release_approved"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

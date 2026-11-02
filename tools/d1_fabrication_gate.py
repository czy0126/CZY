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
import hashlib
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

import d1_bom_coverage as bomcov

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
    # Sign-off metadata alone is not enough: evidence must be present in this
    # checkout with a matching sha256. Reject absolute/out-of-repo paths so an
    # approval cannot silently depend on a private author's desktop.
    ok = doc.get("approved") is True and all(
        isinstance(doc.get(k), str) and doc[k].strip() for k in required
    )
    reason = "approval and source evidence fields incomplete"
    if ok:
        paths = [k for k in required if k.endswith("_path")]
        if not paths:
            ok = False
            reason = "no original evidence file fields"
        for key in paths:
            if not ok:
                break
            original = Path(doc[key])
            if original.is_absolute() or ".." in original.parts:
                ok = False
                reason = "evidence path must be relative and inside repository"
                break
            original = ROOT / original
            digest = doc.get(key[:-5] + "_sha256")
            if (not original.is_file() or not isinstance(digest, str)
                    or len(digest) != 64
                    or hashlib.sha256(original.read_bytes()).hexdigest() != digest.lower()):
                ok = False
                reason = "missing original report or matching sha256: " + key
                break
    return {"passed": bool(ok), "path": display,
            "reason": "source hashes verified; still needs human signature review" if ok else reason}


def build() -> dict:
    golden = _csv(GOLDEN)
    net = _read(NETLIST)
    magnets = _read(CONTRACT)["symbols"]
    placement = _read(HW / "placement_plan.json")
    review = _csv(REVIEW)
    bom = _csv(BOM)
    # Recompute from current BOM and SPICE golden: a stale checked-in
    # bom_coverage.json must never make this release gate go green.
    bom_coverage = bomcov.build()
    native_export = _read(HW / "gen/netlist_export_raw.json")
    if not native_export.get("ok") or not isinstance(native_export.get("value", {}).get("refs"), dict):
        raise ValueError("missing or invalid native EDA export")
    native_refs = set(native_export["value"]["refs"])

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
    required_missing = bom_coverage["required_bom_refs_missing_from_golden"]
    # Unlike the SPICE-derived golden, the *actual native* CAD must include
    # every soldered BOM designator. The external PS1 can remain an interface.
    all_bom_refs = {
        ref for row in bom for ref in bomcov.refs(row["ref"])
    } - bomcov.EXTERNAL_INTERFACES
    native_bom_missing = sorted(all_bom_refs - native_refs)
    checks = {
        "native_editable_project_present": (HW / "dcx_main_board.eprj2").is_file(),
        "golden_subnet_matches": logical_ok,
        "all_golden_refs_and_magnetic_physical_pads_verified": all_placed,
        "no_electrical_placeholders_or_unselected_bom": all_values_frozen,
        "all_required_real_hardware_bom_refs_in_native_design": not native_bom_missing,
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
            "real_hardware_bom_refs_not_in_golden": sorted(x["ref"] for x in required_missing),
            "all_required_bom_refs_missing_from_native_export": native_bom_missing,
            "external_bias_interface_to_document": [x["ref"] for x in bom_coverage["external_interfaces_not_in_golden"]],
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
            "BOM-driven control/decoupling parts must be present in native EDA and the final CAD-derived netlist",
            "Evidence records require original repository files and matching SHA256, but hashes do not replace expert approval",
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

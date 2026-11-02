"""Generate truthful vendor pinout requests and component-selection action register.

No unverified physical MPN/pin is promoted into a verified package.
Uses the native A1 review, draft BOM and magnetic logical-dot contract.

Usage: python tools/d1_sourcing_register.py --write
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import d1_bom_coverage as cov

ROOT = Path(__file__).resolve().parent.parent
HW = ROOT / "hardware/dcx_main"
REVIEW = HW / "pin_footprint_review.csv"
BOM = ROOT / "design/v3/bom/bom_draft.csv"
CONTRACT = HW / "magnetics_symbol_contract.json"
REG = HW / "component_decision_register.json"
VENDOR = HW / "vendor_terminal_request.json"
HIGH = {"T1", "T2", "T3", "T4", "CT", "Lr", "Cr",
        "Cin", "Cout", "D_BT", "J_IN", "J_OUT"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def build() -> tuple[dict, dict]:
    review = read_csv(REVIEW)
    bom = read_csv(BOM)
    lookup = {}
    for row in bom:
        for ref in cov.refs(row["ref"]):
            # T1-T4 are represented by core, I plate and winding BOM rows.
            # Winding is the unit whose electrical pad identity is required.
            if ref not in lookup or row["mpn"] in {"TO BUILD", "TO SELECT"}:
                lookup[ref] = row
    bad = sorted({r["ref"] for r in review if "PLACEHOLDER" in r["note"]})
    selection = []
    for ref in bad:
        if ref not in lookup:
            raise ValueError(f"PLACEHOLDER ref missing from draft BOM: {ref}")
        b = lookup[ref]
        sources = sorted({r["note"] for r in review if r["ref"] == ref
                          and "PLACEHOLDER" in r["note"]})
        selection.append({
            "ref": ref,
            "priority": "P0" if ref in HIGH else "P1",
            "part_role": b["item"],
            "existing_value_or_rating": b["value_or_rating"],
            "current_mpn": b["mpn"],
            "current_package": b["package"],
            "source_path": b["source"],
            "issues": sources,
            "requested_decision": "manufacturer terminal/pad and DOT signoff" if ref in
                {"T1","T2","T3","T4","CT"} else
                "select real purchasable part or approved designed assembly; verify footprint/pad/voltage/current",
            "verified_mpn": None,
            "manufacturer_datasheet": None,
            "eda_footprint_verified": False,
            "decision_owner": None,
            "reviewer": None,
            "status": "PENDING_VENDOR_OR_ENGINEER_EVIDENCE",
        })
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    devices = []
    for sym in contract["symbols"]:
        if sym.get("physical_pad_map_verified"):
            continue
        term = []
        for pin in sym["pins"]:
            term.append({
                "logical_terminal": pin["logical_pin"],
                "required_circuit_net": pin["golden_net"],
                "dot_convention_expected": pin["polarity"],
                "vendor_physical_terminal_id": None,
                "terminal_drawing_ref": None,
                "test_polarity_result": None,
                "test_result_status": "NOT_TESTED",
            })
        devices.append({
            "ref": sym["ref"], "logical_type": sym["winding_type"],
            "vendor_name": None, "drawing_revision": None,
            "vendor_terminal_count_expected": len(term),
            "pins": term, "real_mechanical_footprint": None,
            "isolation_test_requirement": "Confirm primary-secondary insulation and test method with vendor",
            "dot_test_requirement": "Mark real primary and each secondary dotted terminal, validate centre-tap polarity",
            "accepted_by_engineer": False,
            "status": "AWAIT_VENDOR_PINOUT_AND_WINDING_FIRST_ARTICLE",
        })
    return ({
        "status": "SELECTION_REGISTER_NOT_PURCHASE_ORDER",
        "design_review_baseline": "native schematic A1 review, NOT fabrication-ready",
        "total_placeholder_refs": len(selection),
        "items": selection,
        "requirements": [
            "Replace placeholder package and MPN only with manufacturer evidence",
            "Confirm voltage/RMS/capacitance and actual body/footprint for Cr/Cout/Cin",
            "Confirm MOS driver bootstrap capacitance and diode ratings under actual 50V high output",
            "Output connector/busbar and via resistance require signed four-wire and DFM data",
            "No 100/120A continuous or thermal signoff is claimed",
        ],
    }, {
        "status": "REQUEST_FOR_VENDOR_DRAWING_AND_FIRST_ARTICLE_NOT_VERIFIED",
        "devices": devices,
        "requirements": [
            "Return dimensioned terminal diagram and physical pad IDs for each device",
            "Confirm dot, secondary CTAP winding junction, turns, Lm, leakage and cold DCR",
            "Confirm mounting outline, board pocket and electrical clearance",
            "CT current transformer has FOUR logical terminals; present TWO-pad footprint is INVALID",
            "Do not assign sequential 1-5 pins without signed actual hardware drawing",
        ],
    })


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    registers = build()
    for path, data in zip((REG, VENDOR), registers):
        serialized = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        if args.write:
            path.write_text(serialized, encoding="utf-8", newline="\n")
        elif json.loads(path.read_text(encoding="utf-8")) != data:
            raise SystemExit(f"stale register {path}; rerun --write")
    print(f"61-part sourcing register and 5-magnetic vendor request: no verified new MPN")


if __name__ == "__main__":
    raise SystemExit(main())

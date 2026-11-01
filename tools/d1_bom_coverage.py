"""Enumerate every required BOM designator absent from the SPICE-derived netlist.

The golden netlist is useful for pin matching but it does not include some
real-world decoupling and driver enable networks. A full pad-level match
must NEVER be equated with a complete manufactured schematic.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "design/v3/pcb/board_netlist.csv"
BOM = ROOT / "design/v3/bom/bom_draft.csv"
OUT = ROOT / "hardware/dcx_main/bom_coverage.json"

# 12V external supply is a board *interface*, not necessarily a soldered
# component. Still needs a documented connector, power-up and return path.
EXTERNAL_INTERFACES = frozenset({"PS1"})


def refs(text: str) -> list[str]:
    """Expand compact references; fail visibly instead of dropping unknown syntax."""
    if text == "SR1A-SR4B":
        return [f"SR{i}{s}" for i in range(1, 5) for s in ("A", "B")]
    result = []
    for token in text.split():
        pattern = re.fullmatch(r"([A-Za-z_]+)(\d+)-([A-Za-z_]+)(\d+)", token)
        if pattern:
            p, first, q, last = pattern.groups()
            if p != q or int(last) < int(first):
                raise ValueError(f"unsupported BOM ref range: {token}")
            result.extend(f"{p}{i}" for i in range(int(first), int(last)+1))
        else:
            if not re.fullmatch(r"[A-Za-z_]+\d+|QH|QL|Cin|Cout|Cr|Lr|J_IN|J_OUT", token):
                raise ValueError(f"unknown BOM reference syntax: {token}")
            result.append(token)
    if len(set(result)) != len(result):
        raise ValueError(f"duplicated designator within BOM row: {text}")
    return result


def build() -> dict:
    with GOLDEN.open(encoding="utf-8", newline="") as fh:
        golden = {r["ref"] for r in csv.DictReader(fh)}
    with BOM.open(encoding="utf-8", newline="") as fh:
        bom = list(csv.DictReader(fh))
    missing = {}
    external = {}
    rows_unmatched = []
    ref_in_bom = set()
    for row in bom:
        names = refs(row["ref"])
        if int(row["qty"]) != len(names):
            raise ValueError(f"BOM qty != expanded designators for {row['ref']}")
        for name in names:
            ref_in_bom.add(name)
            if name not in golden:
                info = {"ref": name, "function": row["item"], "group": row["group"],
                        "value_or_rating": row["value_or_rating"], "source": row["source"],
                        "required_action": "verify in native schematic and map to PCB/BOM"}
                if name in EXTERNAL_INTERFACES:
                    external[name] = info
                else:
                    missing[name] = info
        if all(n not in golden for n in names):
            rows_unmatched.append(row["ref"])
    return {
        "status": "GOLDEN_NETLIST_INCOMPLETE_FOR_REAL_HARDWARE",
        "golden_ref_count": len(golden),
        "bom_unique_refs": len(ref_in_bom),
        "required_bom_refs_missing_from_golden": [missing[n] for n in sorted(missing)],
        "external_interfaces_not_in_golden": [external[n] for n in sorted(external)],
        "bom_rows_entirely_missing_from_golden": sorted(set(rows_unmatched)),
        "not_in_bom_golden_refs": sorted(golden - ref_in_bom),
        "engineering_notes": [
            "R7-R10 include U2 EN, RUN and HI/LI pull-down paths; these are not optional simply because SPICE omits them",
            "C13 is U2 EN filtering; C101-C112 are controller VDD decouplers as specified by BOM",
            "PS1 is an external control-bias/interface candidate, not automatically an on-board part",
            "Some BOM rows list non-soldered core halves and transformer windings for the same T1-T4 assembly",
            "BOM coverage does not validate any datasheet, net assignment, packaging or schematic correctness",
        ],
        "design_action": "Add absent real peripherals to native CAD, expand its exported netlist golden basis, and make the complete PCB netlist the only fabrication acceptance netlist",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    text = json.dumps(build(), ensure_ascii=False, indent=2) + "\n"
    if args.write:
        OUT.write_text(text, encoding="utf-8", newline="\n")
    elif OUT.is_file() and OUT.read_text(encoding="utf-8") != text:
        raise SystemExit("stale BOM coverage: python tools/d1_bom_coverage.py --write")
    print(f"missing CAD references: {len(build()['required_bom_refs_missing_from_golden'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

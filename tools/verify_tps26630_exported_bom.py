"""Validate actual KiCad 10 draft BOM reference integrity without releasing fabrication.

KiCad's native exporter previously silently appended '?' to functional role
names (RUV_TOP?, J_IN?, etc). The source schematic now uses stable numeric
references and a separate alias mapping for traceability. This checks the
exported BOM, not just the source text. U1/Q1 have no validated native pads.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / "hardware/sr_bias_efuse_proposal"
MAP = BASE / "native/native_reference_map.csv"
EXPECTED_IC = {"U1":"TPS26630RGET", "Q1":"CSD19537Q3T", "Q2":"BSS138-7-F"}


def verify(bom_path: Path, map_path: Path = MAP) -> dict:
    with map_path.open(encoding="utf-8", newline="") as stream:
        mappings = list(csv.DictReader(stream))
    aliases = {row["functional_ref"]:row["native_ref"] for row in mappings}
    if len(aliases) != 12 or len(set(aliases.values())) != 12:
        raise ValueError("functional-to-physical reference map incomplete")
    expected = set(aliases.values()) - {aliases["COUT_MODEL"]}
    expected |= set(EXPECTED_IC)
    with bom_path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    refs = [row.get("Refs","") for row in rows]
    if any(not ref or "?" in ref or "," in ref for ref in refs):
        raise ValueError("KiCad BOM contains invalid/unannotated/grouped designators")
    if len(refs) != len(set(refs)) or set(refs) != expected:
        raise ValueError(f"KiCad exported BOM has unexpected refs: {sorted(refs)} vs {sorted(expected)}")
    by_ref = {row["Refs"]:row for row in rows}
    for ref, part in EXPECTED_IC.items():
        if by_ref[ref]["Value"] != part:
            raise ValueError(f"{ref} wrong OEM BOM value: {by_ref[ref]['Value']!r}")
    # Missing physical footprint is an *open blocker*, not test failure or
    # a silent placeholder that might be mistaken for manufacturing readiness.
    if by_ref["U1"]["Footprint"] or by_ref["Q1"]["Footprint"]:
        raise ValueError("U1/Q1 new footprints require independent OEM pad/EP review")
    return {
        "status":"CONCEPT_BOM_REFERENCES_CHECKED_NOT_FOR_FAB",
        "exported_bom_rows":len(rows),
        "native_reference_count":len(expected),
        "unannotated_refs":0,
        "U1_Q1_physical_footprints_assigned":False,
        "manufacturer_pinmap_exported_by_real_kicad":True,
        "hardware_qualified":False,
        "fabrication_approved":False,
    }


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bom",type=Path,required=True)
    parser.add_argument("--map",type=Path,default=MAP)
    parser.add_argument("--out",type=Path)
    args=parser.parse_args(argv)
    value=verify(args.bom,args.map)
    if args.out:
        args.out.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(value))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Audit native EDA library device number against visible schematic value.

A text-value ECO is NOT BOM part verification. This audit uses only two
manufacturer-documented part numbers and never modifies the original EDA.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "hardware/dcx_main/placeholder_eco.json"
OUTPUT = ROOT / "hardware/dcx_main/native_mpn_value_conflicts.json"
FACTS = {
    "CL10B104KB8NNNC": {"value": "100nF", "vendor": "Samsung",
        "source": "https://media.digikey.com/pdf/Data%20Sheets/Samsung%20PDFs/CL10B104KB8NNNC_Spec.pdf"},
    "0603WAF1002T5E": {"value": "10kΩ", "vendor": "Uniroyal",
        "source": "https://jlcpcb.com/partdetail/0603WAF1002T5E/C25804"},
}
CANDIDATES = {
    "REG capacitors": "GRM188C71E225KE11D",
    "SR drain Kelvin link": "CRCW06030000Z0EA",
}
CANDIDATE_SOURCES = {
    "GRM188C71E225KE11D":
        "https://search.murata.co.jp/Ceramy/image/img/A01X/G101/ENG/GRM188C71E225KE11-01.pdf",
    "CRCW06030000Z0EA":
        "https://www.digikey.com/en/products/detail/vishay-dale/CRCW06030000Z0EA/1179296",
}


def report():
    source = json.loads(INPUT.read_text(encoding="utf-8"))
    known = [r for r in source["rows"]
             if r["native_device"] in FACTS and r["target_value"] is not None]
    bad = [r for r in known if r["target_value"] != FACTS[r["native_device"]]["value"]]
    out = [{
        "ref": r["ref"], "role": r["part_role"],
        "native_device": r["native_device"],
        "native_physical_value": FACTS[r["native_device"]]["value"],
        "schematic_target": r["target_value"],
        "prior_eco_class": r["eco_class"],
        "manufacturer_source": FACTS[r["native_device"]]["source"],
        "candidate": CANDIDATES.get(r["part_role"]),
        "approval": False,
    } for r in bad]
    return {
        "status": "P0_REVIEW_REQUIRED_NOT_FOR_FAB",
        "source": "hardware/dcx_main/placeholder_eco.json",
        "manufacturer_facts": FACTS,
        "known_rows": len(known),
        "mismatch_count": len(out),
        "previously_falsely_value_conforming":
            sum(r["prior_eco_class"] == "ALREADY_CONFORMS" for r in out),
        "known_exact_match_count": len(known) - len(out),
        "rows": out,
        "vendor_candidate_sources": CANDIDATE_SOURCES,
        "native_eda_modified": False,
        "physical_parts_ordered": False,
        "hardware_qualified": False,
        "fabrication_approved": False,
        "next_action": "Export native EasyEDA BOM from an EDA project copy, inspect manufacturer MPN/Library code/value for all 39 refs, replace true devices, confirm 0603 pad/REG DC-bias/Kelvin routing before releasing a purchase order",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true")
    group.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    value = report()
    if args.write:
        OUTPUT.write_text(json.dumps(value, ensure_ascii=False, indent=2)+"\n",
                          encoding="utf-8")
    else:
        actual = json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.is_file() else None
        if actual != value:
            print("MPN/value report stale; run --write")
            return 1
    print(f"Native MPN mismatch {value['mismatch_count']} of {value['known_rows']}; "
          "source-only NOT_FOR_FAB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

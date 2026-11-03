"""Validate candidate evidence independently of fabrication / approved BOM.
Run: python tools/verify_vendor_candidate_matrix.py --check
"""
from __future__ import annotations
import argparse
import csv
import io
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
KIT=ROOT/"docs/D1_EXECUTION_KIT"
REGISTER=ROOT/"hardware/dcx_main/component_decision_register.json"
CATALOG=KIT/"vendor_parts_official.json"
ASSIGN=KIT/"vendor_ref_assignments.json"
MATRIX=KIT/"templates/vendor_candidate_matrix_61.csv"
HEADER=["ref","priority","role","current_package_placeholder","required_value_or_rating","candidate_part_key","candidate_mpn","manufacturer","nominal_spec","rated_voltage_v","nominal_eia_case","source_kind","official_source_url","part_exists","candidate_only","native_eda_verified","application_approved","review_note"]

def render() -> str:
    data=json.loads(REGISTER.read_text(encoding="utf-8"))
    catalog=json.loads(CATALOG.read_text(encoding="utf-8"))
    assign=json.loads(ASSIGN.read_text(encoding="utf-8"))
    items=data["items"]
    refs={x["ref"] for x in items}
    if len(items)!=61 or len(refs)!=61 or data["total_placeholder_refs"]!=61:
        raise ValueError("61 original unique refdes required")
    if not set(assign).issubset(refs):
        raise ValueError("assignment contains nonexistent refdes")
    if not set(assign.values()).issubset(catalog):
        raise ValueError("assignment contains unknown product key")
    out=io.StringIO(newline="")
    writer=csv.DictWriter(out,fieldnames=HEADER,lineterminator="\n")
    writer.writeheader()
    for item in items:
        key=assign.get(item["ref"])
        part=catalog.get(key,{})
        row=dict(zip(HEADER,[
            item["ref"],item["priority"],item["part_role"],item["current_package"],
            item["existing_value_or_rating"],key or "",part.get("mpn",""),
            part.get("maker",""),part.get("nominal",""),part.get("voltage_v",""),
            part.get("eia_case",""),part.get("source_kind",""),
            part.get("source_url",""),"YES_OFFICIAL_MPN" if key else "NO_SPECIFIC_PART",
            "YES","NO","NO",
            part.get("notes","") or ("REQUIRES_INDEPENDENT_ELECTRICAL_AND_PHYSICAL_SELECTION; "+item["requested_decision"])
        ]))
        if key and (not row["official_source_url"].startswith("https://")
                   or row["source_kind"]!="OFFICIAL_MANUFACTURER"):
            raise ValueError("not an official product source: "+item["ref"])
        if row["native_eda_verified"]!="NO" or row["application_approved"]!="NO":
            raise ValueError("illegal design approval")
        writer.writerow(row)
    return out.getvalue()

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--check",action="store_true")
    ap.add_argument("--write",action="store_true")
    args=ap.parse_args()
    expected=render()
    if args.write:
        MATRIX.write_text(expected,encoding="utf-8",newline="")
    elif args.check and (not MATRIX.is_file() or MATRIX.read_text(encoding="utf-8")!=expected):
        raise SystemExit("stale vendor candidate matrix: run --write")
    reader=list(csv.DictReader(io.StringIO(expected)))
    mapped=sum(bool(x["candidate_mpn"]) for x in reader)
    print(f"vendor evidence: {mapped}/61 documented candidates; 61/61 refdes covered; zero CAD approvals")
    return 0

if __name__=="__main__":
    raise SystemExit(main())

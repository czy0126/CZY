"""Generate non-approved RFQ sheets, never invent actual vendor evidence."""
from __future__ import annotations
import argparse
import csv
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HW = ROOT / "hardware/dcx_main"
DEST = ROOT / "docs/D1_EXECUTION_KIT/templates"
SUPPLIER = DEST / "supplier_seed_61.csv"
MAGNETICS = DEST / "magnetic_terminal_seed_24.csv"
SUPPLIER_COLUMNS = ["ref","priority","part_role","required_value_or_rating","existing_placeholder_mpn","existing_placeholder_package","source_path","requested_decision","verified_mpn","manufacturer","official_datasheet_url","datasheet_revision","physical_pad_map","height_mm","measured_ac_loss","reviewer","status"]
MAGNETICS_COLUMNS = ["ref","logical_pin","golden_net","model_polarity","placeholder_footprint","supplier_terminal","manufacturer_drawing","drawing_rev","measured_phase","reviewer","status"]


def _csv(cols, rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=cols, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def supplier_seed():
    obj = json.loads((HW / "component_decision_register.json").read_text(encoding="utf-8"))
    items = obj["items"]
    refs = [x["ref"] for x in items]
    if len(refs) != len(set(refs)) or len(refs) != obj["total_placeholder_refs"]:
        raise ValueError("BOM decision register has duplicate or mismatched references")
    rows = []
    for x in items:
        row = dict(ref=x["ref"], priority=x["priority"], part_role=x["part_role"],
                   required_value_or_rating=x.get("existing_value_or_rating", ""),
                   existing_placeholder_mpn=x.get("current_mpn", ""),
                   existing_placeholder_package=x.get("current_package", ""),
                   source_path=x.get("source_path", ""),
                   requested_decision=x.get("requested_decision", ""))
        row.update({key: "PENDING" for key in SUPPLIER_COLUMNS if key not in row})
        rows.append(row)
    return _csv(SUPPLIER_COLUMNS, rows)


def magnetic_seed():
    obj = json.loads((HW / "magnetics_symbol_contract.json").read_text(encoding="utf-8"))
    rows = []
    for symbol in obj["symbols"]:
        for pin in symbol["pins"]:
            if pin["physical_pad"] is not None or symbol["physical_pad_map_verified"]:
                raise ValueError("physical magnetics now identified: review seed schema")
            row = dict(ref=symbol["ref"], logical_pin=pin["logical_pin"],
                       golden_net=pin["golden_net"], model_polarity=pin["polarity"],
                       placeholder_footprint=symbol["placeholder_footprint"])
            row.update({key: "PENDING" for key in MAGNETICS_COLUMNS if key not in row})
            rows.append(row)
    if len({(x["ref"], x["logical_pin"]) for x in rows}) != len(rows):
        raise ValueError("duplicate magnetic pin requests")
    return _csv(MAGNETICS_COLUMNS, rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true")
    group.add_argument("--write", action="store_true")
    args = ap.parse_args()
    for path, render in ((SUPPLIER, supplier_seed), (MAGNETICS, magnetic_seed)):
        expected = render()
        if args.write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected, encoding="utf-8", newline="")
        elif args.check and (not path.exists() or path.read_text(encoding="utf-8") != expected):
            raise SystemExit(f"stale request {path}; run --write")
        print(path.relative_to(ROOT), expected.count("\n") - 1, "PENDING requests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

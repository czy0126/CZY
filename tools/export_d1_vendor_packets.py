"""Export current vendor requests to directly fillable CSV without invented data.

Usage:
    python tools/export_d1_vendor_packets.py --write
    python tools/export_d1_vendor_packets.py   # verify generated files
Use the JSON request as read-only source; do not overwrite supplier replies.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HW = ROOT / "hardware/dcx_main"
MAG_JSON = HW / "vendor_terminal_request.json"
BOM_JSON = HW / "component_decision_register.json"
MAG_OUT = HW / "supplier_magnetic_terminal_reply_template.csv"
BOM_OUT = HW / "supplier_component_selection_template.csv"

MAG_FIELDS = (
    "ref", "logical_terminal", "expected_circuit_net", "design_dot_convention",
    "supplier_physical_pad", "supplier_pinout_drawing_uri",
    "drawing_revision", "measured_dot_result", "measured_turns_or_ratio",
    "terminal_footprint_verified", "reviewer", "decision",
)
BOM_FIELDS = (
    "ref", "priority", "function", "required_value_or_rating", "existing_package",
    "previous_mpn", "proposed_mpn", "manufacturer_datasheet_uri",
    "actual_package", "pad_map_reviewed", "electrical_stress_accepted",
    "lead_time_or_stock", "owner", "reviewer", "decision",
)


def rows() -> tuple[list[dict], list[dict]]:
    magnetics = json.loads(MAG_JSON.read_text(encoding="utf-8"))
    parts = json.loads(BOM_JSON.read_text(encoding="utf-8"))
    pins = [
        {
            "ref": d["ref"], "logical_terminal": p["logical_terminal"],
            "expected_circuit_net": p["required_circuit_net"],
            "design_dot_convention": p["dot_convention_expected"],
            "supplier_physical_pad": "",
            "supplier_pinout_drawing_uri": "",
            "drawing_revision": "",
            "measured_dot_result": "",
            "measured_turns_or_ratio": "",
            "terminal_footprint_verified": "NO",
            "reviewer": "", "decision": "PENDING",
        }
        for d in magnetics["devices"] for p in d["pins"]
    ]
    choices = [
        {
            "ref": part["ref"],
            "priority": part["priority"],
            "function": part["part_role"],
            "required_value_or_rating": part["existing_value_or_rating"],
            "existing_package": part["current_package"],
            "previous_mpn": part["current_mpn"],
            "proposed_mpn": "", "manufacturer_datasheet_uri": "",
            "actual_package": "", "pad_map_reviewed": "NO",
            "electrical_stress_accepted": "NO", "lead_time_or_stock": "",
            "owner": "", "reviewer": "", "decision": "PENDING",
        }
        for part in parts["items"]
    ]
    choices.sort(key=lambda row: (row["priority"] != "P0", row["ref"]))
    return pins, choices


def serialize(columns: tuple[str, ...], values: list[dict]) -> str:
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(values)
    return buf.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    mag, bom = rows()
    if len(mag) != 24 or len(bom) != 61:
        raise ValueError("expected 5 magnetic devices/24 logical terminal rows and 61 placeholders")
    for path, data in (
        (MAG_OUT, serialize(MAG_FIELDS, mag)),
        (BOM_OUT, serialize(BOM_FIELDS, bom)),
    ):
        if args.write:
            path.write_text(data, encoding="utf-8", newline="\n")
        elif not path.is_file() or path.read_text(encoding="utf-8") != data:
            raise SystemExit(f"stale template: {path}; rerun --write before sending suppliers")
    print("supplier templates: 24 magnetic terminals, 61 unverified selections")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

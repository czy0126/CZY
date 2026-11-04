"""Validate 24 vendor physical magnetic terminals against frozen logical CAD.

This checks evidence *format and consistency*. It CANNOT create physical pad
numbers, authenticate vendor paperwork, qualify insulation, determine CT
polarity from the V3 model, or approve manufacturing.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "hardware/dcx_main/magnetics_symbol_contract.json"
DEFAULT_TEMPLATE = ROOT / "docs/D1_EXECUTION_KIT/templates/magnetic_vendor_response_24_TEMPLATE.csv"
FIELDS = (
    "ref", "logical_pin", "golden_net", "model_polarity", "supplier_terminal",
    "supplier_dot", "pad_xy_mm", "mechanical_footprint_ref",
    "manufacturer_drawing", "drawing_rev", "drawing_sha256",
    "measured_phase", "phase_test_record", "phase_test_sha256",
    "reviewer", "status",
)
PENDING = {"", "PENDING", "UNKNOWN", "TBD", "N/A", "TO_SELECT", "UNVERIFIED"}
HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def contract_entries(contract=None):
    doc = (json.loads(CONTRACT.read_text(encoding="utf-8"))
           if contract is None else contract)
    return {
        (sym["ref"], pin["logical_pin"]): {
            "golden_net": pin["golden_net"],
            "model_polarity": pin["polarity"],
            "placeholder_footprint": sym["placeholder_footprint"],
        }
        for sym in doc["symbols"] for pin in sym["pins"]
    }


def blank_rows(contract=None):
    expected = contract_entries(contract)
    return [
        {
            **{"ref": key[0], "logical_pin": key[1],
               "golden_net": val["golden_net"],
               "model_polarity": val["model_polarity"]},
            **{field: "PENDING" for field in FIELDS[4:]},
        }
        for key, val in expected.items()
    ]


def write_template(dest: Path):
    # Never overwrite an engineer/supplier-filled worksheet.
    with dest.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(blank_rows())


def load_rows(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(FIELDS):
            raise ValueError("unexpected response columns or order; use --write-template")
        rows = list(reader)
        if any(None in row or any(value is None for value in row.values()) for row in rows):
            raise ValueError("ragged supplier response CSV")
    return rows


def supplied(value):
    return isinstance(value, str) and value.strip().upper() not in PENDING


def _xy(raw):
    try:
        x, y = [float(v.strip()) for v in raw.split(",")]
        if not math.isfinite(x) or not math.isfinite(y):
            return None
        return (x, y)
    except (ValueError, TypeError):
        return None


def evaluate(rows, contract=None):
    expected = contract_entries(contract)
    problems = []
    missing = []
    provided = {}
    for position, row in enumerate(rows, 2):
        key = (row.get("ref"), row.get("logical_pin"))
        if key not in expected:
            problems.append(f"row {position}: unknown magnetic pin {key!r}")
            continue
        if key in provided:
            problems.append(f"row {position}: duplicate logical pin {key!r}")
            continue
        provided[key] = row
        standard = expected[key]
        for invariant in ("golden_net", "model_polarity"):
            if row.get(invariant) != standard[invariant]:
                problems.append(f"{key}: frozen {invariant} changed")
    if set(provided) != set(expected):
        for key in sorted(set(expected) - set(provided)):
            problems.append(f"{key}: missing logical terminal")
    used_pads = {}
    used_xy = {}
    observed_dot = {}
    reviewed_count = 0
    for key, row in provided.items():
        ref, logical = key
        known = expected[key]
        phys = row.get("supplier_terminal")
        dot = row.get("supplier_dot")
        if supplied(phys):
            norm = phys.strip().upper()
            identifier = (ref, norm)
            if identifier in used_pads:
                problems.append(f"{ref}: duplicated physical pad {phys!r}")
            used_pads[identifier] = logical
            if norm == logical.upper():
                problems.append(f"{key}: logical pin label is NOT a vendor pad number")
        else:
            missing.append(f"{key}: supplier_terminal")
        expected_dot = known["model_polarity"]
        if supplied(dot):
            if ref == "CT":
                if dot not in ("DOT", "NON_DOT"):
                    problems.append(f"{key}: CT supplier_dot must be DOT/NON_DOT")
            elif logical == "CTAP":
                if dot != "CTAP_SPLICE":
                    problems.append(f"{key}: CTAP requires splice notation, not a single DOT")
            elif dot != expected_dot:
                problems.append(f"{key}: supplier DOT conflicts with frozen model")
            observed_dot[key] = dot
        else:
            missing.append(f"{key}: supplier_dot")
        xy = row.get("pad_xy_mm")
        if supplied(xy):
            pair = _xy(xy)
            if pair is None:
                problems.append(f"{key}: pad_xy_mm must be finite 'x,y' in mm")
            elif (ref, pair) in used_xy:
                problems.append(f"{ref}: two terminal pads share the same physical xy")
            else:
                used_xy[(ref, pair)] = logical
        else:
            missing.append(f"{key}: pad_xy_mm")
        fp = row.get("mechanical_footprint_ref")
        if supplied(fp):
            if fp == known["placeholder_footprint"]:
                problems.append(f"{key}: placeholder footprint cannot be vendor footprint")
        else:
            missing.append(f"{key}: mechanical_footprint_ref")
        for field in ("manufacturer_drawing", "drawing_rev", "measured_phase",
                      "phase_test_record", "reviewer", "status"):
            if not supplied(row.get(field)):
                missing.append(f"{key}: {field}")
        if supplied(row.get("drawing_sha256")):
            if not HASH_RE.fullmatch(row["drawing_sha256"].strip()):
                problems.append(f"{key}: drawing_sha256 is not a SHA256")
        else:
            missing.append(f"{key}: drawing_sha256")
        if supplied(row.get("phase_test_sha256")):
            if not HASH_RE.fullmatch(row["phase_test_sha256"].strip()):
                problems.append(f"{key}: phase_test_sha256 is not a SHA256")
        else:
            missing.append(f"{key}: phase_test_sha256")
        phase = row.get("measured_phase")
        if supplied(phase) and phase != "MATCH":
            problems.append(f"{key}: measured phase is not MATCH")
        if supplied(row.get("status")) and row["status"] != "SUPPLIER_PROPOSED":
            problems.append(f"{key}: unexpected row status, use SUPPLIER_PROPOSED")
        if all(supplied(row.get(field)) for field in FIELDS[4:]):
            reviewed_count += 1
    # CT has no model-defined DOT relationship. The vendor drawing can be
    # internally self-consistent, but cannot "prove" relative sign without an
    # independently witnessed low-energy phasing test.
    ct_pri = [observed_dot.get(("CT", x)) for x in ("PRI_A", "PRI_B")]
    ct_sec = [observed_dot.get(("CT", x)) for x in ("SEC_A", "SEC_B")]
    for label, pair in (("CT primary", ct_pri), ("CT secondary", ct_sec)):
        if all(v in ("DOT", "NON_DOT") for v in pair) and set(pair) != {"DOT", "NON_DOT"}:
            problems.append(f"{label}: expected exactly one DOT terminal")
    status = ("CONTRACT_REJECTED" if problems else
              "INCOMPLETE_VENDOR_PACKET" if missing else
              "REVIEW_PACKAGE_COMPLETE_NOT_APPROVED")
    return {
        "kind": "D1_MAGNETIC_VENDOR_TERMINAL_AUDIT",
        "status": status,
        "required_logical_terminal_count": len(expected),
        "submitted_unique_terminal_count": len(provided),
        "rows_with_all_response_fields": reviewed_count,
        "errors": problems,
        "pending_fields": missing,
        "ct_relative_phase_independently_proven": False,
        "supplier_document_authenticity_verified": False,
        "physical_pad_map_verified": False,
        "native_cad_replaced_with_real_footprints": False,
        "hardware_qualified": False,
        "fabrication_approved": False,
        "human_review_mandatory": True,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--write-template", type=Path)
    p.add_argument("--input", type=Path)
    p.add_argument("--output", type=Path)
    opts = p.parse_args()
    if opts.write_template:
        write_template(opts.write_template)
        print("Wrote nonpassing 24-terminal supplier response template")
        return 0
    if not opts.input:
        p.error("--input is required unless --write-template is specified")
    try:
        rows = load_rows(opts.input)
        result = evaluate(rows)
        result["input_sha256"] = hashlib.sha256(opts.input.read_bytes()).hexdigest()
        exit_code = (0 if result["status"] == "REVIEW_PACKAGE_COMPLETE_NOT_APPROVED"
                     else 2 if result["status"] == "CONTRACT_REJECTED" else 1)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result = {"kind": "D1_MAGNETIC_VENDOR_TERMINAL_AUDIT",
                  "status": "INVALID_PACKET", "errors": [str(exc)],
                  "physical_pad_map_verified": False,
                  "fabrication_approved": False}
        exit_code = 2
    data = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if opts.output:
        opts.output.parent.mkdir(parents=True, exist_ok=True)
        opts.output.write_text(data, encoding="utf-8", newline="\n")
    print(data)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

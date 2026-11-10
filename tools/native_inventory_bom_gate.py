"""Check actual native EasyEDA inventory's Manufacturer ID/Supplier ID/Value.

This is deliberately DIFFERENT from a value-only ECO: the native CAD source
stores both Value and a physical manufacturer part number. A correct text
value does not make the purchase code correct. This source is a Nov 6 snapshot,
NOT a refreshed manufacturing approval.

Usage:
 python tools/native_inventory_bom_gate.py --check
 python tools/native_inventory_bom_gate.py --write
 python tools/native_inventory_bom_gate.py --release-check   # fails closed
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "hardware/dcx_main/gen/native_inventory_raw.json"
REGISTER = ROOT / "hardware/dcx_main/placeholder_eco.json"
OUTPUT = ROOT / "hardware/dcx_main/native_inventory_bom_gate.json"
KNOWN = {
    "CL10B104KB8NNNC": {
        "physical": "100nF",
        "supplier": "C1591",
        "manufacturer": "Samsung Electro-Mechanics",
    },
    "0603WAF1002T5E": {
        "physical": "10kΩ",
        "supplier": "C25804",
        "manufacturer": "UNI-ROYAL",
    },
}


def _resolve_r8(by_ref: dict, placeholder: list) -> tuple[dict, str]:
    """Locate the EN pull-up in a capture whose export may have renamed it.

    ``docs/agent/EDA.md`` §装配排除 ECO: excluding a part from BOM/PCB makes the
    export renumber it (R8 -> R6) while its pins stay identical, so a designator
    lookup alone cannot tell "DNP'd" from "deleted".  Accept the rename ONLY when
    the capture proves the double DNP AND the row still carries R8's registered
    library device.  A renamed-but-populated part matches nothing here, so the
    audit fails closed instead of reporting a clean BOM.
    """
    direct = by_ref.get("R8")
    if direct is not None:
        return direct, "designator"
    row = next((r for r in placeholder if r["ref"] == "R8"), None)
    if row is None:
        raise ValueError("placeholder register has no R8 row")
    matches = [c for c in by_ref.values()
               if c.get("manufacturer_id") == row["native_device"]
               and c.get("add_into_bom") is False
               and c.get("add_into_pcb") is False]
    if len(matches) != 1:
        raise ValueError(
            "missing native R8 and {} double-DNP candidate(s) carrying {}; "
            "cannot check default enable".format(len(matches), row["native_device"]))
    return matches[0], "double-dnp-designator-fallback"


def audit(inventory: Path | None = None) -> dict:
    source = INVENTORY if inventory is None else inventory
    captured = json.loads(source.read_text(encoding="utf-8"))
    if not captured.get("ok") or captured.get("value", {}).get("status") != "INVENTORY":
        raise ValueError("actual native inventory capture missing or unsuccessful")
    n = captured["value"]
    components = n["components"]
    if n["primitive_count"] != len(components):
        raise ValueError("inconsistent native inventory count")
    by_ref = {c["ref"]: c for c in components}
    if len(by_ref) != len(components):
        raise ValueError("duplicate native designator")
    register = json.loads(REGISTER.read_text(encoding="utf-8"))
    placeholder = register["rows"]
    if len({r["ref"] for r in placeholder}) != len(placeholder):
        raise ValueError("duplicate placeholder reference")
    r8_row, r8_identified_by = _resolve_r8(by_ref, placeholder)
    if "R8" not in by_ref:
        # Audit the renamed part under its registered designator so that every
        # later lookup (conflicts, R8 flags) reads the same row.
        by_ref = {**by_ref, "R8": r8_row}
    unknown_refs = sorted(r["ref"] for r in placeholder if r["ref"] not in by_ref)
    if unknown_refs:
        raise ValueError("missing native refs: " + repr(unknown_refs))
    known = [r for r in placeholder
             if r["native_device"] in KNOWN and r["target_value"] is not None]
    errors = []
    for r in known:
        actual = by_ref[r["ref"]]
        mpn = r["native_device"]
        physical = KNOWN[mpn]
        # R8 is the unsafe VCC12->RUN assembly pull-up. If the ACTUAL native
        # capture says BOTH BOM and PCB are disabled, it is deliberately DNP.
        # A DNP part is not a physical wrong-value purchase. A partial DNP
        # (only one flag disabled) still counts as a blocker.
        if (r["ref"] == "R8"
                and actual["add_into_bom"] is False
                and actual["add_into_pcb"] is False):
            continue
        # The register records the PRE-ECO library identity. A real manufacturer
        # swap must not crash the audit, but it must also never disappear from
        # the 51-row coverage merely because its old MPN has been changed.
        # Without independently authenticated OEM electrical and footprint
        # evidence we cannot infer the new device's physical value from text.
        if (actual["manufacturer_id"] != mpn
                or actual["supplier_id"] != physical["supplier"]
                or not isinstance(actual.get("component"), dict)
                or actual["component"].get("name") != mpn):
            errors.append({
                "ref": r["ref"],
                "role": r["part_role"],
                "priority": r["priority"],
                "design_target": r["target_value"],
                "actual_native_display": actual["value"],
                "native_manufacturer_id": actual["manufacturer_id"],
                "native_supplier_id": actual["supplier_id"],
                "manufacturer_nominal": None,
                "manufacturer_vs_design_target": None,
                "display_vs_manufacturer": False,
                "display_vs_design_target": actual["value"] != r["target_value"],
                "add_into_bom": actual["add_into_bom"],
                "add_into_pcb": actual["add_into_pcb"],
                "datasheet_from_captured_native": actual["datasheet"],
                "missing_real_native_cad_edit": False,
                "change_classification": "UNVERIFIED_NATIVE_OEM_OR_LIBRARY_CHANGE",
                "previous_native_mpn": mpn,
                "manufacturer_identity_or_value_verified": False,
                "required_action": (
                    "Verify real OEM datasheet/value, supplier code, component "
                    "library identity, pad mapping and original CAD persistence; "
                    "do not count an unreviewed MPN replacement as a clean BOM"
                ),
            })
            continue
        if physical["physical"] == r["target_value"]:
            continue
        errors.append({
            "ref": r["ref"],
            "role": r["part_role"],
            "priority": r["priority"],
            "design_target": r["target_value"],
            "actual_native_display": actual["value"],
            "native_manufacturer_id": actual["manufacturer_id"],
            "native_supplier_id": actual["supplier_id"],
            "manufacturer_nominal": physical["physical"],
            "manufacturer_vs_design_target": True,
            "display_vs_manufacturer": actual["value"] != physical["physical"],
            "display_vs_design_target": actual["value"] != r["target_value"],
            "add_into_bom": actual["add_into_bom"],
            "add_into_pcb": actual["add_into_pcb"],
            "datasheet_from_captured_native": actual["datasheet"],
            "missing_real_native_cad_edit": True,
        })
    r8 = by_ref["R8"]
    try:
        source_label = source.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        source_label = str(source)
    return {
        "status": "NATIVE_CAPTURE_NOT_FOR_FAB_BOM_AND_ENABLE_BLOCKED",
        "snapshot_source": source_label,
        "snapshot_age_note": (
            "This is the captured Nov 6 unmodified original. A saved ECO on a COPY is not a modification of the active .eprj2."
            if not any(e.get("change_classification") for e in errors)
            and (r8["add_into_bom"] is True or r8["add_into_pcb"] is True)
            else "Capture differs from the original or contains R8 DNP; re-open the saved authoritative native project and independently verify BOM/PCB exports. This capture alone is not an EDA or fab signoff."
        ),
        "register_source": "hardware/dcx_main/placeholder_eco.json",
        "native_components": len(components),
        "register_placeholder_rows": len(placeholder),
        "known_mpn_and_target_rows": len(known),
        "manufacturer_target_conflicts": len(errors),
        "native_display_vs_manufacturer_conflicts": sum(
            e["display_vs_manufacturer"] for e in errors),
        "display_not_yet_at_design_target": sum(
            e["display_vs_design_target"] for e in errors),
        "original_r8_in_bom": r8["add_into_bom"],
        "original_r8_in_pcb": r8["add_into_pcb"],
        "r8_identified_by": r8_identified_by,
        "r8_capture_designator": r8_row["ref"],
        "conflicts": errors,
        "manufacturing_approved": False,
        "native_cad_modified": False,
        "next_action": "Edit real native EasyEDA devices and BOM entries; re-export inventory, BOM, and netlist; check R8 true DNP/default inhibit; verify supplier MPN and footprints before quote or fab.",
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true")
    group.add_argument("--check", action="store_true")
    group.add_argument("--release-check", action="store_true")
    p.add_argument("--inventory", type=Path, default=None,
                   help="capture to audit; defaults to the Nov 6 main-board snapshot")
    p.add_argument("--out", type=Path, default=None,
                   help="report path used by --write/--check; defaults to OUTPUT")
    args = p.parse_args(argv)
    report = audit(args.inventory)
    out = OUTPUT if args.out is None else args.out
    if args.write:
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        return 0
    if args.check:
        actual = json.loads(out.read_text(encoding="utf-8")) if out.exists() else None
        if actual != report:
            print("Native inventory risk report stale / missing: regenerate --write")
            return 1
        print("Known native BOM mismatches:", report["manufacturer_target_conflicts"],
              "R8 still BOM+PCB:", report["original_r8_in_bom"],
              report["original_r8_in_pcb"], "NOT_FOR_FAB")
        return 0
    # This gate is intentionally NOT a general manufacturing approval.
    if report["manufacturer_target_conflicts"] or report["original_r8_in_bom"] or report["original_r8_in_pcb"]:
        print("BLOCKED: native MPN mismatches and/or active R8 enable; not fit to order")
        return 2
    print("Native BOM checks only: other fabrication and hardware gates remain.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

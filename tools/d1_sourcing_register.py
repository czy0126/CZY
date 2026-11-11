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
from performance_first_design import (
    COUT_ESR_RFQ_TARGET_MOHM,
    COUT_VRATED_MIN,
    COUT_VRATED_PREFERRED,
)

ROOT = Path(__file__).resolve().parent.parent
HW = ROOT / "hardware/dcx_main"
REVIEW = HW / "pin_footprint_review.csv"
BOM = ROOT / "design/v3/bom/bom_draft.csv"
CONTRACT = HW / "magnetics_symbol_contract.json"
REG = HW / "component_decision_register.json"
VENDOR = HW / "vendor_terminal_request.json"
COUT_DOSSIER = HW / "g2/cout_oem_candidate.json"
HIGH = {"T1", "T2", "T3", "T4", "CT", "Lr", "Cr",
        "Cin", "Cout", "D_BT", "J_IN", "J_OUT"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _verified_cout(dossier: dict) -> dict:
    """Identity of the OEM-verified Cout candidate, with its RFQ gaps.

    The datasheet archive is the source of truth.  A verified identity is not a
    release: the flags below record that the part misses the P0 high-voltage
    and hot-ESR asks, so the item stays PENDING.
    """
    main = dossier["main_energy_storage"]
    rated = main["rated"]
    bank = main["preliminary_parallel_bank"]
    n = bank["quantity"]
    esr_mohm = rated["esr_mohm_at_100khz_25c_MAX"]
    bank_esr_mohm = esr_mohm / n
    v = rated["rated_voltage_v"]
    f_mid = (rated["F_oem_terminal_mm_min"] + rated["F_oem_terminal_mm_max"]) / 2
    f_tol = (rated["F_oem_terminal_mm_max"] - rated["F_oem_terminal_mm_min"]) / 2
    t_max = rated["temp_range_c"][1]
    life_h = rated["life_at_105c_hours"]
    mpn = main["exact_mpn"]
    limits = main["series_datasheet_esr_limits"]
    eol_multiple = limits["endurance_105c_rated_voltage_2000h_esr_max_multiple_of_initial"]
    return {
        "verified_mpn": mpn,
        "manufacturer_datasheet": main["source_oem"],
        "status": "PENDING_FOOTPRINT_HV_RATING_AND_HOT_ESR_SIGNOFF",
        "exact_part_datasheet_archive": main["oem_archive"],
        "exact_part_datasheet_verified": True,
        "supplier_rfq_high_voltage_target_met": v >= COUT_VRATED_MIN,
        "nominal_100khz_25c_esr_screen_met": bank_esr_mohm <= COUT_ESR_RFQ_TARGET_MOHM,
        # No operating-condition bank ESR evidence is consumed by this generator.
        # Increasing N must not turn a room-temperature screen into hot approval.
        "supplier_rfq_low_esr_target_met": False,
        "operating_condition_esr_evidence_status": "NOT_VERIFIED",
        "issues": [
            f"{mpn} is {v:g} V rated, below the P0 performance-first high-voltage RFQ "
            f">= {COUT_VRATED_MIN:g} V ({COUT_VRATED_PREFERRED:g} V preferred); "
            "cannot close P0 sourcing/approval",
            f"Nominal bank ESR {esr_mohm:g} mOhm/{n} = {bank_esr_mohm:g} mOhm at 100 kHz/25 C "
            f"{'passes' if bank_esr_mohm <= COUT_ESR_RFQ_TARGET_MOHM else 'fails'} only the nominal screen "
            f"<= {COUT_ESR_RFQ_TARGET_MOHM:g} mOhm; actual temperature/frequency compliance "
            "remains unverified regardless of parallel count",
            f"Manufacturer F={f_mid:g} +/-{f_tol:g} mm is a body termination dimension, "
            "not a released pad/land-pattern; the actual native placeholder differs",
            f"200 kHz and DC-bias ESR are unpublished for this voltage rating; the series "
            f"states only a 100 kHz/25 C maximum, and the {t_max} C/{life_h} h endurance "
            f"limit allows ESR to rise to {eol_multiple:g}x initial "
            f"({bank_esr_mohm:g} -> {bank_esr_mohm * eol_multiple:g} mOhm parts only), "
            "so neither hot nor end-of-life ESR can close the same performance-first ask",
            f"capacitor-to-capacitor current sharing and {v:g} V transient overshoot are "
            "not certified",
        ],
    }


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
    dossier = json.loads(COUT_DOSSIER.read_text(encoding="utf-8"))
    for item in selection:
        if item["ref"] != "Cout":
            continue
        if not dossier["gates"]["exact_oem_part_spec_archive_hash_verified"]:
            continue
        extra = _verified_cout(dossier)
        issues = extra.pop("issues")
        item.update(extra)
        item["issues"] = item["issues"] + issues
        item["existing_value_or_rating"] = item["existing_value_or_rating"].replace(
            "part data unverified",
            f"{item['verified_mpn']} individual part parameters OEM verified; "
            "not released for this PCB")
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
    print("61-part sourcing register and 5-magnetic vendor request: "
          "only the dossier-backed Cout identity is verified, and it stays PENDING")


if __name__ == "__main__":
    raise SystemExit(main())

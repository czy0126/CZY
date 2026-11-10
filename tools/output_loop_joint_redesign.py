"""Evaluate a 2-pole, lower-joint-count 100A interface as a CAD ECO option.

This does not replace native CAD or measured contact resistance. In particular,
a "two-contact" drawing is valid only if the engineer can demonstrate exactly
one counted separable joint *on each rail*, with all remaining inseparable
joins and transitions measured/allocated in the PCB reserve, not deleted.

Usage: python tools/output_loop_joint_redesign.py --write | --check
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from connector_budget import DESIGN_BASIS_OHM
from g1_current_neck_screen import report as native_neck_report
from output_loop_budget import (
    CONTACT_SCENARIOS_UOHM, CURRENT_A, RESERVED_PCB_UOHM,
    TEMPERATURE_C, ROOT, loop_resistance, report as existing_report,
)

OUTPUT = ROOT / "hardware/dcx_main/output_joint_reduction_cases.json"
# (name, contact count both rails, width, thickness, length).
# All geometry is a design *proposal*, not a supplier-confirmed assembly.
OPTIONS = (
    ("baseline_4_contacts_30x2x25", 4, 30.0, 2.0, 25.0),
    ("wide_4_contacts_50x2x15", 4, 50.0, 2.0, 15.0),
    ("reduced_2_contacts_30x2x25", 2, 30.0, 2.0, 25.0),
    ("reduced_2_contacts_50x1x15", 2, 50.0, 1.0, 15.0),
    ("reduced_2_contacts_50x2x15", 2, 50.0, 2.0, 15.0),
    ("reduced_2_contacts_50x2x25", 2, 50.0, 2.0, 25.0),
)


def evaluate(name: str, contacts: int, width: float,
             thickness: float, length: float) -> dict:
    if contacts < 2 or contacts % 2:
        raise ValueError("must account for both power rails")
    bar = loop_resistance(width, thickness, length, 0,
                          contact_count=contacts)["bar_pair_ohm"]
    results = {}
    for joint in CONTACT_SCENARIOS_UOHM:
        r = loop_resistance(width, thickness, length, joint,
                            contact_count=contacts)["loop_ohm"]
        key = str(round(joint))
        results[key] = {
            "total_uohm": round(r * 1e6, 3),
            "margin_to_150uohm": round((DESIGN_BASIS_OHM - r) * 1e6, 3),
            "power_w_at_100a": round(CURRENT_A ** 2 * r, 5),
            "drop_mv_at_100a": round(CURRENT_A * r * 1e3, 4),
            "passes_resistance_arithmetic_only": r <= DESIGN_BASIS_OHM,
        }
    return {
        "id": name,
        "total_counted_separable_contacts": contacts,
        "assumed_counted_contacts_per_pole": contacts // 2,
        "rail_count": 2,
        "width_mm_each_rail": width,
        "thickness_mm_each_rail": thickness,
        "length_mm_each_rail": length,
        "bar_pair_uohm_at_100c": round(bar * 1e6, 3),
        "max_joint_uohm_each_including_pcb_reserve": round(
            (DESIGN_BASIS_OHM - bar - RESERVED_PCB_UOHM * 1e-6)
            * 1e6 / contacts, 3),
        "joint_scenarios_uohm": results,
        "geometry_verified": False,
        "contact_count_verified": False,
        "hardware_qualified": False,
    }


def report() -> dict:
    baseline = existing_report()
    g1 = native_neck_report()
    scenarios = g1["scenarios"]
    if (len(scenarios) != 4 or not all(not x["within_complete_rail_budget"] for x in scenarios)
            or g1["fabrication_approved"] is not False):
        raise ValueError("G1 native high-current neck design changed; re-review output joints")
    if (baseline["status"] != "CONCEPT_SCREEN_ONLY_NOT_FOR_FAB"
            or baseline["total_unverified_joints"] != 4
            or baseline["number_of_current_rails"] != 2):
        raise ValueError("old baseline contract changed; re-review concept")
    rows = [evaluate(*t) for t in OPTIONS]
    return {
        "status": "UNVERIFIED_INTERFACE_TOPOLOGY_REDESIGN_NOT_FOR_FAB",
        "hardware_qualified": False,
        "fabrication_approved": False,
        "reference": "hardware/dcx_main/output_loop_candidates.json",
        "design_basis_uohm_both_rails": round(DESIGN_BASIS_OHM * 1e6, 3),
        "design_basis_is_internal_not_regulatory_or_measured": True,
        "temperature_c_assumed": TEMPERATURE_C,
        "current_a_assumed": CURRENT_A,
        "reserved_pcb_uohm_unverified": RESERVED_PCB_UOHM,
        "per_joint_uohm_scenarios_unverified": list(CONTACT_SCENARIOS_UOHM),
        "feasibility_deduction": {
            "four_contacts_each_50uohm_exceed_budget_before_copper": (
                4 * 50 > DESIGN_BASIS_OHM * 1e6),
            "four_contacts_only_joints_uohm_at_50": 200,
            "max_even_contact_count_at_50uohm_with_30uohm_pcb_reserve": 2,
            "two_contacts_require_one_verified_separable_joint_per_pole": True,
            "any_unmodelled_weld_solder_bond_or_external_connector_must_be_counted": True,
        },
        "candidates": rows,
        "current_native_g1_feeder_screen": {
            "status": "MUST_REPLACE_NATIVE_G1_NARROW_FEEDERS_BEFORE_G2",
            "reference": "hardware/dcx_main/g1/g1_100a_copper_neck_screen.json",
            "native_cad_sha256": g1["native_cad_sha256"],
            "optimistic_min_combined_necks_uohm": min(x["combined_necks_uohm"] for x in scenarios),
            "even_210um_exceeds_whole_loop_budget": all(not x["within_complete_rail_budget"] for x in scenarios),
            "candidate_bars_and_joint_arithmetic_includes_these_necks": False,
            "physical_copper_replacement_required": True,
            "fab_approved": False,
        },
        "next_eda_action": (
            "CAD engineer must identify VOUT and PGND from SR-Cout pads to "
            "external load as two explicit physical rails, draw separately "
            "a 4-contact low-R option and a 2-contact integrated copper "
            "inlay/busbar option; enumerate every transition, bolt, solder "
            "bond and Kelvin probe point. A missing interface cannot be "
            "considered 0-ohm; allocate any inseparable joints to the PCB "
            "reserve. Existing native G1 1mm CTAP/SR feeder necks must be replaced "
            "with a short high-cross-section interface, not merely thicker foil. "
            "No pad, clearance or ≤16mm height frozen yet."
        ),
        "required_measurement": (
            "Kelvin 4-wire resistance for full positive+return loop and "
            "each separable joint at specified torque, plating and temperature "
            "(incl 100C worst case), plus current balance and contact hot "
            "spots at staged loads. Actual copper/inlay geometry, all pad "
            "neckdowns/vias and source-to-load terminals must be identified."
        ),
        "not_qualified": [
            "Neither 20 nor 50 microohm per contact is measured.",
            "Reducing counted connections on paper is not reducing real losses.",
            "Current crowding, neckdowns, skin/proximity and thermal rise unknown.",
            "One counted contact/pole requires a manufacturable monolithic or "
            "integrated interface; other joints still resistive and must be budgeted.",
            "The actual reopened G1 native EasyEDA PCB has 1mm CTAP/SR current necks "
            "that fail the complete-loop copper budget even with assumed 210um copper; "
            "3D assembly and supplier DFM remain unverified.",
            "R8, OEM manufacturer MPNs, magnetic pads and hardware fault shutoff remain blocked.",
        ],
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = p.parse_args(argv)
    value = report()
    if args.write:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")
        return 0
    if args.check:
        if not OUTPUT.is_file():
            print("missing joint-reduction report: run --write")
            return 2
        if json.loads(OUTPUT.read_text(encoding="utf-8")) != value:
            print("stale joint-reduction concept: run --write")
            return 2
        print("current joint-reduction concept, still NOT_FOR_FAB")
        return 0
    print(json.dumps(value, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Two-polarity 100 A output-loop copper/joint feasibility screen.

The historical connector_budget.py estimates one bar and two contacts. A real
load-current loop also includes VOUT and PGND, both connections and the PCB
spread/via allowance. This source-backed calculation refuses to promote any
hypothetical contact resistance into a manufacturing approval.

DC I^2 R at a specified conductor temperature only. It is NOT AC loss,
thermal signoff, current-sharing verification, DRC, or a CAD busbar drawing.

Usage:
  python tools/output_loop_budget.py --write
  python tools/output_loop_budget.py --check
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from connector_budget import DESIGN_BASIS_OHM, OUTPUT_CURRENT_A, busbar_resistance

ROOT = Path(__file__).resolve().parent.parent
REFERENCE = ROOT / "hardware/dcx_mech/routed_copper.json"
RESULT = ROOT / "hardware/dcx_main/output_loop_candidates.json"

# Concept geometry only: positive AND return bar, same proposed dimensions.
# Not checked against magnetic terminal, PCB pad, cold plate, or isolation.
CANDIDATES = (
    ("thin_0p5mm", 20.0, 0.5, 25.0),
    ("compact_1mm", 30.0, 1.0, 15.0),
    ("extended_1mm", 30.0, 1.0, 25.0),
    ("thick_2mm", 30.0, 2.0, 25.0),
)
TEMPERATURE_C = 100.0  # conservative resistance scenario, NOT verified T
CONTACTS_TOTAL = 4  # conceptual two terminals per polarity, must map actual CAD
RESERVED_PCB_UOHM = 30.0  # DESIGN ALLOCATION, not a measured impedance
CONTACT_SCENARIOS_UOHM = (20.0, 50.0)
CURRENT_A = 100.0


def loop_resistance(width_mm: float, thickness_mm: float, length_mm: float,
                    contact_uohm: float, reserve_uohm: float = RESERVED_PCB_UOHM,
                    temperature_c: float = TEMPERATURE_C,
                    contact_count: int = CONTACTS_TOTAL) -> dict:
    if min(width_mm, thickness_mm, length_mm) <= 0:
        raise ValueError("positive copper geometry required")
    if contact_uohm < 0 or reserve_uohm < 0:
        raise ValueError("contact and reserve resistance must be nonnegative")
    # A two-rail output contract must count every assumed contact on BOTH
    # poles. Only even positive totals are accepted. This is an electrical
    # accounting parameter; it never asserts a physically feasible topology.
    if type(contact_count) is not int or contact_count < 2 or contact_count % 2:
        raise ValueError("both-rail contact_count must be an even integer >= 2")
    one = busbar_resistance(length_mm / 1000, width_mm / 1000,
                            thickness_mm / 1000, temperature_c)
    two = 2 * one  # both outgoing and return rails carry full current
    total = two + contact_count * contact_uohm * 1e-6 + reserve_uohm * 1e-6
    return {"bar_pair_ohm": two, "loop_ohm": total}


def scenario(name: str, w: float, t: float, length: float) -> dict:
    low = loop_resistance(w, t, length, CONTACT_SCENARIOS_UOHM[0])
    high = loop_resistance(w, t, length, CONTACT_SCENARIOS_UOHM[1])
    bar_pair = low["bar_pair_ohm"]
    max_contact = (DESIGN_BASIS_OHM - bar_pair
                   - RESERVED_PCB_UOHM * 1e-6) / CONTACTS_TOTAL
    return {
        "candidate": name,
        "width_mm_per_rail": w,
        "thickness_mm_per_rail": t,
        "length_mm_per_rail": length,
        "bars_pair_uohm": round(bar_pair * 1e6, 3),
        "budget_uohm_loop": round(DESIGN_BASIS_OHM * 1e6, 3),
        "reserved_pcb_uohm": RESERVED_PCB_UOHM,
        "joint_limit_uohm_each": round(max_contact * 1e6, 3),
        "total_uohm_at_20u_joint": round(low["loop_ohm"] * 1e6, 3),
        "total_uohm_at_50u_joint": round(high["loop_ohm"] * 1e6, 3),
        "loss_w_at_20u_joint": round(CURRENT_A ** 2 * low["loop_ohm"], 5),
        "drop_mv_at_20u_joint": round(CURRENT_A * low["loop_ohm"] * 1e3, 4),
        "screen_pass_20u_joint": low["loop_ohm"] <= DESIGN_BASIS_OHM,
        "screen_pass_50u_joint": high["loop_ohm"] <= DESIGN_BASIS_OHM,
    }


def report() -> dict:
    source = json.loads(REFERENCE.read_text(encoding="utf-8"))
    if source.get("results", {}).get("power_path_meets_the_0p15_mohm_basis") is not False:
        raise ValueError("upstream copper status changed: reassess reference")
    if source.get("status") != "ROUTED_DRAFT_CONNECTIVITY_ONLY_AMPACITY_NOT_MET":
        raise ValueError("upstream route classification changed: reassess")
    return {
        "status": "CONCEPT_SCREEN_ONLY_NOT_FOR_FAB",
        "hardware_qualified": False,
        "fabrication_approved": False,
        "reference": "hardware/dcx_mech/routed_copper.json",
        "reference_status": source["status"],
        "reference_ampacity_qualified": False,
        "budget_ohm_loop": DESIGN_BASIS_OHM,
        "current_a": CURRENT_A,
        "copper_temperature_c_assumed": TEMPERATURE_C,
        "number_of_current_rails": 2,
        "total_unverified_joints": CONTACTS_TOTAL,
        "reserved_pcb_uohm_unverified": RESERVED_PCB_UOHM,
        "contact_cases_uohm_each_unverified": list(CONTACT_SCENARIOS_UOHM),
        "cases": [scenario(*s) for s in CANDIDATES],
        "open": [
            "actual VOUT/PGND terminals, PCB spread and vias must replace reserve",
            "measure each joint by calibrated four-wire Kelvin method at load",
            "2V/100A output regulation and both-rail hot spots not measured",
            "verify magnetics/PCB/TIM/cold-plate height stack and 3D collisions",
            "model current distribution and AC ripple proximity/skin losses",
            "vendor MPN, torque, plating, insulation, creepage and safety review",
            "no physical sample, GUI DRC, thermal or continuous-power signoff",
        ],
        "notes": "20/50 uohm joints are scenarios, not vendor claims; pass is arithmetic only.",
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    action = p.add_mutually_exclusive_group()
    action.add_argument("--write", action="store_true")
    action.add_argument("--check", action="store_true")
    args = p.parse_args(argv)
    content = report()
    if args.write:
        RESULT.parent.mkdir(parents=True, exist_ok=True)
        RESULT.write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")
    elif args.check:
        if not RESULT.is_file() or json.loads(RESULT.read_text(encoding="utf-8")) != content:
            print("output loop candidate report drift or absent; rerun --write")
            return 1
    else:
        print(json.dumps(content, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

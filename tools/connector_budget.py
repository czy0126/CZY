"""Output connector / busbar sizing against the 0.1 mohm path budget.

At 100 A every 0.1 mohm is 1.0 W, which is why the output path is worth sizing
rather than eyeballing.  Two of the three resistances in that path are computable
from geometry exactly:

    R_bar = rho(T) * L / (w * t)          copper, textbook
    dT    = I^2 * R / (h * A_surface)     natural convection, h is a range

The third -- contact resistance of a bolted or soldered joint -- is NOT
computable from anything in this repository.  It depends on plating, torque,
surface finish and whether the joint is press-fit, and the datasheets are not
available in this environment.  It is therefore carried as an explicit input
defaulting to a placeholder, and reported as UNVERIFIED with a first-article
four-wire measurement as the closing action.  Do not let it silently become a
number: it is usually the largest term in a high-current path.

Usage:
    python tools/connector_budget.py --json design/v3/bom/connector_budget.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

COPPER_RHO_20 = 1.724e-8      # ohm*m, annealed copper
ALPHA_CU = 0.00393            # 1/K
T_REF_C = 20.0

# Bare copper in still air, vertical.  Handbook range is roughly 4-8 W/m2K; the
# spread is why every temperature below is reported as a range and not a value.
H_CONV_RANGE = (4.0, 8.0)
T_AMB_C = 40.0                # ampacity convention; matches the stage-F matrix top row

OUTPUT_CURRENT_A = 100.0
OUTPUT_I_RMS_A = 99.8         # measured, iout_from_v_a
INPUT_CURRENT_RMS_A = 6.746   # measured half-bridge input RMS
INPUT_CURRENT_PEAK_A = 13.88  # I(Lr) steady peak

PATH_BUDGET_OHM = 0.1e-3      # self-chosen; the project has no Vout-drop spec

# The 92.33 % system efficiency published in the magnetics package is carried at a
# 0.15 mohm output path costing 1.495 W.  PATH_BUDGET_OHM above is stricter, and the
# two numbers are both self-chosen -- judging the connector against 0.1 while the
# efficiency claim rests on 0.15 makes the two documents contradict each other.
# The design basis is reported alongside the strict target because it is the one
# that yields a per-joint limit the first article can be measured against.
DESIGN_BASIS_OHM = 0.15e-3

BUS_WIDTH_M = 20e-3
BUS_THICKNESS_M = 2e-3
BUS_LENGTH_M = 0.080

# Placeholder only: a clean bolted copper-to-copper joint is often quoted at
# 20-100 uohm, but nothing in this repo or its reachable sources establishes a
# figure for the chosen hardware.  Kept as an input so its weight is visible.
CONTACT_OHM_PLACEHOLDER = 50e-6
CONTACTS_PER_PATH = 2


def copper_rho(temp_c: float, rho_20: float = COPPER_RHO_20,
               alpha: float = ALPHA_CU, t_ref_c: float = T_REF_C) -> float:
    """Copper resistivity at temperature, linear in K."""
    return rho_20 * (1.0 + alpha * (temp_c - t_ref_c))


def busbar_resistance(length_m: float, width_m: float, thickness_m: float,
                      temp_c: float = T_REF_C) -> float:
    """Conductor resistance.  Exact for a rectangular bar of uniform temperature."""
    area = width_m * thickness_m
    if length_m <= 0 or area <= 0:
        raise ValueError("length and cross-section must be positive")
    return copper_rho(temp_c) * length_m / area


def surface_area(length_m: float, width_m: float, thickness_m: float) -> float:
    """Exposed face and edge area of a bar, ignoring the two ends."""
    return 2.0 * (width_m + thickness_m) * length_m


def temperature_rise(i_a: float, length_m: float, width_m: float, thickness_m: float,
                     h_w_m2k: float = 5.5, t_amb_c: float = T_AMB_C,
                     iterations: int = 60) -> float:
    """Steady-state rise above ambient, with rho re-evaluated as the bar warms.

    Resistance and temperature feed each other, so this is a fixed-point solve;
    60 iterations is far past convergence for the thermal time constants here.
    """
    if i_a < 0:
        raise ValueError("current must not be negative")
    area = surface_area(length_m, width_m, thickness_m)
    rise = 0.0
    for _ in range(iterations):
        r = busbar_resistance(length_m, width_m, thickness_m, t_amb_c + rise)
        power = i_a * i_a * r
        rise = power / (h_w_m2k * area)
    return rise


def length_for_resistance(r_ohm: float, width_m: float, thickness_m: float,
                          temp_c: float = T_REF_C) -> float:
    """How long a bar can be and still stay inside a resistance budget."""
    if r_ohm <= 0:
        raise ValueError("resistance budget must be positive")
    return r_ohm * width_m * thickness_m / copper_rho(temp_c)


def contact_weight(contact_ohm: float = CONTACT_OHM_PLACEHOLDER,
                   contacts: int = CONTACTS_PER_PATH,
                   budget_ohm: float = PATH_BUDGET_OHM) -> dict[str, object]:
    """How much of the path budget the joints would consume, if the placeholder holds."""
    total = contact_ohm * contacts
    return {
        "contact_ohm_each": contact_ohm,
        "contacts": contacts,
        "contact_total_ohm": total,
        "frac_of_budget": total / budget_ohm,
        "leaves_ohms": budget_ohm - total,
        "status": "UNVERIFIED placeholder - measure at first article",
    }


def output_path(i_a: float = OUTPUT_CURRENT_A,
                budget_ohm: float = PATH_BUDGET_OHM) -> dict[str, object]:
    """Busbar geometry inside the remaining budget, with the rise it actually runs at.

    `bar_budget` can come out negative: the placeholder joints alone can exceed the
    whole path budget.  That is reported as `feasible: False` with the shortfall
    spelled out, because the alternative -- clamping it to zero and printing a
    plausible bar -- is how a budget quietly stops meaning anything.
    """
    contact = contact_weight(budget_ohm=budget_ohm)
    bar_budget = budget_ohm - contact["contact_total_ohm"]
    feasible = bar_budget > 0
    r_bar = busbar_resistance(BUS_LENGTH_M, BUS_WIDTH_M, BUS_THICKNESS_M)
    rises = {h: temperature_rise(i_a, BUS_LENGTH_M, BUS_WIDTH_M, BUS_THICKNESS_M, h)
             for h in H_CONV_RANGE}
    total = r_bar + contact["contact_total_ohm"]
    return {
        "current_a": i_a,
        "budget_ohm": budget_ohm,
        "budget_w": i_a * i_a * budget_ohm,
        "contact": contact,
        "feasible_with_placeholder_contacts": feasible,
        "joint_shortfall_ohm": max(0.0, -bar_budget),
        "bar": {
            "width_mm": BUS_WIDTH_M * 1e3,
            "thickness_mm": BUS_THICKNESS_M * 1e3,
            "length_mm": BUS_LENGTH_M * 1e3,
            "resistance_ohm": r_bar,
            "power_w": i_a * i_a * r_bar,
            "max_length_for_budget_mm": (
                length_for_resistance(bar_budget, BUS_WIDTH_M, BUS_THICKNESS_M) * 1e3
                if feasible else None),
            "rise_range_k": {"h=4": rises[4.0], "h=8": rises[8.0]},
        },
        "total_ohm_placeholder": total,
        "total_power_w_placeholder": i_a * i_a * total,
    }


def feasibility(i_a: float = OUTPUT_CURRENT_A) -> dict[str, object]:
    """What the path costs at several joint resistances -- the budget is a choice, not a fact."""
    r_bar = busbar_resistance(BUS_LENGTH_M, BUS_WIDTH_M, BUS_THICKNESS_M)
    rows = []
    for r_joint in (20e-6, 50e-6, 100e-6):
        total = r_bar + CONTACTS_PER_PATH * r_joint
        rows.append({
            "joint_ohm": r_joint,
            "path_ohm": total,
            "path_w": i_a * i_a * total,
            "efficiency_loss_frac": i_a * i_a * total / 188.3,
        })
    return {"bar_ohm": r_bar, "rows": rows,
            "note": "0.1 mohm is only reachable with roughly 20 uohm joints or fewer of them; "
                    "at 50 uohm each the two joints use the budget up on their own"}


def joint_limit(budget_ohm: float = DESIGN_BASIS_OHM,
                contacts: int = CONTACTS_PER_PATH,
                length_m: float = BUS_LENGTH_M,
                width_m: float = BUS_WIDTH_M,
                thickness_m: float = BUS_THICKNESS_M) -> dict[str, object]:
    """Largest per-joint resistance the design basis still tolerates.

    This is the number the first-article four-wire measurement gets compared
    against; the 50 uohm placeholder is not a criterion, only an assumption.
    """
    r_bar = busbar_resistance(length_m, width_m, thickness_m)
    allowed = budget_ohm - r_bar
    per_joint = allowed / contacts if contacts else 0.0
    return {
        "budget_ohm": budget_ohm,
        "bar_ohm": r_bar,
        "allowed_joint_total_ohm": allowed,
        "per_joint_ohm": per_joint,
        "placeholder_fits": CONTACT_OHM_PLACEHOLDER <= per_joint,
        "status": "first article must measure every joint at or below per_joint_ohm",
    }


def input_connector(i_rms_a: float = INPUT_CURRENT_RMS_A,
                    i_pk_a: float = INPUT_CURRENT_PEAK_A,
                    thickness_mm: float = 0.07,
                    target_w_per_100mm: float = 0.1) -> dict[str, object]:
    """The 48 V side is not free either: 6.75 A RMS through a narrow trace adds up.

    The width needed for a target dissipation is solved rather than guessed,
    because 2 mm of 2 oz copper turns out to lose 0.56 W per 100 mm.
    """
    thickness_m = thickness_mm * 1e-3
    area_for_target = copper_rho(T_REF_C) * 0.1 * i_rms_a * i_rms_a / target_w_per_100mm
    width_mm_needed = area_for_target / thickness_m * 1e3

    def at(width_mm: float) -> dict[str, float]:
        r = busbar_resistance(0.1, width_mm * 1e-3, thickness_m)
        return {"width_mm": width_mm, "ohm_per_100mm": r,
                "w_per_100mm": i_rms_a * i_rms_a * r}

    return {
        "i_rms_a": i_rms_a,
        "i_peak_a": i_pk_a,
        "target_w_per_100mm": target_w_per_100mm,
        "width_for_target_mm": width_mm_needed,
        "examples": [at(2.0), at(10.0), at(width_mm_needed)],
        "note": "preferred part is a 2-pin 5.08 mm or larger screw terminal; "
                "the trace width, not the terminal rating, sets this side",
    }


def report() -> dict[str, object]:
    return {
        "status": "geometry sized; contact resistance NOT verified; no MPN assigned",
        "output": output_path(),
        "output_feasibility": feasibility(),
        "joint_limit": joint_limit(),
        "input": input_connector(),
        "budget_origin": "Both PATH_BUDGET_OHM (0.1 mohm, strict) and DESIGN_BASIS_OHM "
                         "(0.15 mohm) are self-chosen. The project has no output-drop "
                         "specification; 0.15 is the number the published 92.33 % efficiency "
                         "already contains, so it is the design basis and sets the joint limit.",
        "caveats": [
            "h_conv is a handbook range (4-8 W/m2K), so every rise is a range, not a value",
            "the bar is assumed isothermal; at 80 mm the axial gradient is small but not zero",
            "no radiation term and no forced air; both would lower the rise",
            "contact resistance is a placeholder; at 100 A a 50 uohm joint is 0.5 W on its own",
            "solder-joint and PCB-spreading resistance are not in this model at all",
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path, default=Path("design/v3/bom/connector_budget.json"))
    args = ap.parse_args()

    data = report()
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    out, bar, c = data["output"], data["output"]["bar"], data["output"]["contact"]
    print(f"output {out['current_a']:.0f} A, budget {out['budget_ohm'] * 1e3:.2f} mohm = {out['budget_w']:.2f} W")
    print(f"  bar {bar['width_mm']:.0f}x{bar['thickness_mm']:.0f} mm x {bar['length_mm']:.0f} mm: "
          f"{bar['resistance_ohm'] * 1e3:.3f} mohm, {bar['power_w']:.3f} W, "
          f"rise {bar['rise_range_k']['h=4']:.1f}-{bar['rise_range_k']['h=8']:.1f} K")
    if bar["max_length_for_budget_mm"] is None:
        print(f"  NO bar length fits: joints alone exceed the budget by "
              f"{out['joint_shortfall_ohm'] * 1e6:.0f} uohm")
    else:
        print(f"  max bar length inside budget: {bar['max_length_for_budget_mm']:.0f} mm")
    print(f"  contacts: {c['contacts']} x {c['contact_ohm_each'] * 1e6:.0f} uohm placeholder "
          f"= {100 * c['frac_of_budget']:.0f}% of budget  [{c['status']}]")
    print(f"  total (placeholder): {out['total_ohm_placeholder'] * 1e3:.3f} mohm, "
          f"{out['total_power_w_placeholder']:.2f} W")
    for row in data["output_feasibility"]["rows"]:
        print(f"  joint {row['joint_ohm'] * 1e6:3.0f} uohm -> path {row['path_ohm'] * 1e3:.3f} mohm, "
              f"{row['path_w']:.2f} W, {100 * row['efficiency_loss_frac']:.2f}% of Pout")
    lim = data["joint_limit"]
    print(f"design basis {lim['budget_ohm'] * 1e3:.2f} mohm (the efficiency estimate's number): "
          f"bar {lim['bar_ohm'] * 1e6:.1f} uohm leaves "
          f"{lim['per_joint_ohm'] * 1e6:.1f} uohm per joint"
          f"{'' if lim['placeholder_fits'] else '  -- placeholder does NOT fit'}")
    inp = data["input"]
    print(f"input {inp['i_rms_a']:.2f} A RMS: {inp['width_for_target_mm']:.1f} mm of 2 oz copper "
          f"for {inp['target_w_per_100mm'] * 1e3:.0f} mW/100 mm "
          f"(2 mm gives {inp['examples'][0]['w_per_100mm']:.2f} W/100 mm)")
    print(args.json)


if __name__ == "__main__":
    main()

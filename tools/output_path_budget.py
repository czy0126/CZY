"""On-board 100 A output path: squares, not guesswork (Issue #12 item 4).

`connector_budget.py` sizes the busbar and the bolted joints *off* the board.
This tool covers the part between the SR drains and the busbar -- the plane --
which none of the existing tools looked at, and which the placement study makes
awkward: the four SR groups sit at x = 14..145 mm while the 80 mm busbar covers
x = 60..140 mm.  Group 1 has no busbar above it at all.

The model is sheet resistance:

    R = rho(T) * (L / W) / t          = R_sheet * squares

which is exact for uniform current in an ideal rectangle; a branching 2D
board has no rigorous upper bound from this square-count approximation.
Crucially, each SR group carries about 25 A, not 100 A through the worst
branch. Four-group power must sum the four I_branch**2 * R_branch terms.  It is **not** a substitute for a
finite-element solve, and it says nothing about local hot spots -- a 2 oz plane
carrying 25 A through a 15 mm channel is a strip, and the strip runs hot.

Usage:
    python tools/output_path_budget.py --json design/v3/pcb/output_path_budget.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import main_board_mechanical as mbm  # noqa: E402

COPPER_RHO_20 = 1.724e-8      # ohm*m, annealed copper
ALPHA_CU = 0.00393            # 1/K
OZ_M = 35e-6                  # 1 oz copper plating = 35 um
T_C = 100.0                   # design basis; the heat path is not modelled here

GROUP_CURRENT_A = 25.0        # 100 A / 4 groups, symmetric by construction
DESIGN_BASIS_OHM = 0.15e-3    # same basis the published 92.33 % efficiency uses
STRICT_TARGET_OHM = 0.10e-3   # self-chosen, stricter; `connector_budget.json`
EXPLORATORY_BUDGET_OHM = 0.30e-3  # loss-for-power study only, NOT a released rating

# How far the plane has to reach sideways when a group has no busbar above it.
# The channel is bounded by the J_OUT row on top and the board edge below.
NECK_DEPTH_MM = 15.0


def sheet_ohm_square(thickness_m: float, temp_c: float = T_C) -> float:
    """Resistance of one square of copper foil.  ``rho/t``, nothing else."""
    if thickness_m <= 0:
        raise ValueError("copper thickness must be positive")
    return COPPER_RHO_20 * (1.0 + ALPHA_CU * (temp_c - 20.0)) / thickness_m


def _geometry() -> dict:
    report = mbm.report()
    parts = {p["ref"]: p for p in report["parts"]}
    groups = []
    for i in (1, 2, 3, 4):
        members = [parts[f"SR{i}A"], parts[f"SR{i}B"]]
        groups.append({
            "group": i,
            "x_mm": sum(p["x_mm"] for p in members) / 2.0,
            "y_mm": members[0]["y_mm"],
            "refs": [p["ref"] for p in members],
        })
    return {"groups": groups, "parts": parts, "report": report}


def _neck_mm(x_mm: float, bar: dict) -> float:
    """Horizontal distance from a group's centre to the nearest busbar edge."""
    lo = bar["x_mm"] - bar["w_mm"] / 2.0
    hi = bar["x_mm"] + bar["w_mm"] / 2.0
    if lo <= x_mm <= hi:
        return 0.0
    return min(abs(x_mm - lo), abs(x_mm - hi))


def per_group(geom: dict, thickness_m: float, temp_c: float = T_C,
              bar: dict | None = None) -> list[dict]:
    """Squares, resistance and drop for each SR group on its own."""
    bar = geom["parts"]["J_OUT"] if bar is None else bar
    r_sq = sheet_ohm_square(thickness_m, temp_c)
    rows = []
    for g in geom["groups"]:
        vertical_mm = bar["y_mm"] - g["y_mm"]
        # Each group owns a lane bounded by its neighbours' midpoints; the lane
        # is the widest the plane can be without taking another group's current.
        lane_mm = (geom["report"]["board"]["width_mm"] - 2 * 5.0) / 4.0
        neck_mm = _neck_mm(g["x_mm"], bar)
        vertical_sq = vertical_mm / lane_mm
        neck_sq = neck_mm / NECK_DEPTH_MM if neck_mm > 0 else 0.0
        squares = vertical_sq + neck_sq
        r_ohm = r_sq * squares
        rows.append({
            "group": g["group"], "refs": g["refs"],
            "x_mm": round(g["x_mm"], 2),
            "vertical_run_mm": round(vertical_mm, 2),
            "lane_width_mm": round(lane_mm, 2),
            "horizontal_neck_mm": round(neck_mm, 2),
            "vertical_squares": round(vertical_sq, 3),
            "neck_squares": round(neck_sq, 3),
            "squares": round(squares, 3),
            "r_mohm": round(r_ohm * 1e3, 3),
            "drop_mv": round(GROUP_CURRENT_A * r_ohm * 1e3, 2),
            "p_w": round(GROUP_CURRENT_A ** 2 * r_ohm, 3),
        })
    return rows


def _versus_the_model(worst: dict, total_r: float) -> dict:
    """Compare against the output resistance the whole design is built on.

    `magnetics_design.json:r_out_equiv_ohm` is the measured output-referred
    resistance of the converter -- the number that sets the load line and that
    the published efficiency rests on.  It was measured at an **ideal output
    node**, with no PCB copper in it.  If a single group's plane path is larger
    than that whole figure, the model and the layout describe different
    converters, and saying so is more useful than any error bar.
    """
    data = mbm._load("magnetics/magnetics_design.json")
    r_model = float(data["r_out_equiv_ohm"])
    vout = float(data["output_100a"]["48v"]["vout_v"])
    pout = float(data["output_100a"]["48v"]["pout_w"])
    extra = 100.0 ** 2 * (total_r - DESIGN_BASIS_OHM)
    return {
        "r_out_equiv_mohm": round(r_model * 1e3, 3),
        "worst_group_path_mohm": worst["r_mohm"],
        "worst_group_over_model": round(worst["r_mohm"] * 1e-3 / r_model, 2),
        "extra_loss_vs_0p15_mohm_w": round(extra, 2),
        "pout_at_48v_w": round(pout, 1),
        "efficiency_points_lost": round(100.0 * extra / pout, 2),
        "vout_at_48v_v": round(vout, 3),
        "note": "r_out_equiv 是整机输出折算阻抗，单组平面 R 是局部支路量；"
                "两者不能直接相加。该比值只提示布局与均流风险。",
    }


def budget(thickness_m: float = 2 * OZ_M, temp_c: float = T_C) -> dict:
    """Whole output path: plane + busbar + joints, against both targets."""
    geom = _geometry()
    rows = per_group(geom, thickness_m, temp_c)
    worst = max(rows, key=lambda r: r["r_mohm"])
    # Equal 25 A branches: P_plane = sum((25 A)**2 * R_g).
    # Equivalent at the 100 A system port is R_eq = sum(R_g) / 16.
    # Using the worst group's R as 100 A series R was a major overestimate.
    plane_r = sum(row["r_mohm"] for row in rows) * 1e-3 / 16.0
    r_sq = sheet_ohm_square(thickness_m, temp_c)

    import connector_budget as cb
    bar = cb.busbar_resistance(cb.BUS_LENGTH_M, cb.BUS_WIDTH_M, cb.BUS_THICKNESS_M, temp_c)
    joints = cb.CONTACTS_PER_PATH * cb.CONTACT_OHM_PLACEHOLDER
    total_r = plane_r + bar + joints

    return {
        "copper_weight_oz": round(thickness_m / OZ_M, 2),
        "copper_thickness_um": round(thickness_m * 1e6, 1),
        "temperature_c": temp_c,
        "sheet_mohm_per_square": round(r_sq * 1e3, 4),
        "budget_in_squares": round(DESIGN_BASIS_OHM / r_sq, 3),
        "group_current_a": GROUP_CURRENT_A,
        "groups": rows,
        "worst_group": {"group": worst["group"], "squares": worst["squares"],
                        "r_mohm": worst["r_mohm"]},
        "resistance": {
            "plane_mohm": round(plane_r * 1e3, 3),
            "busbar_mohm": round(bar * 1e3, 3),
            "joints_mohm": round(joints * 1e3, 3),
            "joints_are": "UNVERIFIED placeholder from connector_budget.py",
            "total_mohm": round(total_r * 1e3, 3),
        },
        "loss_w_at_100a": {
            "plane": round(100.0 ** 2 * plane_r, 3),
            "busbar": round(100.0 ** 2 * bar, 3),
            "joints": round(100.0 ** 2 * joints, 3),
            "total": round(100.0 ** 2 * total_r, 3),
        },
        "targets": {
            "design_basis_mohm": round(DESIGN_BASIS_OHM * 1e3, 3),
            "strict_target_mohm": round(STRICT_TARGET_OHM * 1e3, 3),
            "exploratory_mohm": round(EXPLORATORY_BUDGET_OHM * 1e3, 3),
        },
        "feasible_on_design_basis": total_r <= DESIGN_BASIS_OHM,
        "feasible_on_strict_target": total_r <= STRICT_TARGET_OHM,
        "within_exploratory_budget": total_r <= EXPLORATORY_BUDGET_OHM,
        "exploratory_budget_is_not_rating": True,
        "dominant_term": max(
            (("plane", plane_r), ("busbar", bar), ("joints", joints)),
            key=lambda kv: kv[1])[0],
        "versus_the_model": _versus_the_model(worst, total_r),
        "model": {
            "method": "R = R_sheet * squares; uniform current in each segment",
            "direction": "equal-current lane approximation; not a rigorous geometric upper bound",
            "not_modelled": [
                "finite-element spreading at the neck (could raise or lower effective R)",
                "local hot spots and the strip's own self-heating",
                "via resistance between layers (no via field is placed yet)",
                "the Cout bank's parallel path (modelled only as the lane width)",
                "actual four-way current sharing; exactly 25 A per branch is assumed",
            ],
        },
        "remedy": remedy(thickness_m, temp_c),
        "finding": None,   # filled by main(); kept here so the shape is stable
    }


def remedy(thickness_m: float, temp_c: float = T_C) -> dict:
    """What it would take to close the gap -- the actionable half of the report.

    Each option is evaluated with the same square-count model, so the comparison
    is apples to apples.  The question the numbers answer is which lever is
    worth pulling: copper weight, or where the busbar sits.
    """
    geom = _geometry()
    bar = geom["parts"]["J_OUT"]
    lo = bar["x_mm"] - bar["w_mm"] / 2.0
    hi = bar["x_mm"] + bar["w_mm"] / 2.0
    xs = [g["x_mm"] for g in geom["groups"]]
    outside = [g["group"] for g in geom["groups"] if not lo <= g["x_mm"] <= hi]
    span_mm = max(xs) - min(xs)
    # 20 mm of busbar either side of the outermost group centre clears its pads.
    wide_mm = span_mm + 20.0
    wide_bar = dict(bar, x_mm=(min(xs) + max(xs)) / 2.0, w_mm=wide_mm)

    def worst_for(thick_m: float, b: dict | None) -> float:
        return max(r["r_mohm"] for r in per_group(geom, thick_m, temp_c, b))

    import connector_budget as cb
    fixed = (cb.busbar_resistance(cb.BUS_LENGTH_M, cb.BUS_WIDTH_M, cb.BUS_THICKNESS_M, temp_c)
             + cb.CONTACTS_PER_PATH * cb.CONTACT_OHM_PLACEHOLDER)
    options = []
    for oz in (2, 4):
        for name, b in (("现状（80 mm，居中于板）", None),
                        (f"加宽到 {wide_mm:.0f} mm 覆盖四组", wide_bar)):
            rows = per_group(geom, oz * OZ_M, temp_c, b)
            worst = max(r["r_mohm"] for r in rows) * 1e-3
            plane_eq = sum(r["r_mohm"] for r in rows) * 1e-3 / 16.0
            options.append({
                "copper_oz": oz, "busbar": name,
                "worst_group_mohm": round(worst * 1e3, 3),
                "spread_ratio": round(
                    max(r["r_mohm"] for r in rows) / min(r["r_mohm"] for r in rows), 2),
                "path_total_mohm": round((plane_eq + fixed) * 1e3, 3),
                "feasible_on_design_basis": plane_eq + fixed <= DESIGN_BASIS_OHM,
            })
    return {
        "groups_outside_the_busbar": outside,
        "busbar_span_mm": [round(lo, 1), round(hi, 1)],
        "sr_row_span_mm": [round(min(xs), 1), round(max(xs), 1)],
        "busbar_widening_needed_mm": round(wide_mm - bar["w_mm"], 1),
        "options": options,
        "note": "path_total = ΣR_group/16 + R_bar + R_joint，假设每组等分 25 A。"
                "加宽铜排有利于减小路径不均衡；接点仍按未经实测的 2×50 µΩ。"
                "这不是几何不可能性证明：均流与电阻需 PCB 提取和实测。",
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--json", type=Path, default=Path("design/v3/pcb/output_path_budget.json"))
    p.add_argument("--oz", type=float, default=2.0, help="copper weight per layer")
    args = p.parse_args()

    data = budget(args.oz * OZ_M)
    worst = data["worst_group"]
    outside = data["remedy"]["groups_outside_the_busbar"]
    data["finding"] = (
        f"最差组局部路径 {worst['squares']:.2f} 方块；"
        f"四组等分 100 A 的平面等效 {data['resistance']['plane_mohm']:.3f} mΩ，"
        f"第 {', '.join(map(str, outside))} 组铜排不在正上方，需改善均流路径。")

    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8", newline="\n")
    print(f"{data['copper_weight_oz']:g} oz, sheet {data['sheet_mohm_per_square']:.4f} mohm/sq, "
          f"budget {data['budget_in_squares']:.2f} squares")
    for row in data["groups"]:
        print(f"  group {row['group']}: {row['squares']:5.2f} sq "
              f"({row['vertical_squares']:.2f} down + {row['neck_squares']:.2f} across), "
              f"R {row['r_mohm']:.3f} mohm, drop {row['drop_mv']:.1f} mV")
    r = data["resistance"]
    print(f"total {r['total_mohm']:.3f} mohm (plane {r['plane_mohm']:.3f}, "
          f"busbar {r['busbar_mohm']:.3f}, joints {r['joints_mohm']:.3f}) "
          f"= {data['loss_w_at_100a']['total']:.2f} W at 100 A")
    print(f"design basis {data['targets']['design_basis_mohm']:.2f} mohm: "
          f"{'PASS' if data['feasible_on_design_basis'] else 'FAIL'}")
    print(data["finding"])


if __name__ == "__main__":
    main()

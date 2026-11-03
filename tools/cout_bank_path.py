"""The copper the Cout bank sits on -- the term `part ESR / N` leaves out.

`cout_bank.json` sizes the bank from `part ESR / N` and then says, in its own
caveat, that this assumes zero interconnect resistance and that at N >= 15 the
copper spreading resistance is not negligible.  SOURCE-04 asks for the same
term from the other side: "include spreading copper/joints".

The physics is one line.  Each capacitor is in series with the copper that
carries *its* share, so the copper enters before the parallel combination:

    R_bank = 1 / sum(1 / (ESR_part + R_branch_i))

With every R_branch zero that collapses to `ESR_part / N`, which is what the
sizing published -- so the two tools describe the same bank.  The branch
resistance itself uses the square count `output_path_budget.py` already uses:

    R_branch = R_sheet * (vertical_mm + lateral_mm) / lane_mm

The result is a **lower bound**: the square count is a DC model, and at 200 kHz
the current crowds into the copper beside each pad instead of using the whole
lane.  Nothing here is a thermal model either -- the current share that comes
out is a resistance ratio, and SOURCE-04's thermal-imbalance clause stays open.

Usage:
    python tools/cout_bank_path.py --json design/v3/bom/cout_bank_path.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import connector_budget as cb  # noqa: E402
import main_board_mechanical as mbm  # noqa: E402
import output_path_budget as opb  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BANK_JSON = ROOT / "design/v3/bom/cout_bank.json"

# Same placeholder the bolted-joint term carries.  There is no capacitor-joint
# measurement in this repository, and inventing a nicer-looking number would
# make it indistinguishable from data.
JOINT_OHM = cb.CONTACT_OHM_PLACEHOLDER
JOINT_NOTE = "UNVERIFIED placeholder from connector_budget.py"

# Percentage rises at which the branch allowance is quoted.
RISES = (0.10, 0.25, 0.50)

LIMITS = [
    "the square count is a lower bound on AC resistance: at 200 kHz the current "
    "crowds into the copper beside each pad, and neither skin nor proximity effect "
    "is modelled",
    "per-unit pad, via and solder-joint geometry does not exist in this repository; "
    "the 50 uohm joint is the connector placeholder, not a capacitor-joint measurement",
    "each unit is assigned to the nearest SR-group centre; a real plane splits its "
    "current between two groups",
    "the vertical run is copper shared with the SR-to-busbar path in "
    "output_path_budget.json; the two resistances are not additive",
    "part ESR is a vendor-page summary; ESR at 200 kHz, at 2 V bias and at end of "
    "life is not included",
    "no thermal model: the current share below is a resistance ratio, not a temperature",
    "the 42.76 mVpp output ripple on file (operating_point_100a_cout7m.json, 7.05 mF) "
    "was computed with the ideal 0.200 mohm bank Rser; raising a branch impedance cannot "
    "lower the ripple, so that figure is a lower bound as well",
]

DIRECTION = ("a lower bound on the interconnect term; AC crowding and the shared "
             "return path both only raise it")


def part_esr_ohm(bank: dict) -> float:
    """Single-part ESR implied by the published bank value: ``bank ESR x N``."""
    return float(bank["bank_esr_ohm"]) * int(bank["n"])


def parallel_esr(part_esr: float, branch_ohm: Sequence[float]) -> float:
    """Bank ESR with each part's own copper in series with that part.

    ``1 / sum(1 / (ESR_part + R_branch))``.  Every branch zero gives
    ``ESR_part / N``, which is what ``cout_bank.json`` published.
    """
    if part_esr <= 0:
        raise ValueError("part ESR must be positive")
    if not branch_ohm:
        raise ValueError("a bank needs at least one branch")
    return 1.0 / sum(1.0 / (part_esr + b) for b in branch_ohm)


def units(report: dict) -> list[dict]:
    """The Cout units in x order, straight from the placement study."""
    placed = [p for p in report["parts"]
              if p["ref"].startswith("C1") and p["ref"][1:].isdigit()
              and int(p["ref"][1:]) >= 100]
    return sorted(placed, key=lambda p: float(p["x_mm"]))


def unit_pitch_mm(placed: Sequence[dict]) -> float:
    """Mean centre-to-centre spacing -- the widest lane one unit may own."""
    xs = [float(p["x_mm"]) for p in placed]
    if len(xs) < 2:
        raise ValueError("a bank row needs at least two units to have a pitch")
    return sum(b - a for a, b in zip(xs, xs[1:])) / (len(xs) - 1)


def nearest_group(x_mm: float, groups: Sequence[dict]) -> dict:
    """The SR group whose secondary loop this unit serves."""
    return min(groups, key=lambda g: abs(x_mm - float(g["x_mm"])))


def branches(placed: Sequence[dict], groups: Sequence[dict], lane_mm: float,
             r_sheet_ohm: float, joint_ohm: float = JOINT_OHM) -> list[dict]:
    """Square count, plane resistance and joint for every unit's own branch."""
    rows = []
    for p in placed:
        x = float(p["x_mm"])
        group = nearest_group(x, groups)
        vertical = abs(float(p["y_mm"]) - float(group["y_mm"]))
        lateral = abs(x - float(group["x_mm"]))
        squares = (vertical + lateral) / lane_mm
        r_plane = r_sheet_ohm * squares
        rows.append({
            "ref": p["ref"],
            "x_mm": round(x, 2),
            "group": int(group["group"]),
            "lateral_mm": round(lateral, 2),
            "vertical_mm": round(vertical, 2),
            "vertical_squares": round(vertical / lane_mm, 3),
            "lateral_squares": round(lateral / lane_mm, 3),
            "squares": round(squares, 3),
            "r_plane_mohm": round(r_plane * 1e3, 4),
            "r_branch_ohm": r_plane + joint_ohm,
            "r_branch_mohm": round((r_plane + joint_ohm) * 1e3, 4),
        })
    return rows


def allowance(part_esr: float, n: int, rise: float) -> float:
    """Largest *equal* branch resistance that keeps the bank within ``rise``.

    ``(ESR + R) / N = (ESR / N) * (1 + rise)`` solved for R.  It grows linearly
    with N, which is why a larger bank tolerates more copper per branch.
    """
    return (part_esr / n) * (1.0 + rise) * n - part_esr


def bank_esr_with_copper(bank: dict, thickness_m: float = 2 * opb.OZ_M,
                         temp_c: float = opb.T_C, joint_ohm: float = JOINT_OHM,
                         placement: dict | None = None) -> dict:
    """What the bank's ESR becomes once the placed copper is in series."""
    report = mbm.report() if placement is None else placement
    placed = units(report)
    groups = opb._geometry()["groups"]
    lane = unit_pitch_mm(placed)
    r_sheet = opb.sheet_ohm_square(thickness_m, temp_c)
    rows = branches(placed, groups, lane, r_sheet, joint_ohm)

    esr = part_esr_ohm(bank)
    n = int(bank["n"])
    parts_only = esr / n
    bank_esr = parallel_esr(esr, [r["r_branch_ohm"] for r in rows])

    conductances = [1.0 / (esr + r["r_branch_ohm"]) for r in rows]
    total_g = sum(conductances)
    shares = [{"ref": r["ref"], "share_pct": round(100.0 * g / total_g, 4)}
              for r, g in zip(rows, conductances)]
    nominal = 100.0 / len(rows)
    highest = max(s["share_pct"] for s in shares)
    lowest = min(s["share_pct"] for s in shares)
    worst = max(rows, key=lambda r: r["r_branch_ohm"])
    least = min(rows, key=lambda r: r["r_branch_ohm"])

    return {
        "part_esr_mohm": round(esr * 1e3, 4),
        "n": n,
        "parts_only_esr_mohm": round(parts_only * 1e3, 4),
        "bank_esr_mohm": round(bank_esr * 1e3, 4),
        "rise_mohm": round((bank_esr - parts_only) * 1e3, 4),
        "rise_frac": round(bank_esr / parts_only - 1.0, 5),
        "lane_width_mm": round(lane, 3),
        "vertical_run_mm": round(float(rows[0]["vertical_mm"]), 2),
        "sheet_mohm_per_square": round(r_sheet * 1e3, 4),
        "copper_thickness_um": round(thickness_m * 1e6, 1),
        "temperature_c": temp_c,
        "joint_ohm": joint_ohm,
        "joints_are": JOINT_NOTE,
        "units": rows,
        "worst_branch_mohm": round(worst["r_branch_ohm"] * 1e3, 4),
        "worst_branch_ref": worst["ref"],
        "least_branch_mohm": round(least["r_branch_ohm"] * 1e3, 4),
        "branch_spread_ratio": round(worst["r_branch_ohm"] / least["r_branch_ohm"], 3),
        "current_share": {
            "nominal_pct": round(nominal, 4),
            "highest_pct": highest,
            "lowest_pct": lowest,
            "highest_over_nominal": round(highest / nominal, 4),
            "per_unit": shares,
        },
        "direction": DIRECTION,
        "limits": LIMITS,
    }


def allowance_rows(part_esr: float, n: int, lane_mm: float,
                   r_sheet_ohm: float) -> list[dict]:
    """The allowance table, in ohms, squares and millimetres of travel."""
    rows = []
    for rise in RISES:
        r = allowance(part_esr, n, rise)
        squares = r / r_sheet_ohm
        rows.append({
            "rise_frac": rise,
            "bank_esr_mohm": round(part_esr / n * (1.0 + rise) * 1e3, 4),
            "max_branch_mohm": round(r * 1e3, 4),
            "squares": round(squares, 3),
            "lateral_mm": round(squares * lane_mm, 1),
        })
    return rows


def candidates(banks: Sequence[dict], lane_mm: float, r_sheet_ohm: float) -> list[dict]:
    """Every bank the sizing considered, against the same allowance.

    Only the first is placed, so the lane width is borrowed from the placed row;
    a wider row would lower each branch, i.e. these allowances are pessimistic.
    """
    out = []
    for i, bank in enumerate(banks):
        esr = part_esr_ohm(bank)
        n = int(bank["n"])
        out.append({
            "part": bank["part"],
            "n": n,
            "part_esr_mohm": round(esr * 1e3, 4),
            "placed": i == 0,
            "allowance": allowance_rows(esr, n, lane_mm, r_sheet_ohm),
        })
    return out


def report(thickness_m: float = 2 * opb.OZ_M, temp_c: float = opb.T_C) -> dict:
    """The whole record: placed-bank result, allowance table, provenance checks."""
    banks = json.loads(BANK_JSON.read_text(encoding="utf-8"))["banks"]
    bank = banks[0]
    core = bank_esr_with_copper(bank, thickness_m, temp_c)
    r_sheet = opb.sheet_ohm_square(thickness_m, temp_c)
    lane = core["lane_width_mm"]
    placed = units(mbm.report())
    esr = part_esr_ohm(bank)
    n = int(bank["n"])

    core["allowance"] = allowance_rows(esr, n, lane, r_sheet)
    core["candidates"] = candidates(banks, lane, r_sheet)
    worst_versus_ten = core["worst_branch_mohm"] * 1e-3 / allowance(esr, n, 0.10)
    core["worst_branch_over_ten_percent_allowance"] = round(worst_versus_ten, 2)
    return {
        "status": "geometry + sheet resistance; part data still search-sourced",
        "placed_bank": {"part": bank["part"], "n": n, "governed_by": bank["governed_by"]},
        "results": core,
        "model": {
            "method": "R_branch = R_sheet * (vertical + lateral) / lane; "
                      "R_bank = 1 / sum(1 / (ESR_part + R_branch))",
            "direction": DIRECTION,
            "not_modelled": LIMITS,
        },
        "checks": {
            "the_placed_unit_count_is_the_bank_count": len(placed) == n,
            "the_parts_only_esr_reproduces_the_published_bank_esr": (
                abs(esr / n - float(bank["bank_esr_ohm"])) <= 1e-15),
            "the_bank_row_is_a_straight_line": len({p["y_mm"] for p in placed}) == 1,
            "every_unit_sits_in_the_placement_study": all(p.get("evidence") for p in placed),
        },
        "finding": (
            f"并联件 ESR {core['parts_only_esr_mohm']:.3f} mΩ（零件 {core['part_esr_mohm']:.3f} mΩ / {n} 只）；"
            f"按摆放的平面铜阻再加 {core['rise_mohm'] * 1e3:.1f} μΩ，得 {core['bank_esr_mohm']:.3f} mΩ"
            f"（+{core['rise_frac']:.1%}）。最差支路 {core['worst_branch_mohm']:.3f} mΩ 是 +10 % 允许量 "
            f"{allowance(esr, n, 0.10) * 1e3:.3f} mΩ 的 {worst_versus_ten:.1f} 倍，"
            f"该单元分到 {core['current_share']['highest_pct']:.2f} % vs 标称 "
            f"{core['current_share']['nominal_pct']:.2f} %。"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", type=Path, default=Path("design/v3/bom/cout_bank_path.json"))
    ap.add_argument("--oz", type=float, default=2.0, help="copper weight per layer")
    ap.add_argument("--temp-c", type=float, default=opb.T_C)
    args = ap.parse_args()

    data = report(args.oz * opb.OZ_M, args.temp_c)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8", newline="\n")

    r = data["results"]
    print(f"placed bank {data['placed_bank']['part']}: N={r['n']}, "
          f"lane {r['lane_width_mm']:.2f} mm, {r['sheet_mohm_per_square']:.4f} mΩ/sq")
    print(f"  parts only      {r['parts_only_esr_mohm']:.4f} mΩ")
    print(f"  with copper     {r['bank_esr_mohm']:.4f} mΩ  "
          f"(+{r['rise_mohm'] * 1e3:.1f} μΩ, +{r['rise_frac']:.1%})")
    print(f"  worst branch    {r['worst_branch_mohm']:.3f} mΩ ({r['worst_branch_ref']}), "
          f"spread {r['branch_spread_ratio']:.2f}x, "
          f"{r['worst_branch_over_ten_percent_allowance']:.1f}x the 10 % allowance")
    for row in r["allowance"]:
        print(f"  +{row['rise_frac']:.0%}: branch <= {row['max_branch_mohm']:.3f} mΩ "
              f"= {row['squares']:.2f} sq = {row['lateral_mm']:.1f} mm of travel")
    print(data["finding"])
    return 0 if all(data["checks"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

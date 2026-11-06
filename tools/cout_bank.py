"""How many output capacitors, and which requirement decides the count.

Three independent requirements, each taken at the worst measured load:

    capacitance  >= 4 mF      the value the model runs with
    bank ESR     <= 0.2 mohm  the value the model runs with (Rser=0.2m)
    RMS current  >= 56.06 A   the largest measured I(Cout) ripple

The RMS figure is the *largest* of the measured operating points, not the rated
one: 52.48 A at 48 V/100 A, 55.58 A at the 48 V/120 A overload and 56.06 A at the
50 V/120 A overload.  All three are published so none can be quoted as another.

The points are not on equal footing.  The two overload decks save ``I(Cout)`` and
the bank is one lumped element, so that trace is the whole bank current.  The
100 A deck does not save it, so its figure is rebuilt from the four SR currents
with pairs 2/3 assumed symmetric -- a reconstruction that reads about 1.2 % high.
Every point therefore names its method, and the record publishes both numbers
wherever both exist, so the max() is a documented comparison rather than an
assumption that three numbers mean the same thing.

They do not scale together, so the bank size is set by whichever needs the most
parts.  Part data below is a *candidate*, not a selection: the numbers were
taken from a vendor page summary and no datasheet was read, so every row must be
confirmed before it enters a purchase order.

Usage:
    python tools/cout_bank.py --json design/v3/bom/cout_bank.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO = Path(__file__).resolve().parent.parent
PASSIVE = REPO / "design/v3/bom/passive_requirements.json"
STRESS_48V_120A = REPO / "design/v3/power_priority/stress_48v_120a.json"
STRESS_50V_120A = REPO / "design/v3/power_priority/stress_50v_120a.json"

CAPACITANCE_F = 4.0e-3
ESR_OHM = 0.2e-3
# A reconstruction that disagrees with `average(Vout)/RL` by more than this is not
# a ripple measurement: the four SR currents would be the wrong channels or the
# factor of two for the unprobed pairs would be wrong.
MEAN_CHECK_LIMIT_PCT = 0.5
# The three points are not all measured the same way, so the max() mixes methods.
# The reconstruction reads high and the rated point is the one on it, which makes
# the ordering conservative -- but only while the gap it sorts is at least this
# many times the bias it could hide.  Below that, the winner is not established
# by the data and the check goes false rather than picking one.
METHOD_OFFSET_SAFETY = 5.0

# Candidate parts (network search summary, NOT datasheet-verified).
CANDIDATES = [
    {"mpn": "KEMET A720V477M2R5APE003", "c_f": 470e-6, "v_rated": 2.5, "esr_ohm": 3e-3,
     "irms_a": 11.69, "case": "2917 (7.3 x 4.3 mm)", "height_mm": 2.1},
    {"mpn": "KEMET A798D477M2R5PTE006", "c_f": 470e-6, "v_rated": 2.5, "esr_ohm": 6e-3,
     "irms_a": 6.46, "case": "SMD", "height_mm": 3.1},
    {"mpn": "Chemi-Con APSF2R5ELL471MF08S", "c_f": 470e-6, "v_rated": 2.5, "esr_ohm": 5e-3,
     "irms_a": 5.9, "case": "radial 6.3 x 8 mm", "height_mm": 8.0},
]


def _sizing_point(path: Path) -> dict[str, object]:
    """One measured capacitor-current point, read from the artifact that holds it.

    The three artifacts have different schemas at the top level but all the
    fields needed here live under ``cout_ripple`` and beside a ``raw``/``window_us``
    pair, so one reader serves the rated and both overload runs.

    ``method`` is the producer's own label for how the ripple was obtained.  When
    the deck saved ``I(Cout)`` the producer also publishes what the four-SR
    reconstruction would have said; carrying that gap into the point is what lets
    a reader see the price of comparing across methods.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    ripple = data["cout_ripple"]
    source = path.relative_to(REPO).as_posix() if path.is_relative_to(REPO) else path.as_posix()
    point: dict[str, object] = {
        "source": source,
        "raw": data["raw"],
        "window_us": list(data["window_us"]),
        "load_mean_a": ripple["load_mean_a"],
        "ripple_rms_a": ripple["ripple_rms_a"],
        "ripple_pk_a": ripple["ripple_pk_a"],
        "mean_check_pct": ripple["mean_check_pct"],
        "method": ripple.get("reconstruction"),
    }
    reconstructed = ripple.get("ripple_rms_reconstructed_a")
    if reconstructed is not None:
        point["ripple_rms_reconstructed_a"] = reconstructed
        point["method_offset_frac"] = reconstructed / ripple["ripple_rms_a"] - 1.0
    return point


SIZING_POINTS = {
    "rated_100a": _sizing_point(PASSIVE),
    "overload_48v_120a": _sizing_point(STRESS_48V_120A),
    "overload_50v_120a": _sizing_point(STRESS_50V_120A),
}


def default_requirements() -> dict[str, object]:
    """Capacitance and ESR from the model, ripple current from the worst run.

    Capacitance and ESR do not depend on the load -- they are the values every
    deck runs with -- so only the current requirement is quoted at a load, and it
    is quoted at the largest one that has actually been measured.
    """
    worst_key = max(SIZING_POINTS, key=lambda key: SIZING_POINTS[key]["ripple_rms_a"])
    worst = SIZING_POINTS[worst_key]
    return {
        "capacitance_f": CAPACITANCE_F,
        "esr_ohm": ESR_OHM,
        "irms_a": worst["ripple_rms_a"],
        "sized_at": worst["source"],
        "sizing_points": SIZING_POINTS,
        "note": "capacitance and ESR are the values the model runs with; RMS is the "
                "largest of the measured loads, taken from I(Cout) where the deck saves "
                "it and from the four-SR reconstruction at the rated point, which does not",
    }


REQUIREMENTS = default_requirements()


def parts_needed(part: dict[str, float], requirements: dict[str, object] = REQUIREMENTS) -> dict[str, object]:
    """Smallest parallel count that meets each requirement, and the one that wins.

    The ceilings are strict on purpose: a ratio that lands a hair above an integer
    buys one extra part, never one fewer.  Do not "fix" that by rounding.
    """
    n_cap = math.ceil(requirements["capacitance_f"] / part["c_f"])
    n_esr = math.ceil(part["esr_ohm"] / requirements["esr_ohm"])
    n_rms = math.ceil(requirements["irms_a"] / part["irms_a"])
    counts = {"capacitance": n_cap, "esr": n_esr, "rms": n_rms}
    n = max(counts.values())
    governing = max(counts, key=lambda k: counts[k])
    return {
        "part": part["mpn"],
        "counts": counts,
        "n": n,
        "governed_by": governing,
        "bank_capacitance_f": n * part["c_f"],
        "bank_esr_ohm": part["esr_ohm"] / n,
        "bank_irms_a": n * part["irms_a"],
        "v_rated": part["v_rated"],
        "height_mm": part["height_mm"],
        "esr_margin_frac": requirements["esr_ohm"] / (part["esr_ohm"] / n),
    }


def report(requirements: dict[str, object] = REQUIREMENTS) -> dict[str, object]:
    banks = [parts_needed(part, requirements) for part in CANDIDATES]
    best = min(banks, key=lambda b: (b["n"], b["height_mm"]))
    points = requirements["sizing_points"]
    irms = requirements["irms_a"]
    rated_irms = points["rated_100a"]["ripple_rms_a"]
    rated_requirements = {**requirements, "irms_a": rated_irms}
    # The measured points also carry what the reconstruction would have said.  The
    # largest of those gaps bounds how much a mixed-method max() could be hiding.
    offsets = [point["method_offset_frac"] for point in points.values()
               if "method_offset_frac" in point]
    method_offset = max(offsets) if offsets else 0.0
    worst_over_rated = irms / rated_irms - 1.0
    overload_methods = {point.get("method") for key, point in points.items() if key != "rated_100a"}

    results_banks = []
    for part, bank in zip(CANDIDATES, banks):
        per_part = irms / bank["n"]
        results_banks.append({
            "part": bank["part"],
            "n": bank["n"],
            "governed_by": bank["governed_by"],
            "counts": bank["counts"],
            "rms_count_at_overload": bank["counts"]["rms"],
            "rms_count_at_rated_load": parts_needed(part, rated_requirements)["counts"]["rms"],
            "per_part_ripple_a": per_part,
            "per_part_ripple_margin": part["irms_a"] / per_part,
        })

    return {
        "status": "sizing only; part data is search-sourced, not datasheet-verified",
        "requirements": {
            "capacitance_f": requirements["capacitance_f"],
            "esr_ohm": requirements["esr_ohm"],
            "irms_a": irms,
            "sized_at": requirements["sized_at"],
            "sizing_points": points,
            "note": requirements["note"],
        },
        "checks": {
            "the_requirement_is_the_worst_measured_load": irms == max(
                point["ripple_rms_a"] for point in points.values()),
            "every_sizing_point_traces_to_a_committed_artifact": all(
                point["raw"] and (REPO / point["source"]).is_file() for point in points.values()),
            "every_reconstruction_agrees_with_vout_over_rl": all(
                abs(point["mean_check_pct"]) <= MEAN_CHECK_LIMIT_PCT for point in points.values()),
            "every_sizing_point_names_its_method": all(
                isinstance(point.get("method"), str) and point["method"] for point in points.values())
                and len(overload_methods) == 1,
            "the_rated_point_loses_by_more_than_the_method_offset":
                worst_over_rated > METHOD_OFFSET_SAFETY * method_offset,
            "every_bank_meets_the_requirements_at_the_worst_load": all(
                bank["bank_capacitance_f"] >= requirements["capacitance_f"] - 1e-15
                and bank["bank_esr_ohm"] <= requirements["esr_ohm"] + 1e-15
                and bank["bank_irms_a"] >= irms for bank in banks),
        },
        "results": {
            "worst_ripple_rms_a": irms,
            "ripple_point_spread_frac": (irms - min(p["ripple_rms_a"] for p in points.values()))
            / min(p["ripple_rms_a"] for p in points.values()),
            # how far the winning point sits above the one on the other method, and
            # how large that other method's bias is -- the two numbers behind the check
            "worst_over_rated_frac": worst_over_rated,
            "method_offset_max_frac": method_offset,
            # what the model's ESR dissipates at the worst load; the 1 W budget is about this
            "esr_loss_w_at_model_esr": irms**2 * requirements["esr_ohm"],
            "banks": results_banks,
            "the_esr_governed_bank_size_changes_at_the_overload": any(
                row["n"] != parts_needed(part, rated_requirements)["n"]
                for part, row in zip(CANDIDATES, results_banks)),
        },
        "banks": banks,
        "fewest_parts": best["part"],
        "no_output_ripple_spec": True,
        "caveats": [
            "bank ESR = part ESR / N assumes zero interconnect resistance; at N>=15 the "
            "copper spreading resistance is not negligible and is not modelled here",
            "0.2 mohm is the value the simulation ran with, not a specified limit; "
            "at 0.1 mohm the count doubles",
            "part data is a vendor page summary; capacitance at 2 V bias, ESR at "
            "temperature and end of life are not included",
            "the rated point ran with the 4 mF model capacitance and both overload points "
            "with the 7.05 mF candidate value; the ripple current is the difference of the "
            "measured SR and load currents, so the capacitance does not enter it, but the "
            "voltage ripple does and is not comparable across the three points",
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path, default=Path("design/v3/bom/cout_bank.json"))
    args = ap.parse_args()
    data = report()
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(args.json)
    print(f"RMS requirement {data['requirements']['irms_a']:.3f} A "
          f"sized at {data['requirements']['sized_at']}")
    for bank in data["banks"]:
        print(f"{bank['part']}: N={bank['n']} ({bank['governed_by']}) "
              f"C={bank['bank_capacitance_f'] * 1e3:.2f} mF  ESR={bank['bank_esr_ohm'] * 1e3:.3f} mOhm  "
              f"RMS={bank['bank_irms_a']:.1f} A  h={bank['height_mm']} mm")


if __name__ == "__main__":
    main()

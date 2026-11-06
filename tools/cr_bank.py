"""The resonant capacitor is a two-sided requirement, not a capacitance floor.

Cout asks "how many parts until the bank is big enough".  Cr cannot be sized that
way.  The tank has to run below resonance (the 48 V -> 1.887 V point needs a gain
of about 1.9), so

    fr = 1 / (2 pi sqrt(L_total * C))

has to stay above the 200.622 kHz clock.  The design point sits only 0.75 % above
it, which is 1.5 % in capacitance: the bank has a ceiling as well as a floor.

The bank is also coupled to the inductor.  The first article trims the external Lr
to `L_total(C) - L_leak`, so a bank that lands away from 620 nF moves the trim.  A
capacitance band therefore maps to an inductance window, and only the window that
has actually been simulated is evidence.

No capacitor datasheet exists in this repository, so nothing here names a part.
Every per-part figure is a *requirement* a part has to meet, not a selection.

Usage:
    python tools/cr_bank.py --json design/v3/bom/cr_bank.json
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from itertools import combinations_with_replacement
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO = Path(__file__).resolve().parent.parent
DECK = REPO / "sim/v3/sr_tank_dual_v33_ss_1ms_100a.cir"
CR_STRESS = REPO / "design/v3/bom/cr_stress.json"
CR_STRESS_OVERLOAD = REPO / "design/v3/power_priority/cr_stress_48v_120a.json"
LR_DESIGN = REPO / "design/v3/bom/lr_design.json"

# E12 capacitance values that film capacitors are actually sold in, in nF.
E12_NF = (47, 68, 82, 100, 120, 150, 180, 220, 270, 330, 390, 470, 560, 680)

# The high end of the Lr trim window: 0.875 uH external is what the lrmin run used,
# and its note says that is the 0.125 uH-leakage end.  0.875 + 0.125 = the 1.0 uH
# design total, which is why that run is evidence for the design point.
LEAKAGE_TRIM_END_H = 0.125e-6

TOLERANCE_GRADES = (0.01, 0.02, 0.05, 0.10)

_SI = {"n": 1e-9, "u": 1e-6, "m": 1e-3, "k": 1e3, "": 1.0}


def _si(text: str) -> float:
    match = re.fullmatch(r"([+-]?[.\d]+)([numk]?)", text.strip())
    if not match:
        raise ValueError(f"not a SPICE value: {text!r}")
    return float(match.group(1)) * _SI[match.group(2)]


def deck_params(path: Path) -> dict[str, float]:
    """The `.param` values the 100 A deck actually runs the tank with."""
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.lstrip().lower().startswith(".param"):
            continue
        pairs = dict(re.findall(r"(\w+)=([.\d]+[numk]?)", line))
        if "CR_TOTAL" in pairs:
            return {name: _si(value) for name, value in pairs.items()}
    raise SystemExit(f"{path}: no .param line carrying CR_TOTAL")


def tuning(tank: dict[str, float], capacitance_f: float,
           tested: dict[str, tuple[float, float]]) -> dict[str, object]:
    """The L*C product, the capacitance band and the frequency the clock allows.

    `tested` is the inductance the tank has actually been run at, in both forms:
    `l_total_h` (external plus leakage) sets the band, `l_external_h` is what the
    first article trims to.  Only values inside those windows are evidence.
    """
    resonant_hz = tank["resonant_khz"] * 1e3
    clock_hz = tank["clock_khz"] * 1e3
    lc_product = 1.0 / (2.0 * math.pi * resonant_hz) ** 2
    low_l, high_l = tested["l_total_h"]
    return {
        "lc_product_s2": lc_product,
        "resonant_hz": resonant_hz,
        "clock_hz": clock_hz,
        "capacitance_f": capacitance_f,
        "c_max_f": lc_product / low_l,
        "c_min_f": lc_product / high_l,
        "c_clock_ceiling_f": 1.0 / (2.0 * math.pi * clock_hz) ** 2 / tank["total_target_h"],
        "l_total_tested_h": [low_l, high_l],
        "l_external_tested_h": list(tested["l_external_h"]),
    }


def trim_external(capacitance_f: float, lc_product_s2: float, leakage_h: float) -> float:
    """The external Lr the first article has to trim to for a given bank.

    Holding fr fixed means holding L_total * C; the leakage is subtracted because it
    comes with the transformer and cannot be trimmed.
    """
    if capacitance_f <= 0.0:
        raise ValueError("capacitance must be positive")
    return lc_product_s2 / capacitance_f - leakage_h


def max_nominal_for_tolerance(tuning_data: dict[str, object], tolerance: float) -> float:
    """Highest nominal bank a given capacitance grade can be built at.

    A +tolerance part must not push the measured bank past the top of the band.
    """
    return float(tuning_data["c_max_f"]) / (1.0 + tolerance)


def _per_part(values_nf: tuple[int, ...], requirements: dict[str, float]) -> list[dict[str, float]]:
    total_f = sum(values_nf) * 1e-9
    n = len(values_nf)
    return [{
        "c_f": value * 1e-9,
        # parallel capacitors split ripple in proportion to capacitance, not equally
        "share_frac": value * 1e-9 / total_f,
        "irms_a": requirements["irms_a"] * value * 1e-9 / total_f,
        "ipk_a": requirements["i_pk_a"] * value * 1e-9 / total_f,
        # bank ESR = part ESR / N only for equal parts; here each part must stay
        # under N times the bank ceiling so that any mix still meets the bank
        "esr_max_ohm": requirements["esr_ceiling_ohm"] * n,
        "v_rated_min_v": requirements["v_rated_v"],
    } for value in values_nf]


def band_landings(tuning_data: dict[str, object], values_nf: tuple[int, ...], max_parts: int,
                  target_f: float, requirements: dict[str, float] | None = None) -> list[dict[str, object]]:
    """Standard-value combinations whose sum falls inside the capacitance band."""
    if requirements is None:
        requirements = default_requirements()
    band_low, band_high = float(tuning_data["c_min_f"]), float(tuning_data["c_max_f"])
    landings = []
    for n in range(1, max_parts + 1):
        for combo in combinations_with_replacement(sorted(values_nf), n):
            total_f = sum(combo) * 1e-9
            if not band_low - 1e-15 <= total_f <= band_high + 1e-15:
                continue
            per_part = _per_part(combo, requirements)
            landings.append({
                "values_nf": sorted(combo),
                "n_parts": n,
                "total_f": total_f,
                "delta_frac": total_f / target_f - 1.0,
                "external_trim_h": trim_external(total_f, float(tuning_data["lc_product_s2"]),
                                                 requirements["leakage_model_h"]),
                "per_part": per_part,
                "max_part_irms_a": max(part["irms_a"] for part in per_part),
                "equal_parts": len(set(combo)) == 1,
            })
    # fewest parts first, then the least stress on any one of them: a two-part bank
    # on target is the cheapest, but it puts three quarters of the ripple on one part
    landings.sort(key=lambda item: (abs(item["delta_frac"]), item["n_parts"],
                                    item["max_part_irms_a"], item["values_nf"]))
    return landings


def _sizing_point(path: Path) -> dict[str, object]:
    """The four bank-level stresses one operating point puts on the resonant capacitor."""
    stress = json.loads(path.read_text(encoding="utf-8"))
    return {
        "source": str(path.relative_to(REPO)).replace("\\", "/"),
        "raw": stress["raw"],
        "i_rms_a": stress["i_rms_a"],
        "i_pk_a": stress["i_pk_a"],
        "v_max_v": stress["v_max_v"],
        "rating_margin": stress["rating_margin"],
        "esr_ceiling_ohm": stress["esr_ceiling_ohm"],
    }


def default_requirements() -> dict[str, object]:
    """The electrical envelope the worst measured load puts on the bank.

    The rated 100 A point is the one the tank was designed at, but it is not the
    worst one that has been run: the 48 V/120 A overload candidate is in the
    evidence set and puts 18.8 % more ripple through `Cr`, which tightens the
    self-heating ESR ceiling by 29 %.  Sizing on the 100 A figure would size the
    bank 41 % too loose on the number that decides how many parts it takes.  Both
    points are published so neither can be quoted as if it were the other.
    """
    rated = _sizing_point(CR_STRESS)
    overload = _sizing_point(CR_STRESS_OVERLOAD)
    worst = max((rated, overload), key=lambda point: point["i_rms_a"])
    tank = json.loads(LR_DESIGN.read_text(encoding="utf-8"))["tank"]
    return {
        "capacitance_f": json.loads(CR_STRESS.read_text(encoding="utf-8"))["capacitance_f"],
        "v_rated_v": json.loads(CR_STRESS_OVERLOAD.read_text(encoding="utf-8"))["v_rated_v"],
        "v_max_v": worst["v_max_v"],
        "rating_margin": worst["rating_margin"],
        "irms_a": worst["i_rms_a"],
        "i_pk_a": worst["i_pk_a"],
        "esr_ceiling_ohm": worst["esr_ceiling_ohm"],
        "p_allow_w": json.loads(CR_STRESS.read_text(encoding="utf-8"))["p_allow_w"],
        "leakage_model_h": tank["leakage_model_h"],
        "sized_at": worst["source"],
        "sizing_points": {"rated_100a": rated, "overload_120a": overload},
    }


def _tested_inductance(lr: dict[str, object], tank: dict[str, float]) -> dict[str, tuple[float, float]]:
    """Inductance the tank has been run at, in total and external terms.

    The low end of the total window is the design point itself (the 100 A operating
    point).  The high end is a 1.0 uH external part -- the sizing value the Lr note
    calls the top of the trim window -- at the model leakage, i.e. 1.08 uH total.
    """
    external_run_h = [case["external_lr_h"] for case in lr["physical_peaks"]["cases"].values()]
    return {
        "l_total_h": (tank["total_target_h"], max(external_run_h) + tank["leakage_model_h"]),
        "l_external_h": (min(external_run_h), max(external_run_h)),
    }


def _best_per_part_count(landings: list[dict[str, object]]) -> list[dict[str, object]]:
    """The best bank at each part count: closest to target, then least stressed.

    The full enumeration is over four hundred combinations and says nothing a design
    decision can use; one row per part count is the decision table.
    """
    if not landings:
        raise SystemExit("no standard-value bank lands inside the capacitance band")
    best: dict[int, dict[str, object]] = {}
    for landing in landings:
        key = (abs(landing["delta_frac"]), landing["max_part_irms_a"], landing["values_nf"])
        current = best.get(landing["n_parts"])
        if current is None or key < (abs(current["delta_frac"]), current["max_part_irms_a"], current["values_nf"]):
            best[landing["n_parts"]] = landing
    return [best[n] for n in sorted(best)]


def _equal_parts_option(landings: list[dict[str, object]]) -> dict[str, object]:
    """Best bank made of identical parts, for anyone who would rather buy one line item.

    Every such landing is below the design capacitance, so it moves the Lr trim; the
    one closest to target is reported with that movement stated.
    """
    equal = [landing for landing in landings if landing["equal_parts"]]
    if not equal:
        raise SystemExit("no equal-part bank lands inside the capacitance band")
    return min(equal, key=lambda item: (abs(item["delta_frac"]), item["n_parts"]))


def report() -> dict[str, object]:
    stress = json.loads(CR_STRESS.read_text(encoding="utf-8"))
    lr = json.loads(LR_DESIGN.read_text(encoding="utf-8"))
    tank = lr["tank"]
    params = deck_params(DECK)
    requirements = default_requirements()
    tested = _tested_inductance(lr, tank)

    data = tuning(tank, stress["capacitance_f"], tested)
    all_landings = band_landings(data, E12_NF, max_parts=6, target_f=stress["capacitance_f"],
                                 requirements=requirements)
    external_low, external_high = data["l_external_tested_h"]
    trims_ok = all(
        external_low - 1e-15 <= trim_external(landing["total_f"], data["lc_product_s2"], leakage) <= external_high + 1e-15
        for landing in all_landings
        for leakage in (requirements["leakage_model_h"], LEAKAGE_TRIM_END_H)
    )
    grades = [{"tolerance": grade, "max_nominal_f": max_nominal_for_tolerance(data, grade)} for grade in TOLERANCE_GRADES]
    equal_option = _equal_parts_option(all_landings)

    return {
        "status": "sizing only; no capacitor datasheet exists in the repository, so every per-part "
                  "figure is a requirement, not a selected part",
        "sources": {"deck": str(DECK.relative_to(REPO)).replace("\\", "/"),
                    "cr_stress": str(CR_STRESS.relative_to(REPO)).replace("\\", "/"),
                    "cr_stress_overload": str(CR_STRESS_OVERLOAD.relative_to(REPO)).replace("\\", "/"),
                    "lr_design": str(LR_DESIGN.relative_to(REPO)).replace("\\", "/")},
        "requirements": requirements,
        "tuning": {
            "lc_product_s2": data["lc_product_s2"],
            "resonant_hz": data["resonant_hz"],
            "clock_hz": data["clock_hz"],
            "c_max_f": data["c_max_f"],
            "c_min_f": data["c_min_f"],
            "c_clock_ceiling_f": data["c_clock_ceiling_f"],
            "l_total_tested_h": data["l_total_tested_h"],
            "l_external_tested_h": data["l_external_tested_h"],
            "basis": "the band is a trim-feasibility band, not a set of interchangeable tanks. Upper bound: "
                     "the design inductance, i.e. the 620 nF the 100 A point runs. Lower bound: a 1.0 uH "
                     "external part (the sizing top of the trim window) at the model leakage, total 1.08 uH. "
                     "The clock alone would allow up to 629.3 nF, so the inductor window is the binding bound.",
        },
        "tolerance_rule": grades,
        "landings_in_band": len(all_landings),
        "landings": _best_per_part_count(all_landings),
        "landing_shortlist_rule": "one row per part count: closest to the design capacitance, then the least "
                                  "ripple on any single part. The full enumeration is a tool run away, not a file.",
        "recommended": {
            "values_nf": all_landings[0]["values_nf"],
            "total_f": all_landings[0]["total_f"],
            "max_part_irms_a": all_landings[0]["max_part_irms_a"],
            "reason": "lands exactly on the design capacitance with the fewest parts, so the Lr trim target "
                      "stays the nominal 0.92 uH external; the parts are unequal, so ripple divides in "
                      "proportion to capacitance rather than equally, and the "
                      f"{max(all_landings[0]['per_part'], key=lambda part: part['irms_a'])['c_f'] * 1e9:.0f} nF "
                      f"part carries {all_landings[0]['max_part_irms_a']:.2f} A rms",
        },
        "equal_parts_option": {
            "values_nf": equal_option["values_nf"],
            "total_f": equal_option["total_f"],
            "delta_frac": equal_option["delta_frac"],
            "max_part_irms_a": equal_option["max_part_irms_a"],
            "reason": "one line item instead of two, at the cost of landing below the design capacitance and "
                      "therefore moving the Lr trim inside the simulated window",
        },
        "checks": {
            "deck_capacitance_matches_the_stress_run":
                abs(params["CR_TOTAL"] - stress["capacitance_f"]) < 1e-18,
            "deck_external_inductance_matches_the_tank_target":
                abs(params["LR_TOTAL"] - lr["tank"]["external_target_h"]) < 1e-18,
            "the_design_product_reproduces_the_tank_frequency":
                abs(1.0 / (2.0 * math.pi * math.sqrt(data["lc_product_s2"])) - data["resonant_hz"]) < 1.0,
            # structural, not physical: the requirement block must be the worst measured
            # point, so a new run added to `sizing_points` cannot leave the scalar keys
            # quoting the rated one
            "the_requirement_is_the_worst_measured_load": requirements["irms_a"] == max(
                point["i_rms_a"] for point in requirements["sizing_points"].values()),
            "every_landing_is_inside_the_band": all(
                data["c_min_f"] - 1e-15 <= landing["total_f"] <= data["c_max_f"] + 1e-15
                for landing in all_landings),
            "every_landing_keeps_fr_above_the_clock": data["resonant_hz"] > data["clock_hz"],
        },
        "results": {
            "c_band_f": [data["c_min_f"], data["c_max_f"]],
            "fr_without_retune_at_the_band_bottom_hz": 1.0 / (2.0 * math.pi * math.sqrt(
                tank["total_target_h"] * data["c_min_f"])),
            # the other edge fails the other way: a nominal 1.0 uH external part, untrimmed,
            # puts fr below the clock, which is why the trim is not optional
            "fr_untrimmed_with_a_nominal_1u0_part_hz": 1.0 / (2.0 * math.pi * math.sqrt(
                data["l_total_tested_h"][1] * stress["capacitance_f"])),
            "every_landing_keeps_the_trim_inside_the_simulated_window": trims_ok,
            "the_design_point_has_no_upward_capacitance_headroom": data["c_max_f"] <= stress["capacitance_f"] + 1e-15,
            "five_percent_parts_need_a_lower_nominal": max_nominal_for_tolerance(data, 0.05) < stress["capacitance_f"],
            "ten_percent_parts_have_no_landing_in_the_band": max_nominal_for_tolerance(data, 0.10) < data["c_min_f"],
            "the_100_a_point_is_only_simulated_at_the_design_capacitance": True,
            # holding L*C fixed keeps the frequency but not the tank: Z0 = sqrt(L/C) = L / sqrt(LC),
            # so it scales with inductance, and the band bottom is 8 % above the design point
            "tank_impedance_ohm_at_design": math.sqrt(tank["total_target_h"] / stress["capacitance_f"]),
            "tank_impedance_ohm_at_band_bottom": math.sqrt(data["l_total_tested_h"][1] / data["c_min_f"]),
            "tank_impedance_ratio_at_band_bottom": (data["l_total_tested_h"][1] / tank["total_target_h"]),
        },
        "no_capacitor_datasheet_in_repository": True,
        "caveats": [
            "ripple divides in proportion to capacitance only while the parts are still capacitive at "
            "200 kHz; above their self-resonance the split follows impedance, which is not modelled",
            "bank ESR = part ESR / N ignores interconnect resistance; at 2-3 parts that is small but unmeasured",
            "the 100 A operating point was simulated at 620 nF and 1.0 uH total only; a landing at 600 nF "
            "changes the tank gain at the fixed clock and needs its own run before it replaces the design point",
            "self-heating, dV/dt rating and lifetime of the film parts are not modelled anywhere here",
            "the capacitance band assumes the Lr trim window 0.875-1.0 uH external is the evidence window; "
            "a total inductance outside 1.0-1.08 uH has not been run at the 100 A point",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path, default=Path("design/v3/bom/cr_bank.json"))
    args = parser.parse_args()
    data = report()
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(args.json)
    band = data["results"]["c_band_f"]
    print(f"bank band: {band[0] * 1e9:.1f} - {band[1] * 1e9:.1f} nF at {data['tuning']['resonant_hz'] / 1e3:.3f} kHz")
    for landing in data["landings"]:
        values = " + ".join(str(value) for value in landing["values_nf"])
        print(f"  {landing['n_parts']} x ({values}) nF = {landing['total_f'] * 1e9:.0f} nF, "
              f"delta {landing['delta_frac'] * 100:+.2f}%, L_ext {landing['external_trim_h'] * 1e6:.4f} uH, "
              f"max part {landing['max_part_irms_a']:.2f} A rms")
    print(f"landings in band: {data['landings_in_band']} "
          f"(shortlist shows the best bank at each part count)")


if __name__ == "__main__":
    main()

"""Non-rated 48 V/50 V high-output design sensitivity, not a hardware or SPICE run.

Works directly from committed V3 data. Allows modestly higher output-path
resistance in exchange for a higher *candidate* delivered output current/power.
Resistive and fixed-ratio approximations only; nonlinear switching, magnetic
saturation, SR timing, startup, protection, capacitor ripple and continuous
ratings MUST be validated separately. No thermal design is performed here.

Usage: python tools/high_output_sweep.py --json design/v3/power_priority/scenarios.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OP = ROOT / "design/v3/magnetics/operating_point_100a.json"
MAG = ROOT / "design/v3/magnetics/magnetics_design.json"

# Engineering exploration candidates; NOT newly released ratings.
VINS_V = (48.0, 50.0)
IOUTS_A = (100.0, 110.0, 120.0)
PATHS_OHM = (0.00015, 0.00030, 0.00045)
RATIO = 24.0
CONVERTER_PORT = "V(out) at converter before external output bar and contacts"


def calc(vin_v: float, current_a: float, path_ohm: float,
         base: dict, r_incremental_ohm: float) -> dict:
    """Local voltage/load-line sensitivity, NOT a nonlinear LLC solution.

    V0 includes converter internal resistance at its measured operating point;
    changing path R must only be deducted once at the physical load terminals.
    The source-voltage dependence (vin-48)/24 is an ideal fixed-ratio approximation.
    """
    if not 0 < vin_v <= 54 or not 0 < current_a <= 200 or path_ohm < 0:
        raise ValueError("positive, bounded study inputs required")
    i0 = float(base["iout_from_v_a"])
    v0 = float(base["vout_avg_v"])
    vconv = v0 + (vin_v - 48.0) / RATIO - (current_a - i0) * r_incremental_ohm
    vdrop = current_a * path_ohm
    vload = vconv - vdrop
    # Do not claim achieved rating even if the simple model looks favourable.
    return {
        "vin_v": vin_v,
        "iout_a": current_a,
        "path_resistance_mohm": round(path_ohm * 1000, 5),
        "v_converter_est_v": round(vconv, 5),
        "v_load_est_v": round(vload, 5),
        "p_load_est_w": round(vload * current_a, 3),
        "p_output_path_est_w": round(current_a**2 * path_ohm, 3),
        "loss_factor_pure_i2r_vs_base": round((current_a / i0) ** 2, 4),
        "i_per_sr_group_if_balanced_a": round(current_a / 4, 2),
        "source": "LOCAL_LINEAR_SENSITIVITY_NOT_SIMULATED",
        "rating_approved": False,
    }


def sweep() -> dict:
    op = json.loads(OP.read_text(encoding="utf-8"))
    mag = json.loads(MAG.read_text(encoding="utf-8"))
    r = float(mag["r_out_equiv_ohm"])
    rows = [calc(v, i, p, op, r) for v in VINS_V
            for i in IOUTS_A for p in PATHS_OHM]
    return {
        "status": "SCENARIO_ONLY_NOT_HARDWARE_OR_LTSPICE",
        "basis": {
            "op_100a": OP.relative_to(ROOT).as_posix(),
            "magnetics_model": MAG.relative_to(ROOT).as_posix(),
            "vin_reference_v": 48.0,
            "vout_measured_converter_v": op["vout_avg_v"],
            "iout_measured_a": op["iout_from_v_a"],
            "incremental_internal_r_ohm": r,
            "ratio_ideal": RATIO,
            "port_definition": CONVERTER_PORT,
            "not_modelled": [
                "nonlinear LLC load line or frequency shift",
                "conduction and switching losses at higher current",
                "SR turn-off, reverse current, device SOA",
                "real controller over-current trip and startup dynamics",
                "resonant inductor nonlinearity, saturation and CT response",
                "output capacitor ripple current, voltage and ESR/ESL",
                "contact resistance temperature dependence and unequal 4-way current sharing",
                "thermal steady state and mechanical cooling, deferred by project decision",
            ],
        },
        "rows": rows,
        "required_next_tests": [
            "Create LTspice load sweep for I=100, 110, 120 A at 48/50 V with identical real physical decks",
            "Measure SR1..SR4 branch currents, device VDS/VGS and reverse-conduction windows",
            "Check Lr primary fault peak and 3-turn L(I) against peak including trip delay",
            "Re-rate Cr/Cout ripple, capacitor overvoltage, CT, copper and output contacts",
            "Record power at converter port and separately at load terminals",
            "Keep a temporary laboratory current/time limit; do not certify continuous current until safety/thermal verification",
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path, default=ROOT / "design/v3/power_priority/scenarios.json")
    args = ap.parse_args()
    data = sweep()
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(data['rows'])} scenario candidates; rated: False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

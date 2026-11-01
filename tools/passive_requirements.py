"""Derive passive-component requirements from the measured 100 A operating point.

The output-capacitor ripple current is not saved as a trace, so it is rebuilt
from KCL: the four secondary SR currents sum to the output current, and the
capacitor carries the difference from the DC load.  Pairs 2 and 3 are not
instrumented, so their contribution is taken from model symmetry; the mean is
checked against average(Vout)/RL before the RMS is used.

Usage:
    python tools/passive_requirements.py --json design/v3/bom/passive_requirements.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ascii_raw_window import read_window
from magnetics_design import OP_100

RAW = "sim/v3/sr_tank_dual_v33_ss_1ms_100a.raw"
SR_CURRENTS = ["I(VSa1)", "I(VSb1)", "I(VSa4)", "I(VSb4)"]


def trapezoid_mean(y: np.ndarray, t: np.ndarray) -> float:
    return float(np.trapezoid(y, t) / (t[-1] - t[0]))


def capacitor_ripple(t: np.ndarray, secondary_total: np.ndarray) -> dict[str, float]:
    """Split the summed secondary current into DC load and capacitor current."""
    idc = trapezoid_mean(secondary_total, t)
    icap = secondary_total - idc
    return {
        "load_mean_a": idc,
        "ripple_rms_a": float(np.sqrt(trapezoid_mean(icap * icap, t))),
        "secondary_pp_a": float(secondary_total.max() - secondary_total.min()),
        "ripple_pk_a": float(np.abs(icap).max()),
    }


def secondary_total_from_pairs(t: np.ndarray, currents: dict[str, np.ndarray]) -> np.ndarray:
    """Pairs 1 and 4 are measured; pairs 2 and 3 are assumed identical (model symmetry)."""
    pair_sum = -(currents["I(VSa1)"] + currents["I(VSb1)"] + currents["I(VSa4)"] + currents["I(VSb4)"])
    return 2.0 * pair_sum


def cr_lr_requirements(op: dict[str, float], lr_h: float = 1e-6) -> dict[str, float]:
    """Cr and Lr share the series primary current in this topology."""
    ipk = op["Ipri_pk_A"]
    return {
        "irms_a": op["Ipri_rms_A"],
        "ipk_a": ipk,
        "v_rating_min_v": 100.0,
        "lr_energy_at_ipk_j": 0.5 * lr_h * ipk * ipk,
        "lr_flux_linkage_at_ipk_hA": lr_h * ipk,
    }


def path_loss(current_a: float, resistance_ohm: float) -> float:
    return current_a * current_a * resistance_ohm


def pair_ac_rms(t: np.ndarray, pair_current: np.ndarray) -> float:
    idc = trapezoid_mean(pair_current, t)
    return float(np.sqrt(trapezoid_mean((pair_current - idc) ** 2, t)))


def measure_cout(raw: str | Path, t0_us: float, t1_us: float) -> dict[str, float]:
    t, v = read_window(raw, SR_CURRENTS, t0_us * 1e-6, t1_us * 1e-6)
    out = capacitor_ripple(t, secondary_total_from_pairs(t, v))
    out["pair1_ac_rms_a"] = pair_ac_rms(t, -(v["I(VSa1)"] + v["I(VSb1)"]))
    out["pair4_ac_rms_a"] = pair_ac_rms(t, -(v["I(VSa4)"] + v["I(VSb4)"]))
    return out


def measure_cin(raw: str | Path, t0_us: float, t1_us: float) -> dict[str, float]:
    """Input currents from the dedicated probe deck (saved I(Cin), I(Rin)).

    KCL at the 48 V node: the converter draws I(Rin) - I(Cin).  In the model the
    source is a 48 V battery behind 1 mohm, so the capacitor carries almost none
    of the ripple; the bridge current is what a real input filter has to supply.
    """
    t, v = read_window(raw, ["I(Cin)", "I(Rin)"], t0_us * 1e-6, t1_us * 1e-6)
    icin, irin = v["I(Cin)"], v["I(Rin)"]
    bridge = irin - icin
    return {
        "cin_mean_a": trapezoid_mean(icin, t),
        "cin_rms_ac_a": float(np.sqrt(trapezoid_mean((icin - trapezoid_mean(icin, t)) ** 2, t))),
        "source_mean_a": trapezoid_mean(irin, t),
        "source_rms_ac_a": float(
            np.sqrt(trapezoid_mean((irin - trapezoid_mean(irin, t)) ** 2, t))
        ),
        "bridge_mean_a": trapezoid_mean(bridge, t),
        "bridge_rms_a": float(np.sqrt(trapezoid_mean(bridge * bridge, t))),
        "bridge_ac_rms_a": float(
            np.sqrt(trapezoid_mean((bridge - trapezoid_mean(bridge, t)) ** 2, t))
        ),
    }


def report(raw: str | Path = RAW, t0_us: float | None = None, t1_us: float | None = None) -> dict[str, object]:
    t0 = OP_100["window_us"] if t0_us is None else t0_us
    t1 = OP_100["window_us_end"] if t1_us is None else t1_us
    cout = measure_cout(raw, t0, t1)
    cout["mean_check_pct"] = 100.0 * (cout["load_mean_a"] - OP_100["Iout_A"]) / OP_100["Iout_A"]
    return {
        "status": "model measurement, not hardware",
        "raw": str(raw),
        "window_us": [t0, t1],
        "iout_from_v_a": OP_100["Iout_A"],
        "cout_ripple": cout,
        "cout_scope": {
            "measured_pairs": [1, 4],
            "assumed_pairs": [2, 3],
            "note": "four groups are driven in phase, so the measured sum is the correlated (worst) case; "
                    "layout skew would lower it toward sqrt(4) x one pair's AC RMS",
        },
        "cr_lr": cr_lr_requirements(OP_100),
        "path_loss_w": {
            "0.05_mohm": path_loss(OP_100["Iout_A"], 0.05e-3),
            "0.10_mohm": path_loss(OP_100["Iout_A"], 0.10e-3),
            "0.15_mohm": path_loss(OP_100["Iout_A"], 0.15e-3),
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path, default=Path("design/v3/bom/passive_requirements.json"))
    ap.add_argument("--cin-raw", type=Path, default=None,
                    help="raw from the I(Cin)/I(Rin) probe deck; omit until that run exists")
    args = ap.parse_args()
    data = report()
    if args.cin_raw is not None:
        cin = measure_cin(args.cin_raw, *data["window_us"])
        cin["raw"] = str(args.cin_raw)
        data["cin"] = cin
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(args.json)


if __name__ == "__main__":
    main()

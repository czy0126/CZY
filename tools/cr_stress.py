"""Reconstruct the resonant-capacitor voltage from the measured series current.

`V(Cr)` was never saved in the 100 A deck, so the Cr voltage stress is the one
power-path quantity the BOM still guessed at.  It does not have to be guessed:
Cr is in series with Lr, so its voltage follows from `I(Lr)` by integration,

    v(t) = v(0) + (1/C) * integral(i dt)

The integration constant is not free.  In steady state the transformer primary
sees zero average volts (flux balance) and the inductor too (volt-second
balance), so whatever DC the half-bridge midpoint carries must appear across the
blocking capacitor:

    mean(v_Cr) = mean(V(sw))

That makes the absolute peak measurable rather than assumed, and it is the number
a voltage rating has to cover.

Usage:
    python tools/cr_stress.py --json design/v3/bom/cr_stress.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ascii_raw_window import read_window  # noqa: E402

CR_F = 0.62e-6
V_RATED_V = 100.0
P_ALLOW_W = 1.0          # ~0.5 % of the 188 W output; a film cap's own budget
RAW = "sim/v3/sr_tank_dual_v33_ss_1ms_100a.raw"
REQUIREMENTS = Path("design/v3/bom/passive_requirements.json")


def trapezoid_mean(values: np.ndarray, t: np.ndarray) -> float:
    return float(np.trapezoid(values, t) / (t[-1] - t[0]))


def cr_voltage(t: np.ndarray, i: np.ndarray, c_f: float,
               v_dc: float | None = None) -> dict[str, object]:
    """v_Cr(t) from the series current, centred so that its mean is v_dc.

    `v_dc` defaults to 0, which is what you want when the caller only cares about
    the ripple; passing mean(V(sw)) gives the absolute waveform.
    """
    if c_f <= 0:
        raise ValueError("capacitance must be positive")
    steps = 0.5 * (i[1:] + i[:-1]) * np.diff(t)
    charge = np.concatenate(([0.0], np.cumsum(steps)))
    swing = charge / c_f
    offset = 0.0 if v_dc is None else v_dc
    v = offset + swing - trapezoid_mean(swing, t)
    return {
        "v": v,
        "v_max": float(v.max()),
        "v_min": float(v.min()),
        "v_pp": float(v.max() - v.min()),
        "v_mean": float(trapezoid_mean(v, t)),
        # if the window holds an integer number of periods this returns to zero
        "periodicity_residual_v": float(swing[-1] - swing[0]),
    }


def esr_ceiling(i_rms: float, p_allow_w: float) -> float:
    """Bank ESR that keeps I^2*ESR inside an allowed dissipation.

    This is the real Cr selection constraint: film capacitors are not limited by
    voltage here (the swing is well inside the rating) but by how much ripple
    current they can take at 200 kHz, which is an ESR/heating statement.
    """
    if i_rms <= 0:
        raise ValueError("current must be positive")
    return p_allow_w / (i_rms * i_rms)


def analyze(raw: str | Path, t0_us: float, t1_us: float, c_f: float = CR_F,
            v_rated: float = V_RATED_V) -> dict[str, object]:
    t, v = read_window(raw, ["I(Lr)", "V(sw)"], t0_us * 1e-6, t1_us * 1e-6)
    if t.size < 3:
        raise ValueError("window contains too few points")
    i = v["I(Lr)"]
    vsw = v["V(sw)"]
    v_dc = trapezoid_mean(vsw, t)
    stress = cr_voltage(t, i, c_f, v_dc)
    return {
        "raw": str(raw),
        "window_us": [t0_us, t1_us],
        "capacitance_f": c_f,
        "v_rated_v": v_rated,
        "v_dc_v": v_dc,
        "v_max_v": stress["v_max"],
        "v_min_v": stress["v_min"],
        "v_pp_v": stress["v_pp"],
        "i_rms_a": float(np.sqrt(trapezoid_mean(i * i, t))),
        "i_pk_a": float(np.abs(i).max()),
        "periodicity_residual_v": stress["periodicity_residual_v"],
        "rating_margin": v_rated / stress["v_max"],
        "esr_ceiling_ohm": esr_ceiling(float(np.sqrt(trapezoid_mean(i * i, t))), P_ALLOW_W),
        "p_allow_w": P_ALLOW_W,
        "dissipation_at_1mohm_w": float(trapezoid_mean(i * i, t)) * 1e-3,
        "note": "mean(v_Cr) = mean(V(sw)) from transformer flux balance; "
                "v_Cr itself was not saved in this deck",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=RAW)
    ap.add_argument("--requirements", type=Path, default=REQUIREMENTS)
    ap.add_argument("--from-us", type=float)
    ap.add_argument("--to-us", type=float)
    ap.add_argument("--cr-f", type=float, default=CR_F)
    ap.add_argument("--v-rated", type=float, default=V_RATED_V)
    ap.add_argument("--json", type=Path, default=Path("design/v3/bom/cr_stress.json"))
    args = ap.parse_args()

    t0, t1 = args.from_us, args.to_us
    if t0 is None or t1 is None:
        window = json.loads(args.requirements.read_text(encoding="utf-8"))["window_us"]
        t0 = t0 if t0 is not None else window[0]
        t1 = t1 if t1 is not None else window[1]

    data = analyze(args.raw, t0, t1, args.cr_f, args.v_rated)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{data['v_max_v']:.2f} V peak, {data['v_pp_v']:.2f} V pp, "
          f"{data['i_rms_a']:.3f} A RMS, margin {data['rating_margin']:.2f}x at {args.v_rated:.0f} V")
    print(args.json)


if __name__ == "__main__":
    main()

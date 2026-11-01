"""Measure the over-current network in the deck and compare it with the algebra.

`tools/ct_design.py` predicts the OC pin voltage as
`mean(R_b*|i_sec|) * Rd2/(Rf+Rd1+Rd2)` -- linear in current, no clipping term.
This tool checks that against the reruns:

    python tools/oc_network_check.py --raw sim/v3/..._ct10.raw --burden 10 --rd1 10k
    python tools/oc_network_check.py --raw sim/v3/..._ct47.raw --burden 47 --rd1 110k

Three quantities become measured rather than derived:

  * the burden average `V(ocd)` against `ct_design.burden_average()`,
  * the divider gain against `ct_design.divider_gain()`,
  * the OC pin voltage at rated current against the 1 V Level-1 threshold.

The first of those is the reason this tool exists.  A clipped-rectifier model
("the bridge conducts only above 2Vf") once predicted 61 mV at the burden where
the deck showed 834 mV; that model is gone, and the check that killed it is the
`residual.v_ocd` column below.  The residual is now a few percent from waveform
shape and diode junction capacitance, not an order of magnitude from topology.

Two things the model still cannot say: the CT's own magnetising current and
saturation (Lct2 is a fixed 20 mH with an ideal coupling coefficient), and the
diode's junction capacitance is present here but absent from the closed form.

The window is quantised to whole switching periods so the mean is not biased by
a partial cycle -- the same rule the rest of the project's per-period metrics use.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

import ct_design
from ascii_raw_window import read_window

ROOT = Path(__file__).resolve().parent.parent
PERIODS = 22          # same family as design/v3/magnetics/operating_point_100a.json
V_SW_LEVEL = 24.0     # half of 48 V: the half-bridge square wave
SETTLE_US = 0.0


def crossing_times(t: np.ndarray, v: np.ndarray, level: float) -> np.ndarray:
    """Linearly interpolated rising crossings of `level`."""
    above = v > level
    idx = np.nonzero(~above[:-1] & above[1:])[0]
    out = []
    for i in idx:
        v0, v1 = v[i], v[i + 1]
        frac = 0.0 if v1 == v0 else (level - v0) / (v1 - v0)
        out.append(t[i] + frac * (t[i + 1] - t[i]))
    return np.asarray(out)


def whole_period_window(t: np.ndarray, v_sw: np.ndarray, periods: int) -> tuple[float, float, float]:
    """(start, end, period) of the last `periods` complete switching cycles."""
    edges = crossing_times(t, v_sw, V_SW_LEVEL)
    if edges.size < periods + 1:
        raise ValueError(f"only {edges.size} switching edges; need {periods + 1}")
    start, end = float(edges[-periods - 1]), float(edges[-1])
    return start, end, (end - start) / periods


def trapezoid_mean(values: np.ndarray, t: np.ndarray) -> float:
    if t.size < 2:
        return float(values[0])
    return float(np.trapezoid(values, t) / (t[-1] - t[0]))


def analyze(raw: Path, burden_ohm: float, rd1_ohm: float, rd2_ohm: float = ct_design.R_D2_OHM,
            rf_ohm: float = ct_design.R_F_OHM, periods: int = PERIODS) -> dict[str, object]:
    traces = ["V(sw)", "I(Lr)", "V(ocd)", "V(oc1)", "V(oc)"]
    t_all, data = read_window(raw, traces, 0.0, None)
    t0, t1, period = whole_period_window(t_all, data["V(sw)"], periods)
    mask = (t_all >= t0) & (t_all <= t1)
    t = t_all[mask]
    if t.size < 10:
        raise ValueError(f"window {t0:.6g}..{t1:.6g} s holds only {t.size} points")

    i_lr = data["I(Lr)"][mask]
    v_ocd = data["V(ocd)"][mask]
    v_oc1 = data["V(oc1)"][mask]
    v_oc = data["V(oc)"][mask]

    i_pk = float(np.max(np.abs(i_lr)))
    i_avg = trapezoid_mean(np.abs(i_lr), t)
    i_rms = float(np.sqrt(trapezoid_mean(i_lr ** 2, t)))
    v_ocd_mean = trapezoid_mean(v_ocd, t)
    v_oc_mean = trapezoid_mean(v_oc, t)
    v_oc1_mean = trapezoid_mean(v_oc1, t)

    gain_measured = v_oc_mean / v_ocd_mean if v_ocd_mean else float("nan")
    gain_predicted = ct_design.divider_gain(rd1_ohm, rd2_ohm, rf_ohm)
    burden_predicted = ct_design.burden_average(i_avg, burden_ohm)
    oc_predicted = burden_predicted * gain_predicted

    def residual(measured: float, predicted: float) -> float:
        return float("nan") if predicted == 0 else (measured - predicted) / predicted

    return {
        "raw": str(raw.relative_to(ROOT)) if raw.is_relative_to(ROOT) else str(raw),
        "network": {"burden_ohm": burden_ohm, "rd1_ohm": rd1_ohm, "rd2_ohm": rd2_ohm, "rf_ohm": rf_ohm},
        "window": {
            "periods": periods,
            "start_us": round((t0 - t_all[0]) * 1e6, 4),
            "end_us": round((t1 - t_all[0]) * 1e6, 4),
            "period_us": round(period * 1e6, 5),
            "points": int(t.size),
        },
        "primary": {
            "i_pk_a": round(i_pk, 5),
            "i_avg_a": round(i_avg, 5),
            "i_rms_a": round(i_rms, 5),
            "peak_to_average": round(i_pk / i_avg, 5) if i_avg else None,
        },
        "measured": {
            "v_ocd_mean_v": round(v_ocd_mean, 6),
            "v_oc1_mean_v": round(v_oc1_mean, 6),
            "v_oc_mean_v": round(v_oc_mean, 6),
            "v_oc_ripple_pp_v": round(float(np.ptp(v_oc)), 6),
            "divider_gain": round(gain_measured, 6),
        },
        "predicted": {
            "v_ocd_mean_v": round(burden_predicted, 6),
            "divider_gain": round(gain_predicted, 6),
            "v_oc_mean_v": round(oc_predicted, 6),
        },
        "residual": {
            "v_ocd": round(residual(v_ocd_mean, burden_predicted), 4),
            "divider_gain": round(residual(gain_measured, gain_predicted), 4),
            "v_oc": round(residual(v_oc_mean, oc_predicted), 4),
        },
        "trip": {
            "threshold_v": ct_design.V_OC_TRIP,
            "headroom_ratio": round(ct_design.V_OC_TRIP / v_oc_mean, 3) if v_oc_mean else None,
            # The chain is linear in current, so the peak that trips is just the
            # measured peak scaled by the headroom. No bisection needed.
            "extrapolated_a": round(i_pk * ct_design.V_OC_TRIP / v_oc_mean, 3) if v_oc_mean else None,
            "from_algebra_a": (
                round(ct_design.trip_peak_current(i_pk / i_avg, r_burden=burden_ohm, gain=gain_predicted), 3)
                if i_avg else None
            ),
        },
        "assumptions": [
            "the CT is ideal: Lct2 is a fixed 20 mH with Kct=1, so magnetising current and core "
            "saturation are NOT in this number",
            "the closed form omits the diode junction capacitance (Cjo=20p) that the deck has, "
            "which is why the burden residual is not zero",
            "the deck starts from .ic, so this is a warm steady state, not a cold start",
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, required=True)
    ap.add_argument("--burden", type=float, required=True)
    ap.add_argument("--rd1", type=str, required=True, help="e.g. 10k or 110000")
    ap.add_argument("--rd2", type=str, default="24k")
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()

    def ohms(text: str) -> float:
        text = text.strip().lower()
        return float(text[:-1]) * 1e3 if text.endswith("k") else float(text)

    result = analyze(args.raw.resolve(), args.burden, ohms(args.rd1), ohms(args.rd2))
    payload = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(payload, encoding="utf-8")
    print(payload, end="")

    m, p, trip = result["measured"], result["predicted"], result["trip"]
    print(f"\nOC pin at {result['primary']['i_pk_a']:.2f} A peak: "
          f"measured {m['v_oc_mean_v'] * 1e3:.1f} mV "
          f"(algebra {p['v_oc_mean_v'] * 1e3:.1f} mV, "
          f"{result['residual']['v_oc'] * 100:+.1f} %), "
          f"ripple {m['v_oc_ripple_pp_v'] * 1e3:.1f} mV pp")
    if trip["headroom_ratio"] is None:
        print("headroom: no burden voltage at all")
    else:
        print(f"headroom to the 1 V Level-1 threshold: {trip['headroom_ratio']:.2f}x; "
              f"extrapolated trip {trip['extrapolated_a']:.2f} A peak "
              f"(algebra {trip['from_algebra_a']:.2f} A)")


if __name__ == "__main__":
    main()

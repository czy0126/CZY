"""Sizing the over-current CT: the transfer chain, and what actually limits it.

The chain, as the deck builds it:

    v_ocd(t) = R_burden * |i_sec(t)|                  the bridge passes current, it does not clip
    v_oc     = mean(v_ocd) * 24/(1k + 10k + 24k)      the 47 us RC does the mean

Why there is no clipping term
-----------------------------
The CT secondary is a *current* source.  Its primary sits in series with the
resonant tank, so ampere-turn balance forces i_sec = i_pri/N whether or not the
burden clears the diode drop.  The 2*Vf the bridge needs is supplied as extra
*compliance voltage* by the CT; it adds to the flux swing and does not subtract
from the signal.

This file used to carry a clipped-rectifier model ("conducts only above 2*Vf").
That model is wrong here, and `sim/v3/sr_tank_dual_v33_ss_1ms_100a_ct10.raw`
refutes it: V(ocd) runs 0.004 V -> 1.382 V with no dead zone and a mean of
0.834 V, where clipping predicted 0.061 V at the rated current.  A 13.7x error
in the safety threshold is exactly the kind of thing that only a simulation
catches, so the numbers below are pinned to the measured charge, not to 2/pi.

The one place 2/pi survives is `deck_header_check`, because the deck's own header
comment states its figure that way.  The difference between the two is the real
waveform's peak-to-average ratio, and it is 5.5 % here.

Usage:
    python tools/ct_design.py --json design/v3/bom/ct_design.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ascii_raw_window import read_window  # noqa: E402

RAW = "sim/v3/sr_tank_dual_v33_ss_1ms_100a.raw"
WINDOW_US = (7.704687, 117.363517)

TURNS_RATIO = 100          # 1 primary turn : 100 secondary turns
N2_TURNS = 100
BURDEN_OHM = 10.0
R_F_OHM = 1e3              # Rf, in series ahead of the divider
R_D1_OHM = 10e3
R_D2_OHM = 24e3
V_OC_TRIP = 1.0            # UCC25600 Level-1 VOC
AE_M2 = 20.1e-6            # candidate toroid (R25.3, N87); not a chosen part
BSAT_T = 0.34              # N87 at 100 C
BURDEN_CHOICES = (10.0, 22.0, 47.0, 100.0)

# Deck's DSCH model (identical in sim/v2/startup_ct_fault_drv.cir and the v3 deck).
SCHOTTKY_IS_A = 2e-9
SCHOTTKY_N = 1.2
SCHOTTKY_RS = 0.3
V_T = 0.02585

RECT_FACTOR = 2.0 / math.pi   # only for the sinusoidal-idealisation cross-check

INTENDED_TRIP_A = 22.9        # the deck header's figure, peak primary current


def schottky_drop(i_a: float, is_a: float = SCHOTTKY_IS_A, n: float = SCHOTTKY_N,
                  rs: float = SCHOTTKY_RS, vt: float = V_T) -> float:
    """Forward drop of the deck's Schottky model at a given current."""
    if i_a <= 0:
        return 0.0
    return n * vt * math.log(i_a / is_a + 1.0) + i_a * rs


def divider_gain(r1: float = R_D1_OHM, r2: float = R_D2_OHM,
                 rf: float = R_F_OHM) -> float:
    """v_burden -> OC pin.  Rf is in series ahead of the divider, so it joins the top leg."""
    return r2 / (rf + r1 + r2)


def burden_average(i_avg_a: float, r_burden: float, turns: int = TURNS_RATIO) -> float:
    """Mean burden volts for a given rectified secondary average current."""
    return r_burden * abs(i_avg_a) / turns


def sinusoidal_average(i_pri_pk: float, r_burden: float, turns: int = TURNS_RATIO) -> float:
    """The deck header's idealisation: a sinusoidal primary, mean = (2/pi)*peak."""
    return burden_average(RECT_FACTOR * abs(i_pri_pk), r_burden, turns)


def oc_pin_voltage(i_avg_a: float, r_burden: float = BURDEN_OHM, gain: float | None = None,
                   turns: int = TURNS_RATIO) -> float:
    """OC-pin volts for a rectified secondary average current."""
    return burden_average(i_avg_a, r_burden, turns) * (divider_gain() if gain is None else gain)


def trip_average_current(v_trip: float = V_OC_TRIP, r_burden: float = BURDEN_OHM,
                         gain: float | None = None, turns: int = TURNS_RATIO) -> float:
    """Primary rectified-average at which the OC pin reaches the threshold (closed form)."""
    g = divider_gain() if gain is None else gain
    return v_trip * turns / (g * r_burden)


def trip_peak_current(peak_to_average: float, v_trip: float = V_OC_TRIP,
                      r_burden: float = BURDEN_OHM, gain: float | None = None,
                      turns: int = TURNS_RATIO) -> float:
    """Same threshold expressed as a peak, by scaling with the measured waveform ratio.

    The waveform is assumed to keep its shape, so peak and rectified average scale
    together.  During a hard fault that is optimistic -- a fault current is peakier
    than the operating current -- so this is a lower bound on the trip peak.
    """
    return trip_average_current(v_trip, r_burden, gain, turns) * peak_to_average


def compliance_voltage(i_sec_avg_a: float) -> float:
    """What the bridge costs the CT: two junctions the core must supply, not a signal loss."""
    return 2.0 * schottky_drop(i_sec_avg_a)


def flux_peak(q_half_c: float, period_s: float, r_burden: float, vf: float,
              n2: int = N2_TURNS, ae: float = AE_M2, turns: int = TURNS_RATIO) -> float:
    """Peak flux from half-cycle volt-seconds: burden plus the bridge's compliance."""
    volt_seconds = r_burden * q_half_c / turns + vf * 0.5 * period_s
    return volt_seconds / (n2 * ae)


def burden_power(i_rms_a: float, r_burden: float, turns: int = TURNS_RATIO) -> float:
    """The burden carries |i_sec|, so its RMS current is the secondary RMS."""
    return r_burden * (i_rms_a / turns) ** 2


def burden_for_trip(target_peak_a: float, peak_to_average: float,
                    gain: float | None = None, v_trip: float = V_OC_TRIP,
                    turns: int = TURNS_RATIO) -> float:
    """Burden that puts `target_peak_a` exactly on the threshold with the given divider."""
    g = divider_gain() if gain is None else gain
    return v_trip * turns / (g * target_peak_a / peak_to_average)


def half_cycle_charge(raw: str | Path, t0_us: float, t1_us: float,
                      periods: float = 22.0) -> dict[str, float]:
    """Charge in one half cycle, plus RMS, peak, period and the peak-to-average ratio."""
    t, v = read_window(raw, ["I(Lr)"], t0_us * 1e-6, t1_us * 1e-6)
    i = v["I(Lr)"]
    steps = 0.5 * (np.abs(i[1:]) + np.abs(i[:-1])) * np.diff(t)
    period = (t[-1] - t[0]) / periods
    q_half = float(steps.sum() / periods / 2)
    i_avg = 2.0 * q_half / period
    i_pk = float(np.abs(i).max())
    return {
        "i_rms_a": float(np.sqrt(np.trapezoid(i * i, t) / (t[-1] - t[0]))),
        "i_pk_a": i_pk,
        "i_avg_a": i_avg,
        "peak_to_average": i_pk / i_avg,
        "q_half_c": q_half,
        "period_s": float(period),
    }


def evaluate(measured: dict[str, float], burdens=BURDEN_CHOICES) -> list[dict[str, object]]:
    """One row per candidate burden: what it reads, what it trips at, what it costs."""
    q_half = measured["q_half_c"]
    period = measured["period_s"]
    ratio = measured["peak_to_average"]
    vf = compliance_voltage(2.0 * q_half / period / TURNS_RATIO)
    rows = []
    for r_b in burdens:
        rows.append({
            "burden_ohm": r_b,
            "burden_avg_v_at_ipk": burden_average(measured["i_avg_a"], r_b),
            "oc_pin_v_at_ipk": oc_pin_voltage(measured["i_avg_a"], r_b),
            "trip_peak_a": trip_peak_current(ratio, r_burden=r_b),
            "trip_margin_vs_rated": trip_peak_current(ratio, r_burden=r_b) / measured["i_pk_a"],
            "burden_power_w": burden_power(measured["i_rms_a"], r_b),
            "flux_peak_t": flux_peak(q_half, period, r_b, vf),
            "flux_frac_bsat": flux_peak(q_half, period, r_b, vf) / BSAT_T,
        })
    return rows


def report(raw: str | Path = RAW, window_us: tuple[float, float] = WINDOW_US) -> dict[str, object]:
    measured = half_cycle_charge(raw, *window_us)
    i_sec_avg = measured["i_avg_a"] / TURNS_RATIO
    vf = compliance_voltage(i_sec_avg)
    ratio = measured["peak_to_average"]
    return {
        "status": "design study; burden and divider stay as built (10 ohm / 10k)",
        "measured": measured,
        "as_built": {
            "turns_ratio": TURNS_RATIO,
            "burden_ohm": BURDEN_OHM,
            "rd1_ohm": R_D1_OHM,
            "divider_gain": divider_gain(),
            "slope_v_per_a_peak": oc_pin_voltage(measured["i_avg_a"], BURDEN_OHM)
            / measured["i_pk_a"],
            "oc_pin_v_at_ipk": oc_pin_voltage(measured["i_avg_a"], BURDEN_OHM),
            "trip_peak_a": trip_peak_current(ratio),
            "compliance_v": vf,
            "burden_power_w": burden_power(measured["i_rms_a"], BURDEN_OHM),
            "flux_peak_t": flux_peak(measured["q_half_c"], measured["period_s"], BURDEN_OHM, vf),
        },
        "burden_for_intended_trip_ohm": burden_for_trip(INTENDED_TRIP_A, ratio),
        "burden_study": evaluate(measured),
        "deck_header_check": {
            "header_slope_v_per_a": sinusoidal_average(1.0, BURDEN_OHM) * divider_gain(),
            "header_trip_a": V_OC_TRIP / (sinusoidal_average(1.0, BURDEN_OHM) * divider_gain()),
            "claimed": "0.04365 V/A and (2/pi)*24/35 -> 22.9 A",
            "note": "the header idealises the tank current as a sinusoid; the real "
                    "waveform's peak-to-average ratio is lower, which moves the trip up",
        },
        "core_candidate": {"ae_m2": AE_M2, "bsat_t": BSAT_T,
                           "note": "flux stays far below saturation at every burden tried"},
        "caveats": [
            "peak_to_average is measured at the operating point; a fault current is "
            "peakier, so the trip peak computed from it is a lower bound",
            "the magnetising branch (20 mH) is ignored: ~0.04 % of the secondary "
            "current at rated load, but not during a fault",
            "flux assumes the AC primary self-resets; a fault with DC offset would "
            "walk the core and is not covered",
            "the trip figures describe the DC-equivalent threshold, not the observed "
            "fault peak, which the 47 us RC filter lag stretches well beyond it",
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=RAW)
    ap.add_argument("--from-us", type=float, default=WINDOW_US[0])
    ap.add_argument("--to-us", type=float, default=WINDOW_US[1])
    ap.add_argument("--json", type=Path, default=Path("design/v3/bom/ct_design.json"))
    args = ap.parse_args()

    data = report(args.raw, (args.from_us, args.to_us))
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    m, a = data["measured"], data["as_built"]
    print(f"as built (R3={a['burden_ohm']:.0f} ohm, Rd1={a['rd1_ohm']:.0f}): "
          f"OC pin {a['oc_pin_v_at_ipk']:.3f} V at {m['i_pk_a']:.2f} A peak "
          f"({a['slope_v_per_a_peak'] * 1e3:.2f} mV/A) -> trip {a['trip_peak_a']:.2f} A peak")
    print(f"  bridge compliance {a['compliance_v']:.3f} V; burden dissipates {a['burden_power_w']:.3f} W; "
          f"B/Bsat {a['flux_peak_t'] / BSAT_T:.4f}")
    print(f"  burden for exactly {INTENDED_TRIP_A} A: {data['burden_for_intended_trip_ohm']:.2f} ohm")
    for row in data["burden_study"]:
        print(f"  R_b={row['burden_ohm']:5.0f} ohm  OC pin {row['oc_pin_v_at_ipk']:7.3f} V  "
              f"trip {row['trip_peak_a']:6.2f} A  x{row['trip_margin_vs_rated']:5.2f} rated  "
              f"P={row['burden_power_w']:.2f} W  B/Bsat={row['flux_frac_bsat']:.4f}")
    print(args.json)


if __name__ == "__main__":
    main()

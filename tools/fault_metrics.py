"""Fault-response metrics for the CT-sensed cold-start decks.

SIMULATION ONLY - surrogate models, not hardware validation.  Reads a raw file
and reports the quantities the 2026-10-31 review asked for, all measured from
the actual fault-engagement instant (not a rounded 4 ms):

  * fault engagement (PWL crossing of the switch threshold)
  * OC trip instant and delay from engagement
  * peak |I(Lr)| after engagement
  * first sustained primary-drive stop after the trip
  * number of gate restarts after that stop
  * cumulative I^2*t from engagement to trip and to the end of the record
  * minimum and final output voltage (recovery state)

Usage: python tools/fault_metrics.py startup_ct_fault [startup_ct_fault_10m ...]
       python tools/fault_metrics.py --fault-start-ms 5.5 --fault-end-ms 5.6 \
           --gate V(ga1) cold_oc
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PyLTSpice import RawRead

from ascii_raw_window import read_window


ROOT = Path(__file__).resolve().parents[1]
F_FAULT = 3.9e-3
PWL_END = 4.0e-3
PWL_TOP = 5.0
VT_SWITCH = 2.5
VOC_TRIP = 1.0
GATE_ON = 2.0
GATE_OFF = 1.0
# A normal 200 kHz gate-low half-period is ~2.5 us.  A low run this long is a
# controller shutdown, not PWM, so it separates restart bursts from switching.
SUSTAINED_LOW_S = 10e-6


def engage_time(f_fault: float, pwl_end: float) -> float:
    """Instant the 0..5 V PWL ramp crosses the 2.5 V switch threshold."""
    return f_fault + (VT_SWITCH / PWL_TOP) * (pwl_end - f_fault)


def load_traces(name: str, wanted: list[str],
                t_from: float | None = None) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Return time and only the requested traces from sim/v2/<name>.raw.

    t_from switches to the streaming ASCII window reader: a run stopped before
    its last point leaves "No. Points: 0" in the header, which PyLTSpice
    rejects, and a 13 GB raw is expensive to load anyway.
    """
    path = ROOT / "sim" / "v2" / f"{name}.raw"
    if t_from is not None:
        return read_window(path, wanted, t_from)
    raw = RawRead(str(path))
    t = np.asarray(raw.get_trace("time").get_wave(0))
    traces = {tr: np.asarray(raw.get_trace(tr).get_wave(0)) for tr in wanted}
    return t, traces


def first_up(t: np.ndarray, y: np.ndarray, level: float, after: float) -> float | None:
    idx = np.where((t > after) & (y >= level))[0]
    return float(t[idx[0]]) if idx.size else None


def low_runs(t: np.ndarray, y: np.ndarray, level: float, after: float) -> list[tuple[float, float, bool]]:
    """(start, end, open_ended) of every continuous y<level run after `after`."""
    m = t > after
    tt, yy = t[m], y[m]
    low = yy < level
    d = np.diff(np.concatenate(([0], low.astype(int), [0])))
    starts, ends = np.where(d == 1)[0], np.where(d == -1)[0]
    runs = [(float(tt[s]), float(tt[e - 1]), False) for s, e in zip(starts, ends)]
    if low.size and low[-1]:
        runs[-1] = (runs[-1][0], float(tt[-1]), True)
    return runs


def integrate(t: np.ndarray, y: np.ndarray, lo: float, hi: float) -> float:
    m = (t >= lo) & (t <= hi)
    return float(np.trapezoid(y[m], t[m])) if m.sum() > 1 else 0.0


def analyze(name: str, f_fault: float = F_FAULT, pwl_end: float = PWL_END,
            gate: str = "V(gd1)", t_from: float | None = None) -> dict[str, float | str | None]:
    t, tr = load_traces(name, ["V(oc)", "I(Lr)", gate, "V(out)"], t_from)
    v_oc, i_lr, v_gate = tr["V(oc)"], np.abs(tr["I(Lr)"]), tr[gate]
    v_out = tr["V(out)"]

    t_engage = engage_time(f_fault, pwl_end)
    t_trip = first_up(t, v_oc, VOC_TRIP, t_engage)
    m_after = t >= t_engage
    i_peak = float(i_lr[m_after].max()) if m_after.any() else 0.0
    t_peak = float(t[m_after][int(np.argmax(i_lr[m_after]))]) if m_after.any() else None

    runs = low_runs(t, v_gate, GATE_OFF, t_trip if t_trip is not None else t_engage)
    shutdowns = [(s, e, op) for s, e, op in runs if e - s >= SUSTAINED_LOW_S]
    first_stop = shutdowns[0][0] if shutdowns else None
    restarts = [e for _, e, op in shutdowns if not op]
    last_high = float(t[m_after][v_gate[m_after] >= GATE_ON].max()) if (m_after & (v_gate >= GATE_ON)).any() else None
    m_tail_out = t >= (t[-1] - 2e-4)

    return {
        "deck": name,
        "fault_engage_ms": t_engage * 1e3,
        "oc_trip_ms": None if t_trip is None else t_trip * 1e3,
        "fault_to_trip_us": None if t_trip is None else (t_trip - t_engage) * 1e6,
        "peak_primary_A": i_peak,
        "peak_time_ms": None if t_peak is None else t_peak * 1e3,
        "first_sustained_drive_stop_ms": None if first_stop is None else first_stop * 1e3,
        "max_continuous_drive_low_us": round(max((e - s for s, e, _ in shutdowns), default=0.0) * 1e6, 2),
        "shutdown_intervals_ms": [[round(s * 1e3, 4), round(e * 1e3, 4), op] for s, e, op in shutdowns[:8]],
        "gate_restart_bursts": len(restarts),
        "last_gate_high_after_fault_ms": None if last_high is None else last_high * 1e3,
        "i2t_to_trip_mA2s": integrate(t, i_lr**2, t_engage, t_trip) * 1e3 if t_trip else None,
        "i2t_to_end_mA2s": integrate(t, i_lr**2, t_engage, t[-1]) * 1e3,
        "vout_min_V": float(v_out[m_after].min()) if m_after.any() else None,
        "vout_end_V": float(v_out[-1]),
        "vout_tail_avg_V": float(v_out[m_tail_out].mean()) if m_tail_out.any() else None,
        "recovered": bool(v_out[m_tail_out].mean() > 1.0) if m_tail_out.any() else False,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*", default=["startup_ct_fault", "startup_ct_fault_10m"])
    ap.add_argument("--fault-start-ms", type=float, default=F_FAULT * 1e3)
    ap.add_argument("--fault-end-ms", type=float, default=PWL_END * 1e3)
    ap.add_argument("--gate", default="V(gd1)", help="gate trace used to find restart bursts")
    ap.add_argument("--ascii-window-from-ms", type=float, default=None,
                    help="stream the raw from this time instead of a full PyLTSpice load")
    args = ap.parse_args()
    out_dir = ROOT / "design" / "v2"
    t_from = None if args.ascii_window_from_ms is None else args.ascii_window_from_ms * 1e-3
    for name in args.names:
        result = analyze(name, args.fault_start_ms * 1e-3, args.fault_end_ms * 1e-3, args.gate, t_from)
        (out_dir / f"fault_metrics_{name}.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

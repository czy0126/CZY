"""Quantify the current-transformer OC fault response from the LTspice RAW file.

SIMULATION ONLY - surrogate models, not hardware validation.  Reads
sim/v2/startup_ct_fault.raw and prints the numbers needed for the ECO:

  * when the switched overload actually engages (PWL crossing of Vt)
  * the CT-filtered OC trip instant and the delay from fault to trip
  * when the primary gates are pulled low and how long they stay low
  * the peak |I(Lr)| and the I^2*t seen by the primary before the trip acts
  * whether the controller latches (>2 V) or hiccups (0.6-1.0 V band)

Usage:  python tools/fault_probe.py [deck_name]
"""

from pathlib import Path

import numpy as np
from PyLTSpice import RawRead

ROOT = Path(__file__).resolve().parents[1]
VOC_TRIP = 1.0
F_FAULT = 3.9e-3
VT_SWITCH = 2.5
PWL_TOP = 5.0


def load(name: str) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Return the time vector and a dict of every saved trace."""
    raw = RawRead(str(ROOT / "sim" / "v2" / f"{name}.raw"))
    t = np.asarray(raw.get_trace("time").get_wave(0))
    traces = {tr: np.asarray(raw.get_trace(tr).get_wave(0)) for tr in raw.get_trace_names() if tr != "time"}
    return t, traces


def fault_engage_time() -> float:
    """PWL(3.9m->4.0m, 0->5 V) crosses Vt=2.5 V exactly halfway."""
    return F_FAULT + (VT_SWITCH / PWL_TOP) * (4.0e-3 - F_FAULT)


def first_cross(t: np.ndarray, y: np.ndarray, level: float, after: float = 0.0) -> float | None:
    """First time y rises through level strictly after time `after`."""
    idx = np.where((t > after) & (y >= level))[0]
    return float(t[idx[0]]) if idx.size else None


def window(t: np.ndarray, y: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """Return y restricted to [lo, hi]."""
    return y[(t >= lo) & (t <= hi)]


def crossings(t: np.ndarray, y: np.ndarray, level: float, lo: float, hi: float) -> np.ndarray:
    """Indices where y crosses up through level inside [lo, hi]."""
    m = (t >= lo) & (t <= hi)
    above = y >= level
    up = np.where(m[:-1] & ~above[:-1] & above[1:])[0] + 1
    return t[up]


def main() -> None:
    import sys

    name = sys.argv[1] if len(sys.argv) > 1 else "startup_ct_fault"
    t, tr = load(name)
    v_oc = tr["V(oc)"]
    v_gd1 = tr["V(gd1)"]
    i_lr = np.abs(tr["I(Lr)"])
    i_sec = np.abs(tr["I(Lct2)"])
    t_on = fault_engage_time()

    t_trip = first_cross(t, v_oc, VOC_TRIP, F_FAULT)
    low = np.where((t > (t_trip or t_on)) & (v_gd1 < 1.0))[0]
    t_gate_low = float(t[low[0]]) if low.size else None

    m_pre = (t >= t_on) & (t <= (t_trip or 4e-3))
    i2t = float(np.trapezoid(i_lr[m_pre] ** 2, t[m_pre]))
    dt = np.diff(t, prepend=t[0])
    above = {level: dt[(t >= t_on) & (i_lr >= level)].sum() for level in (30.0, 50.0, 60.0)}

    retries = crossings(t, v_oc, VOC_TRIP, (t_trip or 4e-3), t[-1])

    print(f"deck                : {name}")
    print(f"fault engages (Vt)  : {t_on * 1e3:.4f} ms")
    print(f"OC trip (V(oc)=1 V) : {t_trip * 1e3:.4f} ms" if t_trip else "OC trip            : none")
    if t_trip:
        print(f"  fault -> trip     : {(t_trip - t_on) * 1e6:.1f} us")
    print(f"primary gate low at : {t_gate_low * 1e3:.4f} ms" if t_gate_low else "primary gate low   : never")
    if t_gate_low and t_trip:
        print(f"  trip -> gate low  : {(t_gate_low - t_trip) * 1e6:.1f} us")
    print(f"peak |I(Lr)|        : {i_lr.max():.2f} A at {t[int(np.argmax(i_lr))] * 1e3:.4f} ms")
    if t_trip:
        i_at_trip = float(np.interp(t_trip, t, i_lr))
        m_per = (t >= t_trip - 5e-6) & (t <= t_trip)
        i_avg = float(np.trapezoid(i_lr[m_per], t[m_per]) / (t[m_per][-1] - t[m_per][0]))
        print(f"|I(Lr)| at trip   : {i_at_trip:.2f} A momentary, {i_avg:.2f} A cycle-mean")
        print(f"  V(oc1) at trip  : {float(np.interp(t_trip, t, tr['V(oc1)'])):.3f} V -> "
              f"{float(np.interp(t_trip, t, tr['V(oc1)'])) / i_avg * 1e3:.3f} mV per amp of mean current")
    print(f"peak |I(Lct2)|      : {i_sec.max():.4f} A (x100 = {i_sec.max() * 100:.2f} A primary)")
    print(f"integral I^2 dt     : {i2t * 1e3:.3f} mA^2 s over fault-to-trip (6.2 mOhm -> {i2t * 6.2e-3 * 1e3:.2f} mJ)")
    print("time above          : " + ", ".join(f"{lv:.0f} A {d * 1e6:.1f} us" for lv, d in above.items()))
    print(f"V(oc) peak          : {v_oc.max():.3f} V  -> {'LATCH' if v_oc.max() > 2 else 'hiccup band'}")
    print(f"OC trips in record  : {len(retries)} at " + ", ".join(f"{x * 1e3:.4f}" for x in retries[:8]) + " ms")
    span = t[-1] - (retries[0] if len(retries) else t_on)
    v_out_tail = window(t, tr["V(out)"], t[-1] - 2e-4, t[-1])
    print(f"record after first  : {span * 1e3:.3f} ms, output {v_out_tail.mean():.3f} V")


if __name__ == "__main__":
    main()

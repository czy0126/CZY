"""Per-period metrics for the joint SR tank bench (sim/v2/sr_tank_dual*.raw).

The deck saves a handful of waveforms instead of building integrator nodes, so
charge and energy are integrated here over exactly one switching period that is
detected from the gate edges rather than assumed to be 5 us.  That keeps the
window honest: the UCC25600 behaviour block sets the period, not this script.

Sign conventions, measured on sim/v2/startup_ct.raw (rectifier group a1):
    I(VSa1) < 0   rectifying  (current flows ground -> SR -> winding)
                  V(a1) = I * RdsOn < 0 as well
    I(VSa1) > 0   reverse     (current keeps flowing from the winding back into
                  the ground rail while the channel is still on)
    V(a1)         is VDS (drain a1, source sgnd = 0 V reference)

NAMING RULE (review 2026-10-31 round 2, P1)
    Every quantity that starts with ``e_port_`` / ``q_port_`` is measured at the
    two external terminals (V(a1), I(VSa1)) and is therefore a PROXY: it lumps
    channel, body diode, Cds/Cgd/Cgs, and the package inductors together.
    Gate-state masks only split that proxy by which gate was high; they are not
    internal branch losses.  Internal branch energies are measured separately by
    tools/sr_energy_ledger.py from the saved device internals.
    In particular the old ``EBD`` / ``ECH`` names are gone: they invited reading
    a gate-voltage classification as diode conduction and channel conduction.

    q_port_a_gateoff_nc  reverse charge that enters the port while V(ga1) < GATE_ON
    q_port_a_gateon_nc   reverse charge that enters the port while V(ga1) > GATE_ON
    (same for b, each channel classified by its OWN gate -- the round-2 P1)

Overlap is split by gate state, because both channels carrying forward current
means one of two very different things and the sum hides which:
    qovl_on     both gates above GATE_ON  -> conduction overlap; a fault
    qovl_off    both gates below GATE_ON  -> dead-time freewheel through the two
                                             body diodes; the normal path here
    qovl_mixed  one gate on, one off      -> handover
On the measured bench qovl_on is 0 and qovl_off/qovl_mixed carry all of it, so a
gate-voltage-only "shoot-through" test would have called normal commutation a
fault, and a current-only one calls the freewheel a fault.  Both are needed.

The tank beats: per-period reverse charge moves by tens of percent cycle to
cycle, so every metric is averaged over --periods complete periods (default 8)
and reported with its min..max spread.  A per-period peak is still not a stress
number: --span reports the maximum over the whole requested window, which is
always >= the mean of the per-period peaks.

Usage:
    python tools/tank_metrics.py sim/v2/sr_tank_dual_v33.raw
    python tools/tank_metrics.py sim/v2/sr_tank_dual_v33.raw --pair 2 --periods 20
    python tools/tank_metrics.py sim/v2/sr_tank_dual_v33.raw --span 450u 500u
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PyLTSpice import RawRead

GATE_ON = 2.0
# A real gate can cross the decision level twice within a few ns (measured: 3.8 ns
# on sr_tank_dual.raw).  Two crossings that close together are one switching edge;
# counting both injects a ~4 ns "period" into any average.
EDGE_DEBOUNCE = 100e-9


def load(path: Path) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Return (time array, {trace name: values}) from an LTspice raw file."""
    raw = RawRead(str(path))
    names = raw.get_trace_names()
    data = {name: np.asarray(raw.get_trace(name)) for name in names}
    return data["time"], data


def edges(t: np.ndarray, v: np.ndarray, level: float = GATE_ON, debounce: float = EDGE_DEBOUNCE) -> np.ndarray:
    """Times where v crosses `level` ascending, with glitches inside `debounce` merged.

    A cluster of crossings closer than `debounce` is one edge; the LAST member is
    kept, because that is the crossing at which the gate actually stayed high.
    """
    above = v > level
    rises = t[1:][above[1:] & ~above[:-1]]
    if len(rises) < 2:
        return rises
    keep = [float(rises[0])]
    for rise in rises[1:]:
        if rise - keep[-1] < debounce:
            keep[-1] = float(rise)
        else:
            keep.append(float(rise))
    return np.array(keep)


def period_and_window(t: np.ndarray, v_gate: np.ndarray) -> tuple[float, float, float]:
    """Return (period, t0, t1) for the last complete switching period."""
    rises = edges(t, v_gate)
    if len(rises) < 3:
        raise SystemExit("not enough gate edges to detect a period")
    period = float(np.mean(np.diff(rises[-4:])))
    t1 = float(rises[-1])
    return period, t1 - period, t1


def periods(t: np.ndarray, v_gate: np.ndarray, count: int) -> list[tuple[float, float]]:
    """The last `count` complete switching periods, as (t0, t1) pairs."""
    rises = edges(t, v_gate)
    if len(rises) < count + 1:
        raise SystemExit(f"need {count + 1} gate edges for {count} periods, found {len(rises)}")
    return [(float(a), float(b)) for a, b in zip(rises[-count - 1 : -1], rises[-count:])]


def average_metrics(runs: list[dict[str, float]]) -> dict[str, float]:
    """Mean of each metric across periods, plus the min/max spread.

    On this bench the tank beats: the reverse-charge per period moves by tens of
    percent cycle to cycle, so quoting one period would be quoting an accident.
    The mean is NOT a stress number; the max over the whole span is reported by
    the caller as well (see `span_extremes`).
    """
    keys = [key for key in runs[0] if not key.endswith(("_min", "_max", "_spread_pct"))]
    out: dict[str, float] = {}
    for key in keys:
        values = np.array([run[key] for run in runs], dtype=float)
        mean = float(values.mean())
        out[key] = mean
        out[f"{key}_min"] = float(values.min())
        out[f"{key}_max"] = float(values.max())
        out[f"{key}_spread_pct"] = 100.0 * float(values.max() - values.min()) / abs(mean) if mean else float("nan")
    return out


def integrate(t: np.ndarray, *signals: np.ndarray) -> float:
    """Trapezoid integral of the product of the given signals over t."""
    value = np.ones_like(t)
    for signal in signals:
        value = value * signal
    return float(np.trapezoid(value, t))


def time_average(t: np.ndarray, signal: np.ndarray) -> float:
    """Time-weighted mean of `signal` over the samples in t.

    A raw file is sampled non-uniformly, so a plain np.mean weights whatever the
    solver happened to resolve (fast edges get more samples) instead of time.
    The round-2 review caught this on Vout: the sample mean and the time average
    differ at the millivolt level near a switching edge.
    """
    span = float(t[-1] - t[0])
    if span <= 0.0:
        return float("nan")
    return integrate(t, signal) / span


def window(t: np.ndarray, t0: float, t1: float) -> slice:
    return slice(int(np.searchsorted(t, t0)), int(np.searchsorted(t, t1)))


def crossing(t: np.ndarray, i: np.ndarray) -> tuple[float, float]:
    """First negative->positive zero crossing: (time, dI/dt there).

    On this bench rectifying current is negative, so this is the instant the
    reverse current starts -- the turn-off anchor the timing model acts on.
    """
    neg = i < 0
    idx = np.flatnonzero(neg[:-1] & ~neg[1:])
    if not len(idx):
        return float("nan"), float("nan")
    k = int(idx[0]) + 1
    t0, t1 = t[k - 1], t[k]
    slope = (i[k] - i[k - 1]) / (t1 - t0)
    frac = i[k - 1] / (i[k - 1] - i[k])
    return float(t0 + frac * (t1 - t0)), float(slope)


def pair_metrics(t: np.ndarray, data: dict[str, np.ndarray], pair: int, t0: float, t1: float) -> dict[str, float]:
    """Port charges/energies for one rectifier pair over [t0, t1].

    Each channel is classified by its OWN gate.  The round-2 review found the
    previous version used `ga_on | gb_on` for channel a, so a "B on, A off"
    instant was booked as channel-a conduction even though A was off.
    """
    w = window(t, t0, t1)
    tw = t[w]
    vds = data[f"V(a{pair})"][w]  # source is sgnd, and the deck ties Vref sgnd 0 0
    vds_b = data[f"V(b{pair})"][w]
    ia = data[f"I(VSa{pair})"][w]
    ib = data[f"I(VSb{pair})"][w]
    ga = data[f"V(ga{pair})"][w]
    gb = data[f"V(gb{pair})"][w]
    ga_on, gb_on = ga > GATE_ON, gb > GATE_ON
    ga_off, gb_off = ~ga_on, ~gb_on
    fwd_a, fwd_b = np.maximum(-ia, 0.0), np.maximum(-ib, 0.0)
    rev_a, rev_b = np.maximum(ia, 0.0), np.maximum(ib, 0.0)
    overlap = np.minimum(fwd_a, fwd_b)
    ovl_mask = (overlap > 0.0).astype(float)
    # Both channels forward at once means only one of two things, and they must not
    # be added together: both gates ON is a conduction overlap (the fault the
    # interlock exists to prevent); both gates OFF is the dead-time freewheel path
    # through the two body diodes, which this topology uses on every cycle.
    both_on = (ga_on & gb_on).astype(float) * ovl_mask
    both_off = (ga_off & gb_off).astype(float) * ovl_mask
    mixed = ovl_mask - both_on - both_off
    e_ovl = vds * ia + vds_b * ib
    p_a = vds * ia
    p_b = vds_b * ib
    return {
        "q_port_a_fwd_nc": 1e9 * integrate(tw, fwd_a),
        "q_port_a_rev_nc": 1e9 * integrate(tw, rev_a),
        "q_port_b_fwd_nc": 1e9 * integrate(tw, fwd_b),
        "q_port_b_rev_nc": 1e9 * integrate(tw, rev_b),
        # reverse charge split by the channel's own gate: a comparison index, not
        # proof that the charge went through the body diode (Cds/Cgd also carry it)
        "q_port_a_rev_gateon_nc": 1e9 * integrate(tw, rev_a, ga_on.astype(float)),
        "q_port_a_rev_gateoff_nc": 1e9 * integrate(tw, rev_a, ga_off.astype(float)),
        "q_port_b_rev_gateon_nc": 1e9 * integrate(tw, rev_b, gb_on.astype(float)),
        "q_port_b_rev_gateoff_nc": 1e9 * integrate(tw, rev_b, gb_off.astype(float)),
        "qovl_nc": 1e9 * integrate(tw, overlap),
        "qovl_on_nc": 1e9 * integrate(tw, overlap, both_on),
        "qovl_off_nc": 1e9 * integrate(tw, overlap, both_off),
        "qovl_mixed_nc": 1e9 * integrate(tw, overlap, mixed),
        # port energies classified by each channel's OWN gate (proxy, see header)
        "e_port_a_off_uj": 1e6 * integrate(tw, p_a, ga_off.astype(float)),
        "e_port_a_on_uj": 1e6 * integrate(tw, p_a, ga_on.astype(float)),
        "e_port_a_total_uj": 1e6 * integrate(tw, p_a),
        "e_port_b_off_uj": 1e6 * integrate(tw, p_b, gb_off.astype(float)),
        "e_port_b_on_uj": 1e6 * integrate(tw, p_b, gb_on.astype(float)),
        "e_port_b_total_uj": 1e6 * integrate(tw, p_b),
        "eovl_uj": 1e6 * integrate(tw, e_ovl, ovl_mask),
        "eovl_on_uj": 1e6 * integrate(tw, e_ovl, both_on),
        "eovl_off_uj": 1e6 * integrate(tw, e_ovl, both_off),
        "vds_a_min_v": float(vds.min()),
        "vds_a_max_v": float(vds.max()),
        "vds_b_min_v": float(vds_b.min()),
        "vds_b_max_v": float(vds_b.max()),
        "irev_a_pk_a": float(ia.max()),
        "ifwd_a_pk_a": float((-ia).max()),
        "irev_b_pk_a": float(ib.max()),
        "ifwd_b_pk_a": float((-ib).max()),
        "ovl_pk_a": float(overlap.max()),
    }


def span_extremes(t: np.ndarray, data: dict[str, np.ndarray], pair: int, t0: float, t1: float) -> dict[str, float]:
    """True maxima/minima over the whole window, not the mean of per-period peaks.

    The round-2 review: the headline "5.135 A" was the mean of eight per-period
    peaks; the largest sample in that same eight-period window was 5.18856 A and
    the largest in 450-500 us was 5.41201 A.  A rating or stress claim must use
    the peak in the declared window.
    """
    w = window(t, t0, t1)
    tw = t[w]
    vds = data[f"V(a{pair})"][w]
    vds_b = data[f"V(b{pair})"][w]
    ia = data[f"I(VSa{pair})"][w]
    ib = data[f"I(VSb{pair})"][w]
    vout = data["V(out)"][w]
    return {
        "span_start_us": float(tw[0]) * 1e6,
        "span_end_us": float(tw[-1]) * 1e6,
        "span_irev_a_max_a": float(ia.max()),
        "span_irev_b_max_a": float(ib.max()),
        "span_ifwd_a_max_a": float((-ia).max()),
        "span_ifwd_b_max_a": float((-ib).max()),
        "span_vds_a_min_v": float(vds.min()),
        "span_vds_a_max_v": float(vds.max()),
        "span_vds_b_min_v": float(vds_b.min()),
        "span_vds_b_max_v": float(vds_b.max()),
        "span_vout_time_avg_v": time_average(tw, vout),
        "span_vout_pp_v": float(np.ptp(vout)),
    }


def parse_us(value: str) -> float:
    """Parse a microsecond value, accepting the trailing 'u' used in the docs."""
    return float(value.rstrip("uU")) * 1e-6


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("raw", type=Path)
    ap.add_argument("--pair", type=int, default=1, help="which rectifier pair (1..4)")
    ap.add_argument("--periods", type=int, default=8, help="periods to average over (the tank beats)")
    ap.add_argument("--span", nargs=2, type=parse_us, metavar=("START_US", "END_US"),
                    help="wider window for true extremes, e.g. --span 450u 500u; default = the period window")
    args = ap.parse_args()

    t, data = load(args.raw)
    gate = data[f"V(ga{args.pair})"]
    windows = periods(t, gate, args.periods)
    runs = [pair_metrics(t, data, args.pair, t0, t1) for t0, t1 in windows]
    metrics = average_metrics(runs)
    span0, span1 = (args.span if args.span else (windows[0][0], windows[-1][1]))
    extremes = span_extremes(t, data, args.pair, span0, span1)

    print(f"{args.raw}  pair {args.pair}  over {args.periods} periods")
    print(f"period window {windows[0][0] * 1e6:.4f} .. {windows[-1][1] * 1e6:.4f} us")
    print(f"span window   {extremes['span_start_us']:.4f} .. {extremes['span_end_us']:.4f} us")
    lengths = np.array([t1 - t0 for t0, t1 in windows])
    print(f"period {lengths.mean() * 1e6:.4f} us  ({lengths.min() * 1e6:.4f} .. {lengths.max() * 1e6:.4f})  "
          f"f {1e-3 / lengths.mean():.1f} kHz")
    whole = window(t, windows[0][0], windows[-1][1])
    print(f"Vout time-avg over period window {time_average(t[whole], data['V(out)'][whole]):.6f} V  "
          f"ripple {np.ptp(data['V(out)'][whole]) * 1e3:.3f} mV")
    print("  --- per-period mean [min .. max] ---")
    for key in (key for key in metrics if not key.endswith(("_min", "_max", "_spread_pct"))):
        unit = key.rsplit("_", 1)[-1]
        print(f"  {key:<26} {metrics[key]:>12.6g} {unit:<3}"
              f"  [{metrics[key + '_min']:.6g} .. {metrics[key + '_max']:.6g}]")
    print(f"  --- true extremes over the {extremes['span_start_us']:.3f}..{extremes['span_end_us']:.3f} us span ---")
    for key, value in extremes.items():
        if key in ("span_start_us", "span_end_us"):
            continue
        print(f"  {key:<26} {value:>12.6g}")
    for t0, t1 in windows:
        w = window(t, t0, t1)
        tc, slope = crossing(t[w], data[f"I(VSa{args.pair})"][w])
        print(f"    {t0 * 1e6:8.3f} us  crossing {tc * 1e6:8.4f} us  dI/dt {slope / 1e9:7.4f} A/ns")


if __name__ == "__main__":
    main()

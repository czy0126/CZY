"""Window-by-window convergence check for a tank bench raw file.

The round-2 review (P1) rejected reading a single 500 us soft-start window as a
steady-state result.  This tool makes the check explicit: split the saved trace
into consecutive windows and report, per window,

    switching frequency          (from RISE edges, not assumed)
    Vout time-weighted average   (trapezoid, not sample mean)
    Vout peak-to-peak
    reverse charge / peak        (per period, mean and window max)
    forward charge               (per period)
    per-group sharing            (average output current, RMS, port power and
                                  winding volt-seconds for every saved group;
                                  the pair-4/pair-1 Qrev ratio is kept only as a
                                  reverse-commutation index, not as sharing)

A point is "converged" only if the last two windows agree within the tolerances
passed on the command line (default: frequency 0.5 %, Vout 0.1 %, Qrev 3 %,
group-share drift 1 %).  Cold start and steady-state initialisation must be
separate runs; this tool says whether a run has settled, not which run it is.

Usage:
    python tools/steady_state_check.py sim/v2/sr_tank_dual_v33_ss.raw --windows 6 --t-offset-us 400
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from tank_metrics import edges, integrate, load, time_average, window


def periods_in(t: np.ndarray, gate: np.ndarray, t0: float, t1: float) -> list[tuple[float, float]]:
    """Gate-to-gate periods fully inside [t0, t1]."""
    rises = np.array([r for r in edges(t, gate) if t0 <= r <= t1])
    return [(float(a), float(b)) for a, b in zip(rises[:-1], rises[1:])]


def window_summary(t: np.ndarray, data: dict[str, np.ndarray], pair: int, t0: float, t1: float) -> dict[str, float]:
    """One window's frequency, output and per-group rectifier quantities.

    The round-3 review rejected calling the pair-4 / pair-1 reverse-charge ratio
    "current sharing": equal Qrev says the two channels commutate alike, not that
    they deliver equal average current.  This function therefore reports, for
    every instrumented group n (1..4),

        iout_g{n}_a        time-averaged current delivered to the output
        irms_g{n}_a        RMS winding/SR current
        p_port_g{n}_w      port power V(a_n)*I(VSa_n) (proxy, includes reactives)
        flux_g{n}_vs       winding volt-seconds per period, integral of
                           V(out)-V(a_n) (the Lsa_n winding voltage)

    plus their spread.  A symmetric model reports a tiny spread; that is a
    model-symmetry result, not tolerance robustness.
    """
    gate = data[f"V(ga{pair})"]
    wins = periods_in(t, gate, t0, t1)
    if not wins:
        raise SystemExit(f"no complete gate periods in {t0:.6g}..{t1:.6g}")
    lengths = np.array([b - a for a, b in wins])
    freq = 1.0 / float(lengths.mean())
    w = window(t, t0, t1)
    tw, vout = t[w], data["V(out)"][w]
    vds, ia = data[f"V(a{pair})"][w], data[f"I(VSa{pair})"][w]
    periods = [window(t, a, b) for a, b in wins]
    qrev = np.array([1e9 * integrate(t[p], np.maximum(data[f"I(VSa{pair})"][p], 0.0)) for p in periods])
    qfwd = np.array([1e9 * integrate(t[p], np.maximum(-data[f"I(VSa{pair})"][p], 0.0)) for p in periods])
    out = {
        "t0_us": t0 * 1e6,
        "t1_us": t1 * 1e6,
        "periods": float(len(wins)),
        "period_us": float(lengths.mean() * 1e6),
        "period_spread_pct": 100.0 * float(lengths.max() - lengths.min()) / float(lengths.mean()),
        "freq_khz": freq / 1e3,
        "vout_time_avg_v": time_average(tw, vout),
        "vout_pp_mv": float(np.ptp(vout) * 1e3),
        "qvrev_mean_nc": float(qrev.mean()),
        "qvrev_spread_pct": 100.0 * float(qrev.max() - qrev.min()) / float(qrev.mean())
        if qrev.mean() else float("nan"),
        "qvfwd_mean_nc": float(qfwd.mean()),
        "qvfwd_spread_pct": 100.0 * float(qfwd.max() - qfwd.min()) / float(qfwd.mean())
        if qfwd.mean() else float("nan"),
        "irev_span_max_a": float(ia.max()),
        "ifwd_span_max_a": float((-ia).max()),
        "vds_span_min_v": float(vds.min()),
        "vds_span_max_v": float(vds.max()),
    }

    groups = [n for n in (1, 2, 3, 4) if f"I(VSa{n})" in data and f"V(a{n})" in data]
    iouts: list[float] = []
    for n in groups:
        ia_n = data[f"I(VSa{n})"][w]
        va_n = data[f"V(a{n})"][w]
        if f"I(VSb{n})" in data and f"V(b{n})" in data:
            # A rectifier group is a PAIR: its output current is the sum of the
            # two devices, not just the 'a' device.  Ignoring 'b' halves the
            # reported total (94.6 A load looked like 47.6 A on the first try).
            ib_n = data[f"I(VSb{n})"][w]
            vb_n = data[f"V(b{n})"][w]
            iout = time_average(tw, -(ia_n + ib_n))
            irms = float(np.sqrt(max(time_average(tw, (ia_n + ib_n) * (ia_n + ib_n)), 0.0)))
            p_port = time_average(tw, va_n * ia_n + vb_n * ib_n)
        else:
            iout = time_average(tw, -ia_n)
            irms = float(np.sqrt(max(time_average(tw, ia_n * ia_n), 0.0)))
            p_port = time_average(tw, va_n * ia_n)
        iouts.append(iout)
        out[f"iout_g{n}_a"] = iout
        out[f"irms_g{n}_a"] = irms
        out[f"p_port_g{n}_w"] = p_port
        out[f"flux_g{n}_vs"] = integrate(tw, vout - va_n) / float(len(wins))
    if iouts:
        out["iout_sum_a"] = float(sum(iouts))
        mean = float(np.mean(iouts))
        out["iout_spread_pct"] = 100.0 * float(max(iouts) - min(iouts)) / abs(mean) if mean else float("nan")

    # Legacy, explicitly labelled: this is a REVERSE-COMMUTATION ratio, not
    # current sharing.  Kept because older raws only saved pair 1 and pair 4.
    if "I(VSa4)" in data:
        p4 = [window(t, a, b) for a, b in wins]
        q4 = np.array([1e9 * integrate(t[p], np.maximum(data["I(VSa4)"][p], 0.0)) for p in p4])
        out["qvrev_pair4_mean_nc"] = float(q4.mean())
        out["qrev_ratio_pair4_over_pair1_pct"] = (
            100.0 * float(q4.mean() / qrev.mean()) if qrev.mean() else float("nan")
        )
    return out


def relative_gap(a: float, b: float) -> float:
    return 100.0 * abs(b - a) / abs(a) if a else float("nan")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("raw", type=Path)
    ap.add_argument("--pair", type=int, default=1)
    ap.add_argument("--windows", type=int, default=6)
    ap.add_argument("--t-offset-us", type=float, default=0.0,
                    help="display offset; the internal/ss decks rebase Tstart to 0")
    ap.add_argument("--freq-tol", type=float, default=0.5)
    ap.add_argument("--vout-tol", type=float, default=0.1)
    ap.add_argument("--qrev-tol", type=float, default=3.0)
    args = ap.parse_args()

    t, data = load(args.raw)
    t_start, t_end = float(t[0]), float(t[-1])
    edges_t = np.linspace(t_start, t_end, args.windows + 1)
    rows = [window_summary(t, data, args.pair, a, b) for a, b in zip(edges_t[:-1], edges_t[1:])]
    off = args.t_offset_us

    print(f"{args.raw}  pair {args.pair}  {args.windows} windows")
    print(f"{'window (us)':>18} {'f kHz':>8} {'Vout V':>9} {'Vpp mV':>8} "
          f"{'Qrev nC':>9} {'Qrev%':>7} {'Q4/1%':>7} {'Iout A':>7} {'Ish%':>6}")
    for r in rows:
        ratio = r.get("qrev_ratio_pair4_over_pair1_pct")
        share = f"{ratio:7.3f}" if ratio is not None else "      -"
        ispread = r.get("iout_spread_pct")
        ish = f"{ispread:6.2f}" if ispread is not None else "     -"
        iout = r.get("iout_sum_a")
        iout_s = f"{iout:7.2f}" if iout is not None else "      -"
        print(f"{r['t0_us'] + off:8.2f}..{r['t1_us'] + off:8.2f} {r['freq_khz']:8.3f} "
              f"{r['vout_time_avg_v']:9.5f} {r['vout_pp_mv']:8.2f} {r['qvrev_mean_nc']:9.2f} "
              f"{r['qvrev_spread_pct']:7.2f} {share:>7} {iout_s:>7} {ish:>6}")

    last, prev = rows[-1], rows[-2]
    df = relative_gap(prev["freq_khz"], last["freq_khz"])
    dv = relative_gap(prev["vout_time_avg_v"], last["vout_time_avg_v"])
    dq = relative_gap(prev["qvrev_mean_nc"], last["qvrev_mean_nc"])
    # Sharing drift is the worst per-group change of the current SHARE
    # (iout_g / sum iout).  Using a share makes it a ratio, so it does not
    # double-count a change in total output current.  When only one group is
    # saved, there is nothing to compare and the term is 0.
    shares_last = {k: v for k, v in last.items() if k.startswith("iout_g")}
    shares_prev = {k: v for k, v in prev.items() if k.startswith("iout_g")}
    ds = 0.0
    if shares_last and shares_prev and last.get("iout_sum_a") and prev.get("iout_sum_a"):
        for key in shares_last.keys() & shares_prev.keys():
            frac_l = shares_last[key] / last["iout_sum_a"]
            frac_p = shares_prev[key] / prev["iout_sum_a"]
            ds = max(ds, relative_gap(frac_p, frac_l))
    ok = df <= args.freq_tol and dv <= args.vout_tol and dq <= args.qrev_tol and ds <= 1.0
    print(f"last-two-window gaps: f {df:.3f}% (tol {args.freq_tol}), Vout {dv:.3f}% (tol {args.vout_tol}), "
          f"Qrev {dq:.3f}% (tol {args.qrev_tol}), group-share drift {ds:.3f}% (tol 1.0)")
    print("CONVERGED" if ok else "NOT CONVERGED")


if __name__ == "__main__":
    main()

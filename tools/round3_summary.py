"""Build the single round-3 summary table from the bench raw files.

Two cases, deliberately kept apart:

    snapshot  sr_tank_dual_v33_internal.raw   284.4 kHz soft-start snapshot
    design    sr_tank_dual_v33_ss_fine.raw    200.6 kHz operating point

The output is the ONE table the round-3 delivery points at, plus a JSON copy.
It refuses to invent a design row: if a raw is missing, that case is reported as
"missing" rather than filled with the snapshot's numbers.

Usage:
    python tools/round3_summary.py \
        --snapshot sim/v2/sr_tank_dual_v33_internal.raw \
        --design sim/v2/sr_tank_dual_v33_ss_fine.raw \
        --json design/v2/round3_summary.json
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import numpy as np

from sr_energy_ledger import aggregate, ledger_period, ledger_total
from tank_metrics import (
    average_metrics,
    edges,
    integrate,
    load,
    pair_metrics,
    periods,
    span_extremes,
    time_average,
    window,
)

RL_OHM = 0.020
PAIRS = 4
DEVICES_PER_PAIR = 2
# UCC25600 RT-only law: f = 1/[2(6 ns * 1 A / I_RT + 150 ns)], I_RT = 2.5615 mA.
F_LAW_KHZ = 200.609
# Plausible full primary periods.  Shorter/half-cycle intervals are V(sw) level
# crossings that missed a transition; longer ones straddle a missed rise.
PRIMARY_LO_US = 4.5
PRIMARY_HI_US = 5.5


def primary_freq_khz(t: np.ndarray, data: dict[str, np.ndarray], gate_period_s: float | None = None,
                     band: float = 0.35, t0: float | None = None,
                     t1: float | None = None) -> float:
    """Primary switching frequency from V(sw) rise-to-rise intervals (median).

    The SR gate period jitters +-1.3 % because turn-on is a threshold event on
    the ringing drain, so the gate is not a frequency reference -- but it does
    tell us where the primary period must be, which matters because the design
    point (200.6 kHz) and the soft-start snapshot (284.4 kHz) are far apart.
    V(sw) level crossings can also alias (a missed rise looks like a double
    period, a half-cycle looks like 0.5x), so only intervals within +-band of
    the gate period are kept, and their median is returned.

    t0/t1 scope the edges to one window.  Without them the median covers the
    whole file, which is fine when the raw itself is a trimmed window (the
    round-3 operating point) but wrong for a multi-window run: the 8 ms cold
    start asked for 0.5..8 ms slices and every slice got the same
    start-up-contaminated value (248.86 kHz) while the settled gate was
    201.1 kHz.
    """
    rises = edges(t, data["V(sw)"], level=10.0)
    if t0 is not None:
        rises = rises[rises >= t0]
    if t1 is not None:
        rises = rises[rises <= t1]
    dts = np.diff(rises)
    if gate_period_s:
        lo, hi = gate_period_s * (1.0 - band), gate_period_s * (1.0 + band)
    else:
        lo, hi = PRIMARY_LO_US * 1e-6, PRIMARY_HI_US * 1e-6
    ok = dts[(dts > lo) & (dts < hi)]
    if ok.size == 0:
        return float("nan")
    return 1e-3 / float(np.median(ok))



def case(label: str, deck: str, init: str, raw: Path, pair: int, n_periods: int,
         display_offset_us: float = 0.0) -> dict[str, float | str]:
    """One row of the summary table."""
    t, data = load(raw)
    wins = periods(t, data[f"V(ga{pair})"], n_periods)
    lengths = np.array([b - a for a, b in wins])
    freq = 1.0 / float(lengths.mean())

    port = average_metrics([pair_metrics(t, data, pair, a, b) for a, b in wins])
    led = aggregate([ledger_period(t, data, pair, a, b) for a, b in wins], freq)
    total = ledger_total(t, data, pair, wins[0][0], wins[-1][1])
    span = span_extremes(t, data, pair, float(t[0]), float(t[-1]))
    w = window(t, wins[0][0], wins[-1][1])
    tw = t[w]
    vout = data["V(out)"][w]
    pout = time_average(tw, vout * vout / RL_OHM)

    p_dev = led["e_dissipated_uj_mean"] * 1e-6 * freq
    p_all = p_dev * PAIRS * DEVICES_PER_PAIR
    p_diode_cons = (led["e_bodydiode_fwd_uj_mean"] + abs(led["e_bodydiode_rev_uj_mean"])) * 1e-6 * freq

    return {
        "case": label,
        "deck": deck,
        "init": init,
        "raw": str(raw),
        "raw_time_start_s": float(t[0]),
        "raw_time_end_s": float(t[-1]),
        "display_offset_us": float(display_offset_us),
        "saved_window_us": [float(t[0]) * 1e6, float(t[-1]) * 1e6],
        "periods": float(len(wins)),
        "period_us": float(lengths.mean() * 1e6),
        "freq_khz": freq / 1e3,
        "f_primary_khz": primary_freq_khz(t, data, float(lengths.mean())),
        "f_law_khz": F_LAW_KHZ,
        "vout_time_avg_v": time_average(tw, vout),
        "vout_pp_mv": 1e3 * span["span_vout_pp_v"],
        "pout_w": pout,
        "q_port_rev_nc": port["q_port_a_rev_nc"],
        "q_port_rev_gateoff_pct": 100.0 * port["q_port_a_rev_gateoff_nc"] / port["q_port_a_rev_nc"]
        if port["q_port_a_rev_nc"] else float("nan"),
        "q_diode_rev_nc": led["q_diode_rev_nc_mean"],
        "q_channel_rev_nc": led["q_channel_rev_nc_mean"],
        "irev_span_max_a": span["span_irev_a_max_a"],
        "ifwd_span_max_a": span["span_ifwd_a_max_a"],
        "vds_span_max_v": span["span_vds_a_max_v"],
        "e_channel_uj": led["e_channel_uj_mean"],
        "e_bodydiode_uj": led["e_bodydiode_uj_mean"],
        "e_bodydiode_fwd_uj": led["e_bodydiode_fwd_uj_mean"],
        "e_bodydiode_rev_uj": led["e_bodydiode_rev_uj_mean"],
        "e_rg_uj": led["e_rg_uj_mean"],
        "e_dissipated_uj": led["e_dissipated_uj_mean"],
        "p_device_w": p_dev,
        "p_8device_w": p_all,
        "pct_of_pout": 100.0 * p_all / pout if pout else float("nan"),
        "p_diode_conservative_w": p_diode_cons,
        "gate_driver_output_w": led["e_gate_driver_output_w"],
        "residual_pct_of_port": 100.0 * total["e_residual_uj"] / abs(total["e_port_ds_uj"]),
        "period_spread_pct": 100.0 * float(lengths.max() - lengths.min()) / float(lengths.mean()),
        "qrev_spread_pct": port["q_port_a_rev_nc_spread_pct"],
        "qrev_ratio_pair4_over_pair1_pct": None,
    }


def add_sharing(row: dict, raw: Path) -> None:
    """Pair-4/pair-1 reverse-charge ratio over the same period window, if present."""
    t, data = load(raw)
    if "I(VSa4)" not in data:
        return
    wins = periods(t, data["V(ga4)"], int(row["periods"]))
    q1 = np.array([1e9 * integrate(t[window(t, a, b)],
                                   np.maximum(data["I(VSa1)"][window(t, a, b)], 0.0)) for a, b in wins])
    q4 = np.array([1e9 * integrate(t[window(t, a, b)],
                                   np.maximum(data["I(VSa4)"][window(t, a, b)], 0.0)) for a, b in wins])
    row["qrev_ratio_pair4_over_pair1_pct"] = 100.0 * float(q4.mean() / q1.mean())


def print_table(rows: list[dict]) -> None:
    print("| 案例 | f主 kHz | f门 kHz | Vout V | Pout W | Qrev nC | Qbd_rev nC | Ipk A | E_ch uJ | "
          "E_bd uJ | E_Rg uJ | P_dev mW | 8只 W | %Pout | 残差 % |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in rows:
        if row.get("status") == "missing":
            print(f"| {row['case']} | MISSING | | | | | | | | | | | | | |")
            continue
        print(f"| {row['case']} | {row['f_primary_khz']:.2f} | {row['freq_khz']:.2f} | "
              f"{row['vout_time_avg_v']:.4f} | {row['pout_w']:.1f} | "
              f"{row['q_port_rev_nc']:.1f} | {row['q_diode_rev_nc']:.1f} | {row['irev_span_max_a']:.2f} | "
              f"{row['e_channel_uj']:.4f} | {row['e_bodydiode_uj']:.4f} | {row['e_rg_uj']:.4f} | "
              f"{row['p_device_w'] * 1e3:.1f} | {row['p_8device_w']:.2f} | {row['pct_of_pout']:.2f} | "
              f"{row['residual_pct_of_port']:.3f} |")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", type=Path, required=True)
    ap.add_argument("--design", type=Path, required=True)
    ap.add_argument("--json", type=Path, required=True)
    ap.add_argument("--design-deck", default="sr_tank_dual_v33_ss_fine.cir")
    ap.add_argument("--design-periods", type=int, default=12,
                    help="even count; the SR on-time alternates and the gate period jitters")
    ap.add_argument("--snapshot-offset-us", type=float, default=0.0,
                    help="display time added to the snapshot raw's saved axis")
    ap.add_argument("--design-offset-us", type=float, default=880.0,
                    help="display time added to the design raw's saved axis (Tstart=880 us)")
    args = ap.parse_args()

    rows = []
    if args.snapshot.exists():
        row = case("软启动快照", "sr_tank_dual_v33_internal.cir",
                   "VCC 0→12 V 斜坡，SS 从 0", args.snapshot, 1, 8,
                   display_offset_us=args.snapshot_offset_us)
        add_sharing(row, args.snapshot)
        rows.append(row)
    else:
        rows.append({"case": "软启动快照", "status": "missing", "raw": str(args.snapshot)})

    if args.design.exists():
        row = case("设计点", args.design_deck,
                   "VCC=12 V 常开，.ic V(out)=1.89 V(ss)=4 V", args.design, 1, args.design_periods,
                   display_offset_us=args.design_offset_us)
        add_sharing(row, args.design)
        rows.append(row)
    else:
        rows.append({"case": "设计点", "status": "missing", "raw": str(args.design)})

    payload = {"generated": date.today().isoformat(), "rl_ohm": RL_OHM, "cases": rows}
    args.json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print_table(rows)
    print(f"wrote {args.json}")


if __name__ == "__main__":
    main()

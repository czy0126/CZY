"""Per-period spread of the SR branch loss, from the saved raws.

The third review (2026-10-31) asked whether the 6.84 W / 8-device estimate is
numerically converged.  A single mean over a hand-picked window cannot answer
that: on this bench the per-period dissipated energy itself moves by 16..23 %
(one-sigma) from cycle to cycle, so the MEAN of a window has its own standard
error, and a shorter window can shift it by several percent without any change
in timestep.

This tool measures that spread directly.  It takes every complete switching
period in the saved window, runs the branch ledger on each one, and reports the
mean, standard deviation, standard error of the mean, and min..max for:

    e_dissipated_uj   channel + body diode + Rg, one device
    e_channel_uj      channel branch
    e_bodydiode_uj    body-diode branch (negative recovery segments included)
    q_port_rev_nc     reverse port charge (tank_metrics, 2-terminal proxy)
    vout_v, pout_w    output voltage and average(Vout^2/R) over the period

Usage:
    python tools/period_variance.py \
        5n=sim/v2/sr_tank_dual_v33_ss_1ms.raw \
        2n=sim/v2/sr_tank_dual_v33_conv1ms_2n.raw \
        --json design/v2/period_variance.json
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import numpy as np

from sr_energy_ledger import ledger_period
from tank_metrics import edges, load, pair_metrics, time_average, window

RL_OHM = 0.020


def summary(values: np.ndarray) -> dict[str, float]:
    """Mean and its uncertainty for a per-period quantity."""
    values = np.asarray(values, dtype=float)
    n = int(values.size)
    if n == 0:
        return {"n": 0, "mean": float("nan"), "sd": float("nan"), "sem": float("nan")}
    mean = float(values.mean())
    sd = float(values.std(ddof=1)) if n > 1 else float("nan")
    sem = sd / np.sqrt(n) if n > 1 else float("nan")
    return {
        "n": n,
        "mean": mean,
        "sd": sd,
        "sem": float(sem),
        "rel_sd_pct": 100.0 * sd / abs(mean) if mean else float("nan"),
        "rel_sem_pct": 100.0 * sem / abs(mean) if mean else float("nan"),
        "min": float(values.min()),
        "max": float(values.max()),
    }


def complete_periods(t: np.ndarray, gate: np.ndarray) -> list[tuple[float, float]]:
    """Every complete gate period inside the saved window, 2..10 us long.

    The 2..10 us guard rejects half-cycle aliases from a missed edge; the design
    period is ~4.99 us.
    """
    rises = edges(t, gate)
    wins = [(float(a), float(b)) for a, b in zip(rises[:-1], rises[1:])]
    return [(a, b) for a, b in wins if 2e-6 < b - a < 10e-6]


def measure(raw: Path) -> dict[str, object]:
    t, data = load(raw)
    wins = complete_periods(t, data["V(ga1)"])
    freq = 1.0 / float(np.mean([b - a for a, b in wins])) if wins else float("nan")
    rows = []
    for a, b in wins:
        w = window(t, a, b)
        tw = t[w]
        led = ledger_period(t, data, 1, a, b)
        port = pair_metrics(t, data, 1, a, b)
        vout = data["V(out)"][w]
        rows.append({
            "period_us": (b - a) * 1e6,
            "e_dissipated_uj": led["e_dissipated_uj"],
            "e_channel_uj": led["e_channel_uj"],
            "e_bodydiode_uj": led["e_bodydiode_uj"],
            "e_rg_uj": led["e_rg_uj"],
            "q_port_rev_nc": port["q_port_a_rev_nc"],
            "vout_v": time_average(tw, vout),
            "pout_w": time_average(tw, vout * vout / RL_OHM),
        })
    out: dict[str, object] = {
        "raw": str(raw),
        "freq_khz": freq / 1e3,
        "periods": len(rows),
        "window_us": [wins[0][0] * 1e6, wins[-1][1] * 1e6] if wins else [],
    }
    if not rows:
        return out
    for key in ("e_dissipated_uj", "e_channel_uj", "e_bodydiode_uj", "e_rg_uj",
                "q_port_rev_nc", "vout_v", "pout_w"):
        out[key] = summary(np.array([row[key] for row in rows]))
    mean_e = out["e_dissipated_uj"]["mean"]
    # One device's mean dissipation converted to watts at the measured period.
    out["p_device_w"] = mean_e * 1e-6 * freq
    out["p_8device_w"] = out["p_device_w"] * 8
    out["p_8device_sem_w"] = out["e_dissipated_uj"]["sem"] * 1e-6 * freq * 8
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("specs", nargs="+", help="label=path.raw")
    ap.add_argument("--json", type=Path, required=True)
    args = ap.parse_args()
    payload: dict[str, object] = {"generated": date.today().isoformat(), "rl_ohm": RL_OHM,
                                  "note": "per-period spread, model numbers only"}
    for spec in args.specs:
        label, _, path = spec.partition("=")
        if path and Path(path).exists():
            payload[label] = measure(Path(path))
        else:
            payload[label] = {"status": "missing", "raw": path}
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    for label, row in payload.items():
        if not isinstance(row, dict) or "e_dissipated_uj" not in row:
            continue
        e = row["e_dissipated_uj"]
        print(f"{label:12s} n={e['n']:3d} f={row['freq_khz']:.2f} kHz "
              f"e_dis={e['mean']:.3f}+-{e['sem']:.3f} uJ (rel sd {e['rel_sd_pct']:.1f} %) "
              f"8dev={row['p_8device_w']:.2f} +- {row['p_8device_sem_w']:.2f} W")
    print(f"wrote {args.json}")


if __name__ == "__main__":
    main()

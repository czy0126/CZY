"""Round-4 / task-package-1 evidence table.

One run produces ONE JSON + one markdown table that answers the four things the
third independent review (2026-10-31) asked for, and nothing else:

  1. true cold start   -- no .ic, Cout at 0 V, sequenced VCC -> main -> REG
  2. numerical check   -- 5/2/1 ns and CPIN 50/100/200 pF at the SAME operating
                          point, SAME duration, SAME window
  3. full-machine energy -- Pin, Pout, both bias rails and every four-group
                          current on one run, so a loss allocation exists
  4. honest sharing    -- average output current / RMS / port power / winding
                          volt-seconds per group, not a reverse-charge ratio

Everything is a MODEL number.  No row in this table is a hardware measurement.

Usage:
    python tools/task_package1_summary.py \
        --op sim/v2/sr_tank_dual_v33_ss_1ms.raw \
        --full sim/v2/sr_tank_dual_v33_ss_1ms_full.raw \
        --cold sim/v2/sr_tank_dual_v33_cold.raw \
        --conv 5n=sim/v2/sr_tank_dual_v33_conv_5n.raw \
               2n=sim/v2/sr_tank_dual_v33_conv_2n.raw \
               1n=sim/v2/sr_tank_dual_v33_conv_1n.raw \
        --cpin 50p=sim/v2/sr_tank_dual_v33_cpin_50p.raw \
               100p=sim/v2/sr_tank_dual_v33_conv_2n.raw \
               200p=sim/v2/sr_tank_dual_v33_cpin_200p.raw \
        --json design/v2/round4_summary.json
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import numpy as np

from round3_summary import case, primary_freq_khz
from sr_energy_ledger import aggregate, ledger_period
from steady_state_check import window_summary
from tank_metrics import edges, load, periods, time_average, window

RL_OHM = 0.020
VIN_NOMINAL = 48.0
PAIRS = 4
DEVICES_PER_PAIR = 2
I_RT_A = 2.5 / 976.0


def f_law_khz(vss_v: float) -> float:
    """UCC25600 eq (2) frequency from the SS pin voltage, in kHz."""
    i_tot = I_RT_A + max(0.0, 1.81e-3 - vss_v / 2200.0)
    return 1e-3 / (2.0 * (6e-9 / max(i_tot, 1e-9) + 150e-9))


def op_windows(t: np.ndarray, data: dict[str, np.ndarray], n: int = 22) -> list[tuple[float, float]]:
    """The last `n` complete SR gate periods (even count: on-time alternates)."""
    return periods(t, data["V(ga1)"], n)


def power_block(t: np.ndarray, data: dict[str, np.ndarray], t0: float, t1: float) -> dict[str, float]:
    """Input, output and both bias rails over one window, time-averaged."""
    w = window(t, t0, t1)
    tw = t[w]
    vout = data["V(out)"][w]
    pout = time_average(tw, vout * vout / RL_OHM)
    out = {"pout_w_avg_vsq_r": pout}
    if "I(Vbus)" in data and "V(vin0)" in data:
        out["pin_w"] = time_average(tw, -data["V(vin0)"][w] * data["I(Vbus)"][w])
    if "I(Vaux)" in data:
        out["p_aux_w"] = time_average(tw, -data["V(aux)"][w] * data["I(Vaux)"][w])
    if "I(Vreg)" in data:
        out["p_reg_w"] = time_average(tw, -data["V(reg)"][w] * data["I(Vreg)"][w])
    bias = out.get("p_aux_w", 0.0) + out.get("p_reg_w", 0.0)
    if "pin_w" in out:
        total_in = out["pin_w"] + bias
        out["p_total_input_w"] = total_in
        out["p_total_loss_w"] = total_in - pout
        out["efficiency_pct"] = 100.0 * pout / total_in if total_in else float("nan")
    return out


def ledger_window(t: np.ndarray, data: dict[str, np.ndarray], wins: list[tuple[float, float]]) -> dict[str, float]:
    """Per-device SR branch losses and the closure residual over the window."""
    freq = 1.0 / float(np.mean([b - a for a, b in wins]))
    led = aggregate([ledger_period(t, data, 1, a, b) for a, b in wins], freq)
    p_dev = led["e_dissipated_uj_mean"] * 1e-6 * freq
    p_rg = led["e_rg_uj_mean"] * 1e-6 * freq
    return {
        "freq_khz": freq / 1e3,
        "e_channel_uj": led["e_channel_uj_mean"],
        "e_bodydiode_uj": led["e_bodydiode_uj_mean"],
        "e_rg_uj": led["e_rg_uj_mean"],
        "e_dissipated_uj": led["e_dissipated_uj_mean"],
        "p_device_w": p_dev,
        "p_8device_w": p_dev * PAIRS * DEVICES_PER_PAIR,
        # Rg heat is included in e_dissipated, but in this behavioural model it
        # is supplied by the ideal gate-driver source, NOT by VDD/REG.  The
        # machine Pin therefore does not carry it.  Keep the branch term (which
        # does come from the power path) separate so the loss allocation does
        # not subtract Rg twice or credit it to the input.
        "p_rg_8device_w": p_rg * PAIRS * DEVICES_PER_PAIR,
        "p_sr_branch_8device_w": (p_dev - p_rg) * PAIRS * DEVICES_PER_PAIR,
        "e_gate_driver_output_uj": led["e_gate_driver_output_uj_mean"],
        "p_gate_driver_output_w": led["e_gate_driver_output_uj_mean"] * 1e-6 * freq * PAIRS * DEVICES_PER_PAIR,
    }


def sr_allocation(full: dict[str, float]) -> dict[str, float]:
    """Split the measured machine loss without double-counting gate drive.

    Pin - Pout is the model's port loss.  `p_sr_branch_8device_w` is the part
    of it that flows through the SR channel and body diode; Rg and the driver
    output are fed by an ideal driver source in this model and are reported
    beside the allocation, not inside it.
    """
    total = full["p_total_loss_w"]
    branch = full["p_sr_branch_8device_w"]
    return {
        "p_total_loss_w": total,
        "p_sr_branch_8device_w": branch,
        "p_sr_share_of_total_loss_pct": 100.0 * branch / total if total else float("nan"),
        "p_other_model_loss_w": total - branch,
    }


def group_sharing(t: np.ndarray, data: dict[str, np.ndarray], t0: float, t1: float) -> dict[str, float]:
    """Average output current, RMS, port power and volt-seconds per group."""
    row = window_summary(t, data, 1, t0, t1)
    keep = (
        "iout_g1_a", "iout_g2_a", "iout_g3_a", "iout_g4_a",
        "irms_g1_a", "irms_g2_a", "irms_g3_a", "irms_g4_a",
        "p_port_g1_w", "p_port_g2_w", "p_port_g3_w", "p_port_g4_w",
        "flux_g1_vs", "flux_g2_vs", "flux_g3_vs", "flux_g4_vs",
        "iout_sum_a", "iout_spread_pct",
    )
    return {key: row[key] for key in keep if key in row}


def full_machine(raw: Path) -> dict[str, float]:
    """Operating point + full-machine power + four-group sharing on one raw."""
    t, data = load(raw)
    wins = op_windows(t, data, 22)
    t0, t1 = wins[0][0], wins[-1][1]
    out = power_block(t, data, t0, t1)
    out.update(ledger_window(t, data, wins))
    out.update(group_sharing(t, data, t0, t1))
    out["window_us"] = [t0 * 1e6, t1 * 1e6]
    out["raw"] = str(raw)
    out["raw_time_start_s"] = float(t[0])
    out["raw_time_end_s"] = float(t[-1])
    out["display_offset_us"] = 880.0
    if "p_total_loss_w" in out:
        out.update(sr_allocation(out))
    out["bias_note"] = (
        "UCC25600 SR model has no VCC quiescent draw; the SR gate driver is an "
        "ideal B-source not fed from VDD/REG. p_aux/p_reg therefore measure only "
        "residual source current, not real bias input power."
    )
    return out


def episodes(t: np.ndarray, v: np.ndarray, level: float, debounce: float = 2e-6) -> list[dict[str, float]]:
    """Contiguous above-level episodes merged inside `debounce`, with peak."""
    above = v > level
    starts = np.flatnonzero(above[1:] & ~above[:-1]) + 1
    if above[0]:
        starts = np.insert(starts, 0, 0)
    out: list[dict[str, float]] = []
    for idx in starts:
        start = float(t[idx])
        end = start
        peak = float(v[idx])
        for j in range(idx, len(t)):
            if not above[j]:
                break
            end = float(t[j])
            peak = max(peak, float(v[j]))
        if out and start - out[-1]["end_s"] < debounce:
            out[-1]["end_s"] = end
            out[-1]["peak_v"] = max(out[-1]["peak_v"], peak)
        else:
            out.append({"start_s": start, "end_s": end, "peak_v": peak})
    return out


def first_high(t: np.ndarray, gate: np.ndarray, level: float = 2.0) -> float | None:
    idx = np.flatnonzero(gate > level)
    return float(t[idx[0]]) if idx.size else None


def gate_duty(t: np.ndarray, gate: np.ndarray, t0: float, t1: float) -> float:
    w = window(t, t0, t1)
    return time_average(t[w], (gate[w] > 2.0).astype(float))


def cold_start(raw: Path, deck: Path) -> dict[str, object]:
    """What the converter actually does from 0 V, including OC / SS restarts."""
    text = deck.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(".ic"):
            raise SystemExit(f"{deck} still contains {stripped!r}; not a cold start")
    t, data = load(raw)
    out: dict[str, object] = {"deck": str(deck), "raw": str(raw), "t_end_ms": float(t[-1]) * 1e3,
                              "raw_time_start_s": float(t[0]), "raw_time_end_s": float(t[-1]),
                              "display_offset_us": 0.0}
    out["vout_max_v"] = float(data["V(out)"].max())
    out["ipri_peak_a"] = float(np.abs(data["I(Lr)"]).max())
    if "I(VSa1)" in data:
        out["ifwd_sr_peak_a"] = float((-data["I(VSa1)"]).max())
        out["irev_sr_peak_a"] = float(data["I(VSa1)"].max())
    oc = data.get("V(oc)")
    if oc is not None:
        out["oc_max_v"] = float(oc.max())
        out["oc_episodes_above_1v"] = episodes(t, oc, 1.0)
        out["oc_episodes_above_2v"] = episodes(t, oc, 2.0)
    ss = data.get("V(ss)")
    if ss is not None:
        # A FAULT discharge shows up as a fast SS drop.  Compare each sample with
        # the sample 100 us later; a drop > 0.2 V is a restart, not the ramp.
        t_later = t + 100e-6
        idx = np.searchsorted(t, t_later, side="left")
        ok = idx < len(t)
        drop = ss[ok] - ss[idx[ok]]
        drops = np.flatnonzero(drop > 0.2)
        starts: list[float] = []
        for k in drops:
            when = float(t[ok][k])
            if not starts or when - starts[-1] > 100e-6:
                starts.append(when)
        out["ss_restart_times_s"] = starts[:20]
        out["ss_restart_count"] = len(starts)
    gates = {}
    for n in (1, 2, 3, 4):
        for side in ("ga", "gb"):
            key = f"V({side}{n})"
            if key in data:
                gates[f"{side}{n}_first_high_s"] = first_high(t, data[key])
                gates[f"{side}{n}_duty_last_1ms"] = gate_duty(t, data[key], float(t[-1]) - 1e-3, float(t[-1]))
    out["gate_first_high"] = gates
    pre = {f"pre{n}": float(data[f"V(pre{n})"][-1]) for n in (1, 2, 3, 4) if f"V(pre{n})" in data}
    out["pre_final"] = pre
    # Frequency evolution.  f_law is the controller law evaluated at the window's
    # mean V(SS); it says what the oscillator should be doing, not what the tank
    # locks to.
    windows = [(0.5e-3, 1e-3), (1e-3, 1.5e-3), (1.5e-3, 2.5e-3), (2.5e-3, 4e-3),
               (4e-3, 5.5e-3), (5.5e-3, 7e-3), (7e-3, 8e-3)]
    rows = []
    for a, b in windows:
        if b > float(t[-1]):
            continue
        w = window(t, a, b)
        vss = time_average(t[w], ss[w]) if ss is not None else float("nan")
        rises = [r for r in edges(t, data["V(ga1)"]) if a <= r <= b]
        gate_period = float(np.mean(np.diff(rises))) if len(rises) >= 2 else None
        rows.append({
            "t0_ms": a * 1e3,
            "t1_ms": b * 1e3,
            "vout_v": time_average(t[w], data["V(out)"][w]),
            "vss_v": vss,
            "f_primary_khz": primary_freq_khz(t, data, gate_period, t0=a, t1=b),
            "f_law_khz": f_law_khz(float(vss)) if not np.isnan(vss) else float("nan"),
        })
    out["frequency_evolution"] = rows
    final = window_summary(t, data, 1, max(float(t[-1]) - 1e-3, 0.0), float(t[-1]))
    out["final_window"] = {k: v for k, v in final.items() if k.startswith(("iout", "irms", "p_port", "flux"))}
    return out


def conv_row(raw: Path, label: str, offset_us: float = 150.0, n_periods: int = 8) -> dict[str, float | str]:
    """One convergence row on the same saved window as the reference.

    offset_us is the Tstart that was trimmed away before the raw was written:
    150 us for the short 200 us family, 880 us for the 1 ms design-point family.

    n_periods must match that family's reference row.  The 1 ms family passes 22
    so its 5 ns row equals the operating-point row exactly; the 200 us family
    only has 10 complete periods, so it uses 8.  Per-period e_dissipated has a
    16..23 % cycle-to-cycle spread, so mixing period counts within one family
    would show ~9 % "differences" that are window noise, not convergence.
    """
    row = case(label, raw.stem + ".cir", "operating point", raw, 1, n_periods,
               display_offset_us=offset_us)
    keep = ("f_primary_khz", "freq_khz", "vout_time_avg_v", "pout_w",
            "q_port_rev_nc", "e_channel_uj", "e_bodydiode_uj", "e_rg_uj",
            "e_dissipated_uj", "p_device_w", "residual_pct_of_port",
            "period_spread_pct", "qrev_spread_pct", "display_offset_us",
            "raw_time_start_s", "raw_time_end_s")
    return {key: row[key] for key in keep}


def relative(a: float, b: float) -> float:
    return 100.0 * (b - a) / abs(a) if a else float("nan")


def compare(rows: dict[str, dict[str, float]], reference: str) -> dict[str, dict[str, float]]:
    """Relative change of every metric against the reference case."""
    ref = rows[reference]
    out: dict[str, dict[str, float]] = {}
    for label, row in rows.items():
        out[label] = {
            key: relative(float(ref[key]), float(row[key]))
            for key in ("f_primary_khz", "vout_time_avg_v", "q_port_rev_nc",
                        "e_dissipated_uj", "pout_w")
            if key in ref and key in row
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--op", type=Path, required=True)
    ap.add_argument("--full", type=Path, required=True)
    ap.add_argument("--cold", type=Path, default=None)
    ap.add_argument("--cold-deck", type=Path, default=Path("sim/v2/sr_tank_dual_v33_cold.cir"))
    ap.add_argument("--conv", nargs="+", default=[])
    ap.add_argument("--conv1ms", nargs="+", default=[],
                    help="fine steps at the 1 ms DESIGN point, e.g. 2n=... 1n=...; "
                         "the 5 ns reference is the --op raw")
    ap.add_argument("--cpin", nargs="+", default=[],
                    help="200 us CPIN family (INVALID as evidence: that window is still "
                         "a transient).  Kept only for the historical record.")
    ap.add_argument("--cpin1ms", nargs="+", default=[],
                    help="CPIN family at the 1 ms DESIGN point, e.g. 50p=... 200p=...; "
                         "the 100 pF reference is the --op raw")
    ap.add_argument("--json", type=Path, required=True)
    args = ap.parse_args()

    payload: dict[str, object] = {"generated": date.today().isoformat(), "rl_ohm": RL_OHM,
                                  "note": "MODEL numbers, no hardware measurement"}

    if args.op.exists():
        t, data = load(args.op)
        wins = op_windows(t, data, 22)
        payload["operating_point"] = {
            "raw": str(args.op),
            "raw_time_start_s": float(t[0]),
            "raw_time_end_s": float(t[-1]),
            "display_offset_us": 880.0,
            "window_us": [wins[0][0] * 1e6, wins[-1][1] * 1e6],
            "periods": len(wins),
            **ledger_window(t, data, wins),
            **power_block(t, data, wins[0][0], wins[-1][1]),
        }

    if args.full.exists():
        payload["full_machine"] = full_machine(args.full)

    if args.cold and args.cold.exists():
        payload["cold_start"] = cold_start(args.cold, args.cold_deck)

    conv: dict[str, dict[str, float]] = {}
    for spec in args.conv:
        label, _, path = spec.partition("=")
        if path and Path(path).exists():
            conv[label] = conv_row(Path(path), label)
    if conv:
        payload["convergence"] = conv
        payload["convergence_vs_5n_pct"] = compare(conv, "5n") if "5n" in conv else {}

    conv1ms: dict[str, dict[str, float]] = {}
    for spec in args.conv1ms:
        label, _, path = spec.partition("=")
        if path and Path(path).exists():
            conv1ms[label] = conv_row(Path(path), label, offset_us=880.0, n_periods=22)
    if conv1ms:
        if args.op.exists():
            conv1ms["5n"] = conv_row(args.op, "5n", offset_us=880.0, n_periods=22)
        payload["convergence_1ms"] = conv1ms
        payload["convergence_1ms_vs_5n_pct"] = compare(conv1ms, "5n") if "5n" in conv1ms else {}

    cpin: dict[str, dict[str, float]] = {}
    for spec in args.cpin:
        label, _, path = spec.partition("=")
        if path and Path(path).exists():
            cpin[label] = conv_row(Path(path), label)
    if cpin:
        payload["cpin_sensitivity_invalid_200us"] = cpin
        payload["cpin_sensitivity_invalid_200us"]["note"] = (
            "NOT valid evidence: the saved 150..200 us window is not the design "
            "point.  Vout there is 1.948..1.954 V against 1.892 V settled, i.e. "
            "still on the start-up overshoot, so a timestep or CPIN change moves "
            "the trajectory and not only the numerics.  The 1 ms family "
            "(cpin_sensitivity) is the evidence.")
        payload["cpin_vs_100p_pct_invalid_200us"] = (
            compare(cpin, "100p") if "100p" in cpin else {})

    cpin1ms: dict[str, dict[str, float]] = {}
    for spec in args.cpin1ms:
        label, _, path = spec.partition("=")
        if path and Path(path).exists():
            cpin1ms[label] = conv_row(Path(path), label, offset_us=880.0, n_periods=22)
    if cpin1ms:
        if args.op.exists():
            cpin1ms["100p"] = conv_row(args.op, "100p", offset_us=880.0, n_periods=22)
        payload["cpin_sensitivity"] = cpin1ms
        payload["cpin_vs_100p_pct"] = compare(cpin1ms, "100p") if "100p" in cpin1ms else {}

    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {args.json}")
    print(json.dumps({k: v for k, v in payload.items() if k not in ("convergence", "cpin_sensitivity")},
                     indent=2, ensure_ascii=False)[:4000])


if __name__ == "__main__":
    main()

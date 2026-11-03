"""Extract ELE-08 steady-state-initialized hot-fault metrics.

These decks start from ``.ic V(out)=1.89 V(ss)=4``, so the fault lands on a
precharged operating point instead of the soft-start ramp that the original
cold-start fault caught at ``V(ss)=3.78 V``.  That difference is the whole
point, and it is also the trap: **a precharge is not a proof of settling**.
The record therefore reports the pre-fault window (120..170 us on the rebased
axis) with its ripple and drift, and the post-fault window (175..320 us).

``Tstart`` rebases the stored timestamps: the 2175 us PWL crossing is saved at
175 us.  The 2 ms pre-fault window is deliberate: with ``.ic V(ss)=4`` the SS
pin only reaches ~4.485 V at 1 ms, below the strict 4.8 V settled floor.
Those offsets are derived from the deck text, never typed in.

Usage:
    python tools/hot_fault_metrics.py \
        --raw sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a.raw \
        --log sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a.log \
        --deck sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a.cir \
        --rl 15.4m --json design/v3/power_priority/hotfault_48v_120a.json
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np

from analyze_v3_transient import (first_cross, low_runs, mean_window,
                                  parallel_load_ohm, peak_after)
from ascii_raw_window import read_window
from current_manifest import spice_seconds

ROOT = Path(__file__).resolve().parent.parent
VOC_TRIP = 1.0
GATE_OFF = 1.0
SUSTAINED_LOW_S = 10e-6
SS_TARGET_V = 5.0
SS_TOLERANCE = 0.04           # 5.0 V settled target, 4.8 V floor (same as the strict log validator)
VOUT_DRIFT_LIMIT = 0.01       # half-window mean drift as a fraction of mean
NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?[a-zA-Z]*"


def _numbers(text: str) -> list[float]:
    return [spice_seconds(token) for token in re.findall(NUMBER, text)]


def _pwl_ramp(line: str) -> tuple[float, float] | None:
    """First 0->5 V segment of a ``PWL(...)`` source, as (start, end) seconds."""
    inner = line[line.index("(") + 1: line.rindex(")")]
    values = _numbers(inner)
    for a, ya, b, yb in zip(values[0::2], values[1::2], values[2::2], values[3::2]):
        if yb > ya and ya <= 2.5 <= yb:
            return a, b
    return None


def tran_window(deck_text: str) -> tuple[float, float]:
    """(Tstop, Tstart) from the deck's ``.tran`` line, in seconds."""
    for line in deck_text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith(".tran"):
            parts = stripped.split()
            return spice_seconds(parts[2]), spice_seconds(parts[3])
    raise ValueError("deck has no .tran line")


def saved_stop_s(deck_text: str) -> float:
    """Tstop on the saved axis.  Tstart rebases the timestamps, so a deck that
    stops at 2320 us and starts saving at 2000 us ends at 320 us, not 2320 us."""
    stop, start = tran_window(deck_text)
    return stop - start


def saved_fault_window(deck_text: str) -> dict[str, object]:
    """PWL crossing in absolute time and on the Tstart-rebased saved axis."""
    tstart = None
    ramp = None
    for line in deck_text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith(".tran"):
            parts = stripped.split()
            tstart = spice_seconds(parts[3])        # Tstep Tstop Tstart Tmaxstep
        if stripped.lower().startswith("vflt") and "pwl" in stripped.lower():
            ramp = _pwl_ramp(stripped)
    if tstart is None or ramp is None:
        raise ValueError("deck has no .tran Tstart or no Vflt PWL ramp")
    start, end = ramp
    engage = start + (2.5 / 5.0) * (end - start)
    if engage < tstart:
        raise ValueError("fault engages before the saved window opens")
    return {
        "tstart_s": tstart,
        "ramp_start_abs_s": start,
        "ramp_end_abs_s": end,
        "engage_abs_s": engage,
        "engage_rebased_s": engage - tstart,
    }


def fault_branch_ohm(deck_text: str) -> float:
    """``Ron`` of the fault switch plus its series resistor."""
    rflt = ron = None
    for line in deck_text.splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0].lower().startswith("rflt"):
            rflt = spice_seconds(parts[3])
        if parts[0].lower() == ".model" and len(parts) > 1 and "flt" in parts[1].lower():
            hit = re.search(r"ron\s*=\s*(" + NUMBER + ")", line, re.I)
            if hit:
                ron = spice_seconds(hit.group(1))
    if rflt is None or ron is None:
        raise ValueError("deck has no Rflt / SW(Ron=...) fault branch")
    return rflt + ron


def window_stats(t: np.ndarray, y: np.ndarray, t0: float, t1: float) -> dict[str, object]:
    mask = (t >= t0) & (t <= t1)
    if mask.sum() < 2:
        return {"samples": int(mask.sum()), "mean": None, "min": None,
                "max": None, "pp": None, "rms": None}
    tt, yy = t[mask], y[mask]
    return {
        "samples": int(mask.sum()),
        "mean": mean_window(t, y, t0, t1),
        "min": float(yy.min()),
        "max": float(yy.max()),
        "pp": float(yy.max() - yy.min()),
        "rms": float(np.sqrt(max(np.trapezoid(yy * yy, tt) / (tt[-1] - tt[0]), 0.0))),
    }


def pre_fault_state(t: np.ndarray, d: dict[str, np.ndarray],
                    t0: float, t1: float) -> dict[str, object]:
    """Was the converter actually at the design point before the fault?"""
    mid = 0.5 * (t0 + t1)
    vout = d["V(out)"]
    ss = d["V(ss)"]
    vout_stats = window_stats(t, vout, t0, t1)
    ss_stats = window_stats(t, ss, t0, t1)
    first = mean_window(t, vout, t0, mid)
    second = mean_window(t, vout, mid, t1)
    scale = max(abs(float(vout_stats["mean"] or 0.0)), 1e-12)
    drift = abs(second - first) / scale
    soft_start_finished = bool(float(ss_stats["mean"] or 0.0) >= SS_TARGET_V * (1 - SS_TOLERANCE))
    vout_flat = bool(drift <= VOUT_DRIFT_LIMIT)
    return {
        "window_s": [t0, t1],
        "vout": vout_stats,
        "ss": ss_stats,
        "oc": window_stats(t, d["V(oc)"], t0, t1),
        "vout_first_half_mean_v": first,
        "vout_second_half_mean_v": second,
        "vout_half_window_drift_frac": drift,
        "criterion": {
            "soft_start_target_v": SS_TARGET_V,
            "soft_start_floor_v": SS_TARGET_V * (1 - SS_TOLERANCE),
            "vout_half_window_drift_limit_frac": VOUT_DRIFT_LIMIT,
            "basis": "a precharge is not settling; both checks must hold",
        },
        "soft_start_finished": soft_start_finished,
        "vout_flat": vout_flat,
        "stable_at_design_point": soft_start_finished and vout_flat,
    }


def gate_after_trip(t: np.ndarray, gate: np.ndarray, t_trip: float,
                    on_level: float = 2.0) -> dict[str, object]:
    """What the saved SR gate does once the trip has fired.

    A report may not claim "the drive stayed low" without this: the SR
    timing model turns off on drain reverse-bias, so a bridge that stops
    switching can leave a gate asserted with nothing to reset it.  Real
    UCC24624 standby/light-load turn-off is not modelled.
    """
    after = t >= t_trip
    if not after.any():
        return {"samples": 0, "high_fraction": None, "final_v": None,
                "high_at_end": None, "gate_on_level_v": on_level}
    g = gate[after]
    return {
        "samples": int(after.sum()),
        "high_fraction": float((g > on_level).mean()),
        "final_v": float(gate[-1]),
        "high_at_end": bool(gate[-1] > on_level),
        "gate_on_level_v": on_level,
    }


def trip_delay(t: np.ndarray, voc: np.ndarray, engage_s: float,
               level: float = VOC_TRIP) -> dict[str, object]:
    trip = first_cross(t, voc, level, engage_s)
    return {
        "trip_s": trip,
        "trip_rebased_ms": None if trip is None else trip * 1e3,
        "delay_from_engage_us": None if trip is None else (trip - engage_s) * 1e6,
        "level_v": level,
    }


def parse_log(text: str) -> dict[str, object]:
    """``Total elapsed time`` plus every ``name: expr=value`` measurement line."""
    elapsed = re.search(r"Total elapsed time:\s*([0-9.]+)\s*seconds", text, re.I)
    measurements: dict[str, float] = {}
    for line in text.splitlines():
        head = re.match(r"\s*([A-Za-z_]\w*)\s*:\s*(.*)$", line)
        if not head:
            continue
        body = head.group(2)
        at = re.search(r"\bAT\s+(" + NUMBER + ")", body)
        eq = re.search(r"=\s*(" + NUMBER + ")", body)
        hit = at or eq
        if hit:
            measurements[head.group(1).lower()] = float(spice_seconds(hit.group(1)))
    # LTspice prints the elapsed line before giving up too, so the marker alone
    # would report "Time step too small; Simulation Failed" as a finished run.
    return {
        "solver_completed": elapsed is not None and "Simulation Failed" not in text,
        "total_elapsed_s": float(elapsed.group(1)) if elapsed else None,
        "measurements": measurements,
    }


def summarize(raw: Path, deck: Path, log: Path | None, rl: float,
              pre=(120e-6, 170e-6), post=(175e-6, 320e-6)) -> dict[str, object]:
    deck_text = deck.read_text(encoding="utf-8")
    window = saved_fault_window(deck_text)
    engage = float(window["engage_rebased_s"])
    names = ["V(out)", "V(ss)", "V(oc)", "I(Lr)", "V(ga1)", "V(gb1)", "V(reg)",
             "I(VSa1)", "I(VSb1)"]
    t, d = read_window(raw, names, 0.0, None)
    stop, start = tran_window(deck_text)
    saved_stop = stop - start
    branch = fault_branch_ohm(deck_text)

    trip = trip_delay(t, d["V(oc)"], engage)
    t_trip = trip["trip_s"] or float(t[-1])
    ipri_before, ipri_before_t = peak_after(t, d["I(Lr)"], engage, t_trip)
    ipri_after, ipri_after_t = peak_after(t, d["I(Lr)"], engage)
    sr_forward = max(float((-d[k]).max()) for k in ("I(VSa1)", "I(VSb1)"))
    sr_reverse = max(float(d[k].max()) for k in ("I(VSa1)", "I(VSb1)"))
    after = t >= engage
    runs = low_runs(t, d["V(ga1)"], GATE_OFF, t_trip)
    sustained = [(s, e) for s, e, _ in runs if e - s >= SUSTAINED_LOW_S]
    tail0 = max(float(t[0]), float(t[-1]) - 100e-6)
    load_after = parallel_load_ohm(rl, branch)
    log_data = parse_log(log.read_text(encoding="utf-8", errors="replace")) if log else None
    return {
        "kind": "hot_fault",
        "evidence_level": "SIMULATED_ONLY / NOT_RATED / NOT_A_COLD_START",
        "deck": str(deck.relative_to(ROOT)) if deck.is_relative_to(ROOT) else str(deck),
        "raw": str(raw.relative_to(ROOT)) if raw.is_relative_to(ROOT) else str(raw),
        "deck_has_ic": any(line.strip().lower().startswith(".ic")
                           for line in deck_text.splitlines()),
        "raw_bytes": raw.stat().st_size,
        "t_first_s": float(t[0]),
        "t_last_s": float(t[-1]),
        "deck_tstop_abs_s": stop,
        "deck_tstart_abs_s": start,
        "saved_stop_s": saved_stop,
        "reached_tstop": bool(t[-1] >= saved_stop - 1e-9),
        "solver_prefix_only": bool(t[-1] < saved_stop - 1e-9),
        "saved_window": window,
        "pre_fault": pre_fault_state(t, d, *pre),
        "fault": {
            "branch_ohm": branch,
            "load_ohm_nominal": rl,
            "load_ohm_after_fault": load_after,
            "severity_x": rl / load_after,
            **trip,
            "ipri_peak_before_trip_a": ipri_before,
            "ipri_peak_before_trip_ms": None if ipri_before_t is None else ipri_before_t * 1e3,
            "ipri_peak_after_engage_a": ipri_after,
            "ipri_peak_after_engage_ms": None if ipri_after_t is None else ipri_after_t * 1e3,
            "oc_max_v": float(d["V(oc)"].max()),
            "sr_forward_peak_whole_record_a": sr_forward,
            "sr_reverse_peak_whole_record_a": sr_reverse,
            "vout_min_after_engage_v": float(d["V(out)"][after].min()) if after.any() else None,
            "vout_final_v": mean_window(t, d["V(out)"], tail0, float(t[-1])),
            "pout_final_w": mean_window(t, d["V(out)"] ** 2 / load_after, tail0, float(t[-1])),
            "pout_final_basis": "V(out)^2 / (RL || fault branch), last 100 us",
            "first_sustained_drive_stop_ms": sustained[0][0] * 1e3 if sustained else None,
            "max_drive_low_us": round(max((e - s for s, e in sustained), default=0.0) * 1e6, 2),
            "i2t_to_trip_a2s": float(np.trapezoid(
                d["I(Lr)"][(t >= engage) & (t <= t_trip)] ** 2,
                t[(t >= engage) & (t <= t_trip)])),
            "reg_final_v": mean_window(t, d["V(reg)"], tail0, float(t[-1])),
            "sr_a_gate_after_trip": gate_after_trip(t, d["V(ga1)"], t_trip),
            "sr_b_gate_after_trip": gate_after_trip(t, d["V(gb1)"], t_trip),
            "sr_gate_latched_at_end": bool(
                d["V(ga1)"][-1] > 2.0 or d["V(gb1)"][-1] > 2.0),
        },
        "log": log_data,
        "limits": [
            "steady-state initialization means this is NOT a cold start; "
            "it cannot prove start-up protection or a cold inrush stress",
            "the model has no thermal, SOA or real current-sharing evidence",
            "a precharge does not prove settling -- use pre_fault.stable_at_design_point",
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, required=True)
    ap.add_argument("--deck", type=Path, required=True)
    ap.add_argument("--log", type=Path, default=None)
    ap.add_argument("--rl", default="15.4m")
    ap.add_argument("--pre-us", type=float, nargs=2, default=(120.0, 170.0))
    ap.add_argument("--post-us", type=float, nargs=2, default=(175.0, 320.0))
    ap.add_argument("--json", type=Path, required=True)
    args = ap.parse_args()
    data = summarize(args.raw.resolve(), args.deck.resolve(),
                     args.log.resolve() if args.log else None,
                     spice_seconds(args.rl),
                     tuple(x * 1e-6 for x in args.pre_us),
                     tuple(x * 1e-6 for x in args.post_us))
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

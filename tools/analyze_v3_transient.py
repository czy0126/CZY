"""Measure the 48 V/120 A target true-cold-start and overload-fault raws.

These two decks are stress candidates, not hardware ratings.  The cold raw is
large (tens of millions of ASCII lines), so this tool streams only the saved
columns it needs through :mod:`ascii_raw_window` instead of asking PyLTSpice to
materialise every trace.

What the record must carry
--------------------------
Cold start
    no ``.ic`` in the deck, the converter really starts at 0 V, the final
    output voltage/current, the primary and SR peaks, and whether soft start
    restarted.  "120 A" is only the eventual load target: current before the
    output rises is not 120 A.
Fault
    engagement is the PWL crossing of the fault-switch threshold, the OC trip
    instant and delay are measured from ``V(oc)``, and the peak ``|I(Lr)|``
    after engagement is the stress number.  If the solver collapses, the
    streamed prefix is still a valid record of the reachable interval and the
    JSON says so instead of pretending the 8 ms deck finished.

Usage:
    python tools/analyze_v3_transient.py --kind cold \
        --raw sim/v3/sr_tank_dual_v33_cold_vin48_i120_target.raw \
        --deck sim/v3/sr_tank_dual_v33_cold_vin48_i120_target.cir \
        --json design/v3/power_priority/cold_start_48v_120a_target.json
    python tools/analyze_v3_transient.py --kind fault \
        --raw sim/v3/sr_tank_dual_v33_cold_oc_vin48_i120_target.raw \
        --deck sim/v3/sr_tank_dual_v33_cold_oc_vin48_i120_target.cir \
        --json design/v3/power_priority/fault_48v_120a_target.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from ascii_raw_window import read_window
from current_manifest import spice_seconds

ROOT = Path(__file__).resolve().parent.parent
VOC_TRIP = 1.0
VOC_LATCH = 2.0
FAULT_TOP_V = 5.0
FAULT_SWITCH_V = 2.5
GATE_ON = 2.0
GATE_OFF = 1.0
SUSTAINED_LOW_S = 10e-6
TAIL_S = 100e-6


def deck_stop_s(deck: Path) -> float:
    """``Tstop`` from the deck's ``.tran`` line (Tstep Tstop Tstart Tmaxstep)."""
    for line in deck.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0].lower() == ".tran":
            return spice_seconds(parts[2])
    raise ValueError(f"{deck.name} has no .tran line")


def deck_has_ic(deck: Path) -> bool:
    """True if any directive (not a comment) starts with ``.ic``."""
    for line in deck.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("*") and stripped.lower().startswith(".ic"):
            return True
    return False


def engage_time(fault_start_s: float, fault_end_s: float) -> float:
    """When the 0..5 V fault PWL crosses the 2.5 V switch threshold."""
    return fault_start_s + (FAULT_SWITCH_V / FAULT_TOP_V) * (fault_end_s - fault_start_s)


def parallel_load_ohm(load_ohm: float, fault_ohm: float) -> float:
    """Load seen during the injected fault (the fault branch is in parallel)."""
    return load_ohm * fault_ohm / (load_ohm + fault_ohm)


def deck_fault_branch_ohm(deck: Path) -> float:
    """``Ron`` of ``Sflt`` plus ``Rflt``: the branch is in series with itself."""
    rflt = ron = None
    for line in deck.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0].lower() == "rflt":
            rflt = spice_seconds(parts[3])
        if parts and parts[0].lower().startswith(".model") and "SFLT" in line:
            for token in line.replace("(", " ").replace(")", " ").split():
                if token.lower().startswith("ron="):
                    ron = spice_seconds(token.split("=", 1)[1])
    if rflt is None or ron is None:
        raise ValueError(f"{deck.name} has no Rflt/Ron pair for the fault branch")
    return rflt + ron


def first_cross(t: np.ndarray, y: np.ndarray, level: float, after: float) -> float | None:
    idx = np.where((t > after) & (y >= level))[0]
    return float(t[idx[0]]) if idx.size else None


def low_runs(t: np.ndarray, y: np.ndarray, level: float, after: float) -> list[tuple[float, float, bool]]:
    mask = t > after
    tt, yy = t[mask], y[mask]
    if tt.size == 0:
        return []
    low = yy < level
    changes = np.diff(np.concatenate(([0], low.astype(int), [0])))
    starts, ends = np.where(changes == 1)[0], np.where(changes == -1)[0]
    runs = [(float(tt[s]), float(tt[e - 1]), False) for s, e in zip(starts, ends)]
    if low[-1] and runs:
        runs[-1] = (runs[-1][0], float(tt[-1]), True)
    return runs


def mean_window(t: np.ndarray, y: np.ndarray, t0: float, t1: float) -> float:
    mask = (t >= t0) & (t <= t1)
    if mask.sum() < 2:
        return float("nan")
    return float(np.trapezoid(y[mask], t[mask]) / (t[mask][-1] - t[mask][0]))


def rms_window(t: np.ndarray, y: np.ndarray, t0: float, t1: float) -> float:
    return float(np.sqrt(max(mean_window(t, y * y, t0, t1), 0.0)))


def i2t(t: np.ndarray, y: np.ndarray, t0: float, t1: float) -> float:
    mask = (t >= t0) & (t <= t1)
    return float(np.trapezoid(y[mask] ** 2, t[mask])) if mask.sum() > 1 else 0.0


def peak_after(t: np.ndarray, y: np.ndarray, after: float, before: float | None = None) -> tuple[float, float | None]:
    mask = t >= after
    if before is not None:
        mask &= t <= before
    if not mask.any():
        return 0.0, None
    tt, yy = t[mask], np.abs(y[mask])
    k = int(np.argmax(yy))
    return float(yy[k]), float(tt[k])


def common_meta(raw: Path, deck: Path, kind: str, t: np.ndarray) -> dict[str, object]:
    stop = deck_stop_s(deck)
    return {
        "kind": kind,
        "evidence_level": "SIMULATED_ONLY / NOT_RATED",
        "deck": str(deck.relative_to(ROOT)) if deck.is_relative_to(ROOT) else str(deck),
        "deck_has_ic": deck_has_ic(deck),
        "deck_tstop_s": stop,
        "raw": str(raw.relative_to(ROOT)) if raw.is_relative_to(ROOT) else str(raw),
        "raw_bytes": raw.stat().st_size,
        "raw_mtime": raw.stat().st_mtime,
        "t_first_s": float(t[0]),
        "t_last_s": float(t[-1]),
        "reached_tstop": bool(t[-1] >= stop - 1e-9),
        "solver_prefix_only": bool(t[-1] < stop - 1e-9),
        "note": "A streamed prefix of a collapsed run is still a valid record of "
                "the reachable interval; it is not a completed 8 ms run.",
    }


def summarize_cold(raw: Path, deck: Path, rl: float) -> dict[str, object]:
    names = ["V(out)", "I(Lr)", "V(oc)", "V(ss)", "V(ga1)", "V(reg)",
             "I(VSa1)", "I(VSb1)", "I(VSa4)", "I(VSb4)"]
    t, d = read_window(raw, names, 0.0, None)
    out: dict[str, object] = common_meta(raw, deck, "cold", t)
    # The first sample is the evidence for "no precharge": with `uic` and no
    # `.ic`, the solver's zero initial state must show up as ~0 V here.
    out["vout_at_t_first_v"] = float(d["V(out)"][0])
    out["ss_at_t_first_v"] = float(d["V(ss)"][0])
    tail0 = max(float(t[0]), float(t[-1]) - TAIL_S)
    out["load_ohm_nominal"] = rl
    out["vout_final_v"] = mean_window(t, d["V(out)"], tail0, float(t[-1]))
    out["vout_max_v"] = float(d["V(out)"].max())
    out["pout_final_w"] = mean_window(t, d["V(out)"] ** 2 / rl, tail0, float(t[-1]))
    out["pout_final_basis"] = "V(out)^2 / RL, trapezoidally averaged over the last 100 us"
    # The load is the 120 A *target*; the achieved current is whatever the
    # output voltage divided by that load turns out to be.
    out["iout_final_a"] = out["vout_final_v"] / rl
    hit = np.where(d["V(out)"] >= 0.9 * max(float(d["V(out)"].max()), 1e-9))[0]
    out["time_to_90pct_vout_ms"] = float(t[hit[0]]) * 1e3 if hit.size else None
    peak, peak_t = peak_after(t, d["I(Lr)"], 0.0)
    out["ipri_peak_a"] = peak
    out["ipri_peak_time_ms"] = None if peak_t is None else peak_t * 1e3
    out["ipri_rms_a"] = rms_window(t, d["I(Lr)"], tail0, float(t[-1]))
    out["sr_forward_peak_a"] = max(float((-d[k]).max()) for k in ("I(VSa1)", "I(VSb1)", "I(VSa4)", "I(VSb4)"))
    out["sr_reverse_peak_a"] = max(float(d[k].max()) for k in ("I(VSa1)", "I(VSb1)", "I(VSa4)", "I(VSb4)"))
    out["oc_max_v"] = float(d["V(oc)"].max())
    out["oc_time_max_ms"] = float(t[int(np.argmax(d["V(oc)"]))]) * 1e3
    out["oc_episodes_above_1v"] = len(low_runs(t, -d["V(oc)"], -VOC_TRIP, 0.0))
    out["oc_episodes_above_2v"] = len(low_runs(t, -d["V(oc)"], -VOC_LATCH, 0.0))
    out["ss_final_v"] = mean_window(t, d["V(ss)"], tail0, float(t[-1]))
    out["reg_final_v"] = mean_window(t, d["V(reg)"], tail0, float(t[-1]))
    return out


def summarize_fault(raw: Path, deck: Path, rl: float,
                    fault_start_s: float, fault_end_s: float,
                    fault_ohm: float | None = None) -> dict[str, object]:
    t_read, d = read_window(raw, ["V(out)", "I(Lr)", "V(oc)", "V(ss)", "V(ga1)", "V(reg)",
                                  "I(VSa1)", "I(VSb1)", "I(VSa4)", "I(VSb4)"],
                            max(0.0, fault_start_s - 0.5e-3), None)
    t = t_read
    out: dict[str, object] = common_meta(raw, deck, "fault", t)
    t_engage = engage_time(fault_start_s, fault_end_s)
    t_trip = first_cross(t, d["V(oc)"], VOC_TRIP, t_engage)
    out["fault_engage_ms"] = t_engage * 1e3
    # What the converter was doing when the overload landed.  The fault block's
    # banner claims start-up "has settled at the 200.6 kHz design point"; these
    # fields let the record check that instead of inheriting the claim.
    out["vout_at_engage_v"] = mean_window(t, d["V(out)"], t_engage - 20e-6, t_engage)
    out["ss_at_engage_v"] = mean_window(t, d["V(ss)"], t_engage - 20e-6, t_engage)
    out["oc_at_engage_v"] = mean_window(t, d["V(oc)"], t_engage - 20e-6, t_engage)
    if fault_ohm is None:
        fault_ohm = deck_fault_branch_ohm(deck)
    out["load_ohm_nominal"] = rl
    out["fault_branch_ohm"] = fault_ohm
    out["load_ohm_after_fault"] = parallel_load_ohm(rl, fault_ohm)
    out["fault_severity_x"] = rl / out["load_ohm_after_fault"]
    out["oc_trip_ms"] = None if t_trip is None else t_trip * 1e3
    out["fault_to_trip_us"] = None if t_trip is None else (t_trip - t_engage) * 1e6
    pre = t_trip if t_trip is not None else float(t[-1])
    peak, peak_t = peak_after(t, d["I(Lr)"], t_engage, pre)
    out["ipri_peak_before_trip_a"] = peak
    out["ipri_peak_before_trip_time_ms"] = None if peak_t is None else peak_t * 1e3
    peak_all, peak_all_t = peak_after(t, d["I(Lr)"], t_engage)
    out["ipri_peak_after_engage_a"] = peak_all
    out["ipri_peak_after_engage_time_ms"] = None if peak_all_t is None else peak_all_t * 1e3
    out["ipri_peak_5p6_5p8_a"] = float(np.abs(d["I(Lr)"][(t >= 5.6e-3) & (t <= 5.8e-3)]).max()) \
        if ((t >= 5.6e-3) & (t <= 5.8e-3)).any() else None
    out["oc_max_v"] = float(d["V(oc)"].max())
    out["oc_time_max_ms"] = float(t[int(np.argmax(d["V(oc)"]))]) * 1e3
    runs = low_runs(t, d["V(ga1)"], GATE_OFF, t_trip if t_trip is not None else t_engage)
    sustained = [(s, e, op) for s, e, op in runs if e - s >= SUSTAINED_LOW_S]
    out["first_sustained_drive_stop_ms"] = sustained[0][0] * 1e3 if sustained else None
    out["max_drive_low_us"] = round(max((e - s for s, e, _ in sustained), default=0.0) * 1e6, 2)
    out["i2t_to_trip_a2s"] = i2t(t, d["I(Lr)"], t_engage, pre)
    out["i2t_after_engage_a2s"] = i2t(t, d["I(Lr)"], t_engage, float(t[-1]))
    after = t >= t_engage
    out["vout_min_after_fault_v"] = float(d["V(out)"][after].min()) if after.any() else None
    tail0 = max(float(t[0]), float(t[-1]) - TAIL_S)
    out["vout_final_v"] = mean_window(t, d["V(out)"], tail0, float(t[-1]))
    # After engagement the output feeds both branches, so the load power uses
    # the parallel value.  The nominal RL would overstate it by the severity.
    out["pout_final_w"] = mean_window(
        t, d["V(out)"] ** 2 / out["load_ohm_after_fault"], tail0, float(t[-1]))
    out["pout_final_basis"] = "V(out)^2 / (RL || (Ron+Rflt)), the post-fault load"
    out["sr_forward_peak_a"] = max(float((-d[k]).max()) for k in ("I(VSa1)", "I(VSb1)", "I(VSa4)", "I(VSb4)"))
    out["sr_reverse_peak_a"] = max(float(d[k].max()) for k in ("I(VSa1)", "I(VSb1)", "I(VSa4)", "I(VSb4)"))
    out["reg_final_v"] = mean_window(t, d["V(reg)"], tail0, float(t[-1]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=("cold", "fault"), required=True)
    ap.add_argument("--raw", type=Path, required=True)
    ap.add_argument("--deck", type=Path, required=True)
    ap.add_argument("--rl", type=float, default=0.0154)
    ap.add_argument("--fault-start-ms", type=float, default=5.5)
    ap.add_argument("--fault-end-ms", type=float, default=5.6)
    ap.add_argument("--fault-r-ohm", type=float, default=None,
                    help="the injected branch in parallel with --rl; default "
                         "reads Ron+Rflt from the deck")
    ap.add_argument("--json", type=Path, required=True)
    args = ap.parse_args()
    raw = args.raw.resolve()
    deck = args.deck.resolve()
    if args.kind == "cold":
        if deck_has_ic(deck):
            raise SystemExit(f"{deck.name} contains .ic; it is not a true cold start")
        data = summarize_cold(raw, deck, args.rl)
    else:
        data = summarize_fault(raw, deck, args.rl,
                               args.fault_start_ms * 1e-3, args.fault_end_ms * 1e-3,
                               args.fault_r_ohm)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

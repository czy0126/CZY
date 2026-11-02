"""Eight-SR post-fault gate/current report from an ASCII RAW.

This reads the probe-deck output (`make_sr_fault_probes.py`).  It never
approves protection: it records which of the eight SR gates is still high at
the end, when that gate last rose, the drain-source voltage and the device
current while the gate is high, and the post-trip I^2t.  A high gate is a
model observation, not proof of permanent latch or of safe shutdown.

Usage:
    python tools/sr_fault_probe_report.py --case 48v_120a \
        --json design/v3/power_priority/sr_fault_probe_48v_120a.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from analyze_v3_transient import GATE_OFF, SUSTAINED_LOW_S, low_runs
from ascii_raw_window import read_window

ROOT = Path(__file__).resolve().parent.parent
PP = ROOT / "design/v3/power_priority"
CASES = {
    "48v_120a": {
        "raw": ROOT / "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_srprobe.raw",
        "deck": ROOT / "sim/v3/sr_tank_dual_v33_ss_hotfault_48v_120a_srprobe.cir",
        "base_json": PP / "hotfault_48v_120a.json",
    },
    "50v_120a": {
        "raw": ROOT / "sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a_srprobe.raw",
        "deck": ROOT / "sim/v3/sr_tank_dual_v33_ss_hotfault_50v_120a_srprobe.cir",
        "base_json": PP / "hotfault_50v_120a.json",
    },
}
PAIRS = (1, 2, 3, 4)
SIDES = ("a", "b")
GATE_ON_V = 2.0  # same level as analyze_v3_transient's published gate split
DEBOUNCE_S = 200e-9
ENGAGE_S = 175e-6
READ_LEAD_S = 5e-6
READ_TAIL_S = 2e-6


def device_traces(pair: int, side: str) -> tuple[str, str, str]:
    return f"V(g{side}{pair})", f"V({side}{pair})", f"I(VS{side}{pair})"


def all_traces() -> list[str]:
    return [name for pair in PAIRS for side in SIDES for name in device_traces(pair, side)]


def require_traces(data: dict[str, np.ndarray]) -> None:
    """Refuse a raw that lacks any of the eight devices.

    The base hot-fault raw only saves pair 1/4, so pointing this tool at it
    would otherwise crash on a KeyError inside the summary and look like a
    tool bug instead of "this record cannot answer the question".
    """
    missing = [name for name in all_traces() if name not in data]
    if missing:
        raise ValueError(f"raw lacks eight-device probes: {missing}")


def last_sustained_rise(t: np.ndarray, gate: np.ndarray, after: float,
                        debounce: float = DEBOUNCE_S) -> float | None:
    """Time of the last low->high gate crossing that stays high for debounce."""
    high = gate > GATE_ON_V
    crossings = np.flatnonzero(~high[:-1] & high[1:]) + 1
    for i in crossings[::-1]:
        if t[i] < after:
            return None
        stop = int(np.searchsorted(t, t[i] + debounce))
        stop = min(stop, t.size - 1)
        if bool(high[i:stop + 1].all()):
            return float(t[i])
    return None


def final_high_start(t: np.ndarray, gate: np.ndarray, after: float) -> float | None:
    """Time the gate last rose and stayed high to the end of the record.

    ``last_sustained_rise`` accepts any rise that survives the debounce; this
    one is the *final latch*, so a gain that rises and falls again does not
    count.  Returning None is the honest answer for a gate that is low at the
    last sample.
    """
    high = gate > GATE_ON_V
    if not bool(high[-1]):
        return None
    crossings = np.flatnonzero(~high[:-1] & high[1:]) + 1
    if crossings.size == 0:
        return None
    start = float(t[crossings[-1]])
    return start if start >= after else None


def drive_release_us(t: np.ndarray, gate: np.ndarray, trip_s: float) -> float | None:
    """First low run of at least 10 us after trip, as in hot_fault_metrics.

    The shorter dips are gate-drive edges, not a released drive; using the
    same >=10 us rule keeps this column comparable with the base JSON.
    """
    sustained = [(s, e) for s, e, _ in low_runs(t, gate, GATE_OFF, trip_s)
                 if e - s >= SUSTAINED_LOW_S]
    return sustained[0][0] * 1e6 if sustained else None


def latch_summary(t: np.ndarray, gate: np.ndarray, vds: np.ndarray,
                  current: np.ndarray, trip_s: float) -> dict[str, object] | None:
    """Current, Vds and I^2t during the final high-gate interval only.

    The post-trip gate-high total mixes two different things: the tail of the
    normal on-time right after trip (hundreds of amps) and the final latch in
    the dead state (amps).  Only this block answers "what does the gate high
    at the end actually conduct".
    """
    start = final_high_start(t, gate, trip_s)
    if start is None:
        return None
    mask = t >= start
    ts = t[mask]
    i = current[mask]
    v = vds[mask]
    forward = np.maximum(-i, 0.0)
    return {
        "start_us": start * 1e6,
        "duration_us": (float(t[-1]) - start) * 1e6,
        "i_abs_max_a": float(np.abs(i).max()),
        "i_forward_max_a": float(forward.max()),
        "i_reverse_max_a": float(np.maximum(i, 0.0).max()),
        "i2t_abs_a2s": float(np.trapezoid(i ** 2, ts)),
        "i2t_forward_a2s": float(np.trapezoid(forward ** 2, ts)),
        "vds_min_v": float(v.min()),
        "vds_max_v": float(v.max()),
    }


def device_summary(t: np.ndarray, gate: np.ndarray, vds: np.ndarray,
                   current: np.ndarray, trip_s: float) -> dict[str, object]:
    """Physical observation for one SR: gate state, Vds and device current."""
    post = t >= trip_s
    high = gate > GATE_ON_V
    tp = t[post]
    forward = np.maximum(-current, 0.0)
    reverse = np.maximum(current, 0.0)
    return {
        "gate_end_v": float(gate[-1]),
        "gate_high_at_end": bool(high[-1]),
        "gate_post_peak_v": float(gate[post].max()) if post.any() else None,
        "gate_high_fraction_after_trip": float(high[post].mean()) if post.any() else None,
        "gate_last_rise_us": (None if (rise := last_sustained_rise(t, gate, trip_s)) is None
                              else rise * 1e6),
        "vds_end_v": float(vds[-1]),
        "vds_min_post_v": float(vds[post].min()) if post.any() else None,
        "vds_max_post_v": float(vds[post].max()) if post.any() else None,
        "i_forward_peak_post_a": float(forward[post].max()) if post.any() else None,
        "i_reverse_peak_post_a": float(reverse[post].max()) if post.any() else None,
        "i2t_forward_post_a2s": float(np.trapezoid(forward[post] ** 2, tp)) if post.any() else None,
        "i2t_abs_post_a2s": float(np.trapezoid(current[post] ** 2, tp)) if post.any() else None,
        "i2t_while_gate_high_a2s": (
            float(np.trapezoid((current[post] ** 2) * high[post], tp)) if post.any() else None),
        "conduction_while_gate_high_a": (
            float(np.abs(current[post][high[post]]).max()) if (post.any() and high[post].any()) else 0.0),
        "drive_release_us": drive_release_us(t, gate, trip_s),
        "final_latch": latch_summary(t, gate, vds, current, trip_s),
    }


def summarize(t: np.ndarray, data: dict[str, np.ndarray], trip_s: float,
              saved_stop_s: float) -> dict[str, object]:
    devices = {}
    for pair in PAIRS:
        for side in SIDES:
            gate, vds, current = device_traces(pair, side)
            devices[f"{pair}{side.upper()}"] = device_summary(
                t, data[gate], data[vds], data[current], trip_s)
    high_at_end = [name for name, row in devices.items() if row["gate_high_at_end"]]
    latches = {name: row["final_latch"] for name, row in devices.items()
               if row["final_latch"] is not None}
    return {
        "t_first_s": float(t[0]),
        "t_last_s": float(t[-1]),
        "saved_stop_s": saved_stop_s,
        "reached_tstop": bool(t[-1] >= saved_stop_s - 0.5e-6),
        "solver_prefix_only": bool(t[-1] < saved_stop_s - 0.5e-6),
        "trip_s": trip_s,
        "devices": devices,
        "devices_high_at_end": high_at_end,
        "any_gate_high_at_end": bool(high_at_end),
        "conduction_currents_while_high_a": {
            name: row["conduction_while_gate_high_a"] for name, row in devices.items()
            if row["conduction_while_gate_high_a"] > 0.1},
        # The two numbers answer different questions.  The dict above includes
        # the tail of the normal gate on-time just after trip; the latch block
        # is only the final rise that persists to the end of the record.
        "final_latch_devices": sorted(latches),
        "final_latch_max_current_a": (
            max((v["i_abs_max_a"] for v in latches.values()), default=0.0)),
        "final_latch_max_i2t_abs_a2s": (
            max((v["i2t_abs_a2s"] for v in latches.values()), default=0.0)),
        "final_latch_i2t_abs_total_a2s": (
            float(sum(v["i2t_abs_a2s"] for v in latches.values()))),
    }


def build(case: str, raw: Path | None = None) -> dict[str, object]:
    if case not in CASES:
        raise ValueError(f"unsupported case: {case}")
    spec = CASES[case]
    raw = raw or spec["raw"]
    deck = spec["deck"]
    base = json.loads(spec["base_json"].read_text(encoding="utf-8"))
    trip_s = float(base["fault"]["trip_s"])
    saved_stop_s = float(base["saved_stop_s"])
    t, data = read_window(raw, all_traces(), max(0.0, ENGAGE_S - READ_LEAD_S),
                          saved_stop_s + READ_TAIL_S)
    require_traces(data)
    results = summarize(t, data, trip_s, saved_stop_s)
    results["raw"] = str(raw.relative_to(ROOT))
    results["raw_bytes"] = raw.stat().st_size
    results["deck"] = str(deck.relative_to(ROOT))
    results["evidence_level"] = "SIMULATED_ONLY / NOT_RATED / MODEL OBSERVATION"
    results["limits"] = (
        "A gate high at the last saved sample does not prove permanent latch. "
        "The SR timing model implements neither UCC24624 standby nor a real "
        "device SOA; Vgs/Vds/Id are model waveforms, not hardware.")
    return {
        "checks": {
            "ok": bool(all(name in data for name in all_traces())),
            "all_eight_devices_present": bool(all(name in data for name in all_traces())),
            "raw_has_nonempty_window": bool(t.size > 1),
            "coverage_is_reported_not_assumed":
                "reached_tstop" in results and "solver_prefix_only" in results,
        },
        "results": results,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", choices=tuple(CASES), required=True)
    ap.add_argument("--raw", type=Path, default=None)
    ap.add_argument("--json", type=Path, required=True)
    args = ap.parse_args()
    report = build(args.case, args.raw)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    r = report["results"]
    print(f"{args.case}: t_last={r['t_last_s'] * 1e6:.3f} us "
          f"reached_tstop={r['reached_tstop']} high_at_end={r['devices_high_at_end']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

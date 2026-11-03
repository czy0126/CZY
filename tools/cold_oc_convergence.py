"""Compare a cshunt cold-overload solve with the stalled 8 ms published record.

The 48 V/120 A true-cold-start fault deck stops advancing at 7.5714 ms of its
8 ms window: the solver collapses to ~1e-17 s steps and writes 11.55 GB while
simulated time moves by nanoseconds.  The same signature appeared in the 50 V
hot-fault stall, and there ``cshunt=1 fF`` (795 kOhm at 200 kHz) let the run
finish.  This tool tests the same aid on the cold-overload deck.

Two rules keep the comparison honest:

* the same saved window is read from both raws, so a solver setting is never
  mixed with a window change;
* the deck bodies must be identical after comments, ``.tran`` and ``.options``
  are removed -- otherwise it is a circuit change wearing a solver label.

Completion is read from the raw tail, never from the comparison slice: a
stalled file's prefix ends exactly at the window, which would look like a
clean stop if the window were used as the completion test.  When a record
stalls early, both sides are still read over the same *effective* slice
(``min(declared end, both tails)``); otherwise the maxima compare different
spans and the delta would reward the longer file.  Whether the declared window
was covered is reported separately.

Usage:
    python tools/cold_oc_convergence.py \
        --base-raw sim/v3/sr_tank_dual_v33_cold_oc_vin48_i120_target.raw \
        --base-deck sim/v3/sr_tank_dual_v33_cold_oc_vin48_i120_target.cir \
        --variant-raw sim/v3/sr_tank_dual_v33_cold_oc_vin48_i120_target_cshunt.raw \
        --variant-deck sim/v3/sr_tank_dual_v33_cold_oc_vin48_i120_target_cshunt.cir \
        --base-log sim/v3/sr_tank_dual_v33_cold_oc_vin48_i120_target.log \
        --variant-log sim/v3/sr_tank_dual_v33_cold_oc_vin48_i120_target_cshunt.log \
        --json design/v3/power_priority/cold_oc_vin48_i120_cshunt.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from analyze_v3_transient import first_cross, peak_after
from ascii_raw_window import last_time, read_window
from hot_fault_metrics import parse_log, saved_fault_window, saved_stop_s, VOC_TRIP
from hotfault_diagnostic import circuit_differences

ROOT = Path(__file__).resolve().parent.parent
# The fault engages at 5.55 ms; the OC trip and the I(Lr) peak both fall in
# 5.6..5.8 ms.  Stopping the window at 6.0 ms keeps the read small while
# covering every quantity the two runs can be compared on -- past 6 ms the
# stalled base has no counterpart the variant would be measured against.
COMPARE_WINDOW_US = (5400.0, 6000.0)
NAMES = ["V(oc)", "I(Lr)", "V(out)", "I(VSa1)", "I(VSb1)"]
PEAK_KEYS = ("trip_s", "ipri_peak_a", "sr_forward_peak_a", "oc_max_v",
             "vout_min_after_engage_v")
_STOP_TOL_S = 1e-9


def reached_stop(t_last_s: float, stop_s: float, tol_s: float = _STOP_TOL_S) -> bool:
    """True when a raw reaches its deck's saved stop."""
    return t_last_s >= stop_s - tol_s


def window_peaks(raw: Path, deck_text: str, t0_s: float, t1_s: float) -> dict[str, object]:
    """Peak definitions restricted to one common window of the cold-overload run."""
    t, d = read_window(raw, NAMES, t0_s, t1_s)
    engage = float(saved_fault_window(deck_text)["engage_rebased_s"])
    start = max(engage, t0_s)
    trip = first_cross(t, d["V(oc)"], VOC_TRIP, start)
    ipri, ipri_t = peak_after(t, d["I(Lr)"], start, trip if trip else None)
    after = t >= engage
    return {
        "t_first_s": float(t[0]),
        "t_last_s": float(t[-1]),
        "samples": int(t.size),
        "trip_s": trip,
        "delay_from_engage_us": None if trip is None else (trip - engage) * 1e6,
        "ipri_peak_a": ipri,
        "ipri_peak_ms": None if ipri_t is None else ipri_t * 1e3,
        # Body-diode forward current is negative in this deck; the published
        # record uses the same sign convention (fault_48v_120a_target.json).
        "sr_forward_peak_a": max(float((-d["I(VSa1)"]).max()),
                                 float((-d["I(VSb1)"]).max())),
        "oc_max_v": float(d["V(oc)"].max()),
        "vout_min_after_engage_v": float(d["V(out)"][after].min()) if after.any() else None,
    }


def compare(base_raw: Path, base_deck: Path, variant_raw: Path, variant_deck: Path, *,
            base_log: Path | None = None, variant_log: Path | None = None) -> dict[str, object]:
    base_text = base_deck.read_text(encoding="utf-8")
    variant_text = variant_deck.read_text(encoding="utf-8")
    differences = circuit_differences(base_text, variant_text)
    base_stop = saved_stop_s(base_text)
    variant_stop = saved_stop_s(variant_text)
    t0_s, t1_s = (v * 1e-6 for v in COMPARE_WINDOW_US)
    if t1_s > min(base_stop, variant_stop) + 1e-12:
        raise ValueError("comparison window exceeds a deck's saved stop")
    base_t_last = last_time(base_raw)
    variant_t_last = last_time(variant_raw)
    # A stalled record ends at its last saved sample.  Both sides are read over
    # the same effective slice, otherwise the maxima compare different spans.
    end_s = min(t1_s, base_t_last, variant_t_last)
    if end_s <= t0_s:
        raise ValueError("the two raws share no part of the comparison window")
    base = window_peaks(base_raw, base_text, t0_s, end_s)
    variant = window_peaks(variant_raw, variant_text, t0_s, end_s)
    delta = {key: (None if base.get(key) is None or variant.get(key) is None
                   else variant[key] - base[key]) for key in PEAK_KEYS}
    relative = {key: (None if base.get(key) in (None, 0.0) or variant.get(key) is None
                      else variant[key] / base[key] - 1.0) for key in PEAK_KEYS}
    covered = end_s >= t1_s - 1e-9
    base_done = reached_stop(base_t_last, base_stop)
    variant_done = reached_stop(variant_t_last, variant_stop)
    base_log_data = parse_log(base_log.read_text(encoding="utf-8", errors="replace")) if base_log else None
    variant_log_data = parse_log(variant_log.read_text(encoding="utf-8", errors="replace")) if variant_log else None
    limits = [
        "a convergence aid bounds a numerical artifact; it is not hardware evidence",
        "peaks are maxima over samples, so one step of sampling difference can move them",
        f"the comparison window ends at {COMPARE_WINDOW_US[1]:.0f} us; nothing after it has a base counterpart",
        "vout_min_after_engage_v is window-limited: the published -4.98 mV full-prefix "
        "dip happens after 6 ms, so the two numbers are different quantities",
        "a completed run does not approve the fault, the 8.7x stress or the hardware SOA",
    ]
    if not covered:
        limits.append(
            f"the common slice ends at {end_s * 1e6:.2f} us, not {t1_s * 1e6:.0f} us: "
            "the shorter record stops there, so the full-window deltas do not exist")
    if not variant_done:
        limits.append("the variant stalled too; its post-stall samples are not evidence")
    return {
        "kind": "cold_oc_convergence_diagnostic",
        "evidence_level": "SIMULATED_ONLY / NOT_RATED / NOT_A_COLD_START",
        "base_deck": str(base_deck.relative_to(ROOT)) if base_deck.is_relative_to(ROOT) else str(base_deck),
        "variant_deck": str(variant_deck.relative_to(ROOT)) if variant_deck.is_relative_to(ROOT) else str(variant_deck),
        "window_s": [t0_s, end_s],
        "declared_window_s": [t0_s, t1_s],
        "window_basis": "5.4-6.0 ms: covers fault engage (5.55 ms), the OC trip and the I(Lr) peak; "
                        "both sides are truncated to the shorter record's tail",
        "solver_option_lines": {
            "base": [line.strip() for line in base_text.splitlines()
                     if line.strip().lower().startswith(".options")],
            "variant": [line.strip() for line in variant_text.splitlines()
                        if line.strip().lower().startswith(".options")],
        },
        "results": {
            "base": base,
            "variant": variant,
            "delta": delta,
            "relative": relative,
            "base_saved_stop_us": base_stop * 1e6,
            "variant_saved_stop_us": variant_stop * 1e6,
            "base_reached_saved_stop": base_done,
            "variant_reached_saved_stop": variant_done,
            "base_t_last_us": base_t_last * 1e6,
            "variant_t_last_us": variant_t_last * 1e6,
            "window_end_us": end_s * 1e6,
            "declared_window_end_us": t1_s * 1e6,
            "declared_window_fully_covered": bool(covered),
        },
        "logs": {"base": base_log_data, "variant": variant_log_data},
        "checks": {
            "the_two_decks_differ_only_on_solver_settings": differences == [],
            "the_comparison_window_is_covered_by_both_raws": bool(covered),
            "the_window_stays_inside_both_decks": t1_s <= min(base_stop, variant_stop) + 1e-12,
        },
        "circuit_differences": differences,
        "limits": limits,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-raw", type=Path, required=True)
    ap.add_argument("--base-deck", type=Path, required=True)
    ap.add_argument("--variant-raw", type=Path, required=True)
    ap.add_argument("--variant-deck", type=Path, required=True)
    ap.add_argument("--base-log", type=Path)
    ap.add_argument("--variant-log", type=Path)
    ap.add_argument("--json", type=Path, required=True)
    args = ap.parse_args()
    record = compare(
        args.base_raw, args.base_deck, args.variant_raw, args.variant_deck,
        base_log=args.base_log, variant_log=args.variant_log,
    )
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.json}")
    print(f"base {record['results']['base']['trip_s']} / variant {record['results']['variant']['trip_s']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

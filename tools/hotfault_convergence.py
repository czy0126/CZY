"""Compare a convergence-aid hot-fault solve with the stalled published record.

The 50 V base run reaches 296.928 us of its 320 us saved window and then
advances 0.93 us in ~62 min (13.3 GB of raw for 1 ns of simulated time).  That
is a step-size limit cycle in the post-trip dead zone, not physics: every saved
voltage is frozen to microvolts while the charge-defined Cds/Cgd currents swing
by hundreds of amps.  A convergence aid (``cshunt``, or a softened model rail)
is only useful if it

* reaches the full saved stop instead of stalling again, and
* reproduces the published peaks over the window both runs cover.

This tool checks both and refuses to compare decks that differ anywhere other
than comments, ``.tran`` and ``.options`` -- otherwise the comparison would mix
a circuit change into a numerical one.  Like the SOLVER_DIAGNOSTIC tool, it
reports deltas as measured, never as a tolerance.

Usage:
    python tools/hotfault_convergence.py \
        --base-raw sim/v3/..._50v_120a.raw --base-deck sim/v3/..._50v_120a.cir \
        --variant-raw sim/v3/..._50v_120a_cshunt.raw \
        --variant-deck sim/v3/..._50v_120a_cshunt.cir \
        --base-log ..._50v_120a.log --variant-log ..._50v_120a_cshunt.log \
        --json design/v3/power_priority/hotfault_50v_120a_cshunt.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ascii_raw_window import last_time
from current_manifest import spice_seconds
from hot_fault_metrics import parse_log, saved_stop_s
from hotfault_diagnostic import PEAK_KEYS, circuit_differences, relative_deltas, window_peaks

ROOT = Path(__file__).resolve().parent.parent
# 220 us is the SOLVER_DIAGNOSTIC window: it covers the fault, the trip and
# both headline peaks, and both base raws have data there.  220, not 320,
# because the base stops at 296.929 us and a comparison must be same-window.
COMPARE_WINDOW_US = 220.0
# 220 us expressed as `220.0 * 1e-6` is one ULP above the stop parsed from
# `.tran 0 2220u 2000u`: the window guard needs a tolerance or it rejects a
# legal window.  1 ps is far below the 5 ns step.
_WINDOW_TOL_S = 1e-12


def max_step_s(deck_text: str) -> float | None:
    """The deck's ``.tran`` Tmaxstep, or None when it declares none.

    This is the only honest tolerance for "does the raw span the window": no
    sample can land exactly on the window's end, so the last in-window sample
    may sit up to one step short of it.  A fixed picosecond rejects a comparison
    whose raws both span the whole window -- the 5 fF B candidate slices ended
    at 219.9966 / 219.9990 us of a 220 us window and the check read "failed".
    """
    for line in deck_text.splitlines():
        parts = line.strip().split()
        if parts and parts[0].lower() == ".tran" and len(parts) >= 5:
            try:
                return spice_seconds(parts[4])
            except ValueError:
                return None
    return None


def reached_stop(t_last_s: float, stop_s: float, tol_s: float = 1e-9) -> bool:
    """True when a raw reaches its deck's saved stop (1 ns tolerance)."""
    return t_last_s >= stop_s - tol_s


def _options(text: str) -> list[str]:
    """The .options lines, so the record names the aid instead of relying on a header."""
    return [line.strip() for line in text.splitlines()
            if line.strip().lower().startswith(".options")]


def compare(base_raw: Path, base_deck: Path, variant_raw: Path, variant_deck: Path,
            *, window_us: float = COMPARE_WINDOW_US,
            base_log: Path | None = None, variant_log: Path | None = None) -> dict[str, object]:
    base_text = base_deck.read_text(encoding="utf-8")
    variant_text = variant_deck.read_text(encoding="utf-8")
    differences = circuit_differences(base_text, variant_text)
    base_stop = saved_stop_s(base_text)
    variant_stop = saved_stop_s(variant_text)
    window_s = window_us * 1e-6
    if window_s > min(base_stop, variant_stop) + _WINDOW_TOL_S:
        raise ValueError("comparison window exceeds a deck's saved stop")
    base = window_peaks(base_raw, base_text, window_s)
    variant = window_peaks(variant_raw, variant_text, window_s)
    # A variant that stops inside the comparison window has one record, not two:
    # re-reading a GB to recover the same slice would only duplicate the I/O.
    variant_full = (variant if window_s >= variant_stop - 1e-9
                    else window_peaks(variant_raw, variant_text, variant_stop))
    delta = {key: (None if base.get(key) is None or variant.get(key) is None
                   else variant[key] - base[key]) for key in PEAK_KEYS}
    base_log_data = parse_log(base_log.read_text(encoding="utf-8", errors="replace")) if base_log else None
    variant_log_data = parse_log(variant_log.read_text(encoding="utf-8", errors="replace")) if variant_log else None
    steps = [step for step in (max_step_s(base_text), max_step_s(variant_text)) if step is not None]
    coverage_tol = max(steps, default=_WINDOW_TOL_S)
    covered = (float(base["t_last_s"]) >= window_s - coverage_tol
               and float(variant["t_last_s"]) >= window_s - coverage_tol)
    # Completion is a property of the whole raw, not of the comparison slice:
    # reading the prefix would always end at the window and call a stall a stop.
    base_t_last = last_time(base_raw)
    variant_t_last = last_time(variant_raw)
    base_done = reached_stop(base_t_last, base_stop)
    variant_done = reached_stop(variant_t_last, variant_stop)
    limits = [
        "a convergence aid bounds a numerical artifact; it is not hardware evidence",
        "peaks are maxima over samples, so one step of sampling difference can move them",
        f"the comparison window ends at {window_us:.0f} us; nothing after it has a base counterpart",
        "a completed run does not make the post-trip model boundary (no UCC24624 standby, no SOA) safe",
    ]
    if not variant_done:
        limits.append("the variant stalled too; its post-stall samples are not evidence")
    return {
        "kind": "hotfault_convergence_diagnostic",
        "evidence_level": "SIMULATED_ONLY / NOT_RATED",
        "base_deck": str(base_deck.relative_to(ROOT)) if base_deck.is_relative_to(ROOT) else str(base_deck),
        "variant_deck": str(variant_deck.relative_to(ROOT)) if variant_deck.is_relative_to(ROOT) else str(variant_deck),
        "window_s": [0.0, window_s],
        "window_basis": f"{window_us:.0f} us: covers fault, trip and both headline peaks",
        "solver_option_lines": {"base": _options(base_text), "variant": _options(variant_text)},
        "results": {
            "base": base,
            "variant": variant,
            "delta": delta,
            "coverage_tolerance_s": coverage_tol,
            "relative": relative_deltas(base, variant),
            "base_saved_stop_us": base_stop * 1e6,
            "variant_saved_stop_us": variant_stop * 1e6,
            "base_saved_stop_s": base_stop,
            "variant_saved_stop_s": variant_stop,
            "base_reached_saved_stop": base_done,
            "variant_reached_saved_stop": variant_done,
            "base_t_last_us": base_t_last * 1e6,
            "variant_t_last_us": variant_t_last * 1e6,
            "variant_full_window": variant_full,
        },
        "logs": {"base": base_log_data, "variant": variant_log_data},
        "checks": {
            "the_two_decks_differ_only_on_solver_settings": not differences,
            "the_comparison_window_is_covered_by_both_raws": covered,
            "the_window_stays_inside_both_decks": window_s <= min(base_stop, variant_stop) + _WINDOW_TOL_S,
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
    ap.add_argument("--window-us", type=float, default=COMPARE_WINDOW_US)
    ap.add_argument("--base-log", type=Path, default=None)
    ap.add_argument("--variant-log", type=Path, default=None)
    ap.add_argument("--json", type=Path, required=True)
    args = ap.parse_args()
    record = compare(args.base_raw.resolve(), args.base_deck.resolve(),
                     args.variant_raw.resolve(), args.variant_deck.resolve(),
                     window_us=args.window_us,
                     base_log=args.base_log.resolve() if args.base_log else None,
                     variant_log=args.variant_log.resolve() if args.variant_log else None)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8", newline="\n")
    checks = record["checks"]
    results = record["results"]
    print(f"convergence diagnostic: checks {'ok' if all(checks.values()) else 'FAILED'}; "
          f"variant reached {results['variant_t_last_us']:.3f} us of "
          f"{results['variant_saved_stop_us']:.1f} us "
          f"({'completed' if results['variant_reached_saved_stop'] else 'stalled'})")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Compare a v3_4 Bage-soft-rail run with its v3_3 parent over a shared window.

The experiment changes exactly two things relative to the parent deck: the
``.include`` line points at ``sr_timing_v3_4_age_rail.lib`` instead of
``sr_timing_v3_3.lib``, and that model file differs from v3_3 by one Bage
expression.  Both are verified from the committed files before any raw is
opened, so a numeric difference in the shared window can be attributed to the
declared model change and not to a stray circuit edit.

The shared window ends at 220 us: it covers the fault, the trip and both
headline peaks, and it is the only span the stalled 2 fF control and its
replacement both contain.  Beyond it the tool only scans for the first sample
where the two trajectories part; no peak is measured there.

This is a numerical-surrogate diagnostic.  It is not silicon behaviour, not an
SOA or thermal proof, and a completed run does not make the post-trip model
boundary safe.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import generate_prot03_bage_diagnostic as gen
import hotfault_diagnostic as hot
from analyze_v3_transient import mean_window
from ascii_raw_window import last_time, read_window
from hot_fault_metrics import saved_stop_s
from hotfault_convergence import max_step_s, reached_stop

ROOT = Path(__file__).resolve().parent.parent
COMPARE_WINDOW_US = 220.0
PRE_FAULT_US = (140.0, 175.0)
_WINDOW_TOL_S = 1e-12


def verify_pair(variant: str, role: str, parent_text: str, variant_text: str,
                model_text: str) -> list[str]:
    """Raise unless the variant deck and model are exactly the declared ones.

    Returns the single element of the expected diff, so the record names the
    cause instead of asserting a generic "no differences".
    """
    expected = gen.deck_content(variant, role)
    if variant_text != expected:
        raise ValueError(f"{variant}/{role} deck is not the declared agefix derivative")
    if parent_text != (gen.SIM / gen.ROLE_FILES[variant][role]).read_text(encoding="utf-8"):
        raise ValueError(f"{variant}/{role} parent deck does not match the committed parent")
    if model_text != gen.model_content():
        raise ValueError("the v3_4 model is not the one declared by the generator")
    if gen.INCLUDE_OLD not in parent_text or gen.INCLUDE_NEW not in variant_text:
        raise ValueError("the parent/child include lines are not the declared pair")
    return [f"{gen.INCLUDE_OLD} -> {gen.INCLUDE_NEW} (model file: one Bage expression)"]


def measure(raw: Path, deck_text: str, window_s: float) -> dict[str, object]:
    """Published peak definitions plus the 140-175 us pre-fault V(out) mean."""
    peaks = hot.window_peaks(raw, deck_text, window_s)
    pre0, pre1 = (u * 1e-6 for u in PRE_FAULT_US)
    t, d = read_window(raw, ["V(out)"], pre0, pre1)
    mean = mean_window(t, d["V(out)"], pre0, pre1)
    peaks["pre_fault_vout_mean_v"] = None if mean != mean else mean
    peaks["pre_fault_window_s"] = [pre0, pre1]
    return peaks


def first_divergence(base_raw: Path, variant_raw: Path, t0_s: float,
                     t1_s: float) -> dict[str, object]:
    """First sample in [t0, t1) where the two raws disagree, and how.

    Both raws are read over the same span and compared element-wise.  Once the
    trajectories part, the two solver time axes are independent, so the scan
    stops at that sample.  ``None`` with equal sample counts means the two runs
    were bit-identical over the whole scanned span -- the declared model change
    was inert there, which is why exact-zero deltas are legitimate.
    """
    t1, d1 = read_window(base_raw, hot.NAMES, t0_s, t1_s)
    t2, d2 = read_window(variant_raw, hot.NAMES, t0_s, t1_s)
    n = min(len(t1), len(t2))
    first: float | None = None
    kind: str | None = None
    for i in range(n):
        if t1[i] != t2[i]:
            first, kind = float(t1[i]), "time"
            break
        if any(d1[name][i] != d2[name][i] for name in hot.NAMES):
            first, kind = float(t1[i]), "value"
            break
    return {
        "window_s": [t0_s, t1_s],
        "compared_samples": int(n),
        "base_samples": int(len(t1)),
        "variant_samples": int(len(t2)),
        "first_difference_s": first,
        "first_difference_us": None if first is None else first * 1e6,
        "difference_kind": kind,
        "identical_over_common_prefix": first is None and len(t1) == len(t2),
        "status": "compared",
    }


def compare(base_raw: Path, variant_raw: Path, base_deck_text: str, variant_deck_text: str,
            *, window_us: float = COMPARE_WINDOW_US) -> dict[str, object]:
    window_s = window_us * 1e-6
    base_stop = saved_stop_s(base_deck_text)
    variant_stop = saved_stop_s(variant_deck_text)
    if window_s > min(base_stop, variant_stop) + _WINDOW_TOL_S:
        raise ValueError("comparison window exceeds a deck's saved stop")
    base = measure(base_raw, base_deck_text, window_s)
    variant = measure(variant_raw, variant_deck_text, window_s)
    keys = hot.PEAK_KEYS + ("pre_fault_vout_mean_v",)
    delta = {k: (None if base[k] is None or variant[k] is None else variant[k] - base[k])
             for k in keys}
    relative = {k: (None if base[k] in (None, 0.0) or variant[k] is None
                    else variant[k] / base[k] - 1.0) for k in keys}
    steps = [step for step in (max_step_s(base_deck_text), max_step_s(variant_deck_text))
             if step is not None]
    coverage_tol = max(steps, default=_WINDOW_TOL_S)
    covered = (float(base["t_last_s"]) >= window_s - coverage_tol
               and float(variant["t_last_s"]) >= window_s - coverage_tol)
    base_t_last = last_time(base_raw)
    variant_t_last = last_time(variant_raw)
    base_done = reached_stop(base_t_last, base_stop)
    variant_done = reached_stop(variant_t_last, variant_stop)
    scan_hi = min(base_stop, variant_stop, base_t_last, variant_t_last)
    if scan_hi > window_s + _WINDOW_TOL_S:
        post = first_divergence(base_raw, variant_raw, window_s, scan_hi)
    else:
        post = {"window_s": [window_s, scan_hi], "compared_samples": 0,
                "first_difference_s": None, "first_difference_us": None,
                "difference_kind": None, "identical_over_common_prefix": None,
                "status": "no common post-window prefix"}
    limits = [
        "a numerical-surrogate rail change bounds a solver artifact; it is not device behaviour",
        "peaks are maxima over samples, so one step of sampling difference can move them",
        f"the shared window ends at {window_us:.0f} us; nothing after it has a parent counterpart",
        "a completed run does not make the post-trip boundary (no UCC24624 standby, no SOA) safe",
        "the post-window scan only reports where the two time axes first part; it measures no peak",
    ]
    if not variant_done:
        limits.append("the variant stalled too; its post-stall samples are not evidence")
    return {
        "kind": "prot03_bage_model_shared_window",
        "evidence_level": "SIMULATED_ONLY / NOT_RATED",
        "base_deck": None,
        "variant_deck": None,
        "window_s": [0.0, window_s],
        "window_basis": f"{window_us:.0f} us: covers fault, trip and both headline peaks",
        "results": {
            "base": base,
            "variant": variant,
            "delta": delta,
            "relative": relative,
            "coverage_tolerance_s": coverage_tol,
            "base_saved_stop_s": base_stop,
            "variant_saved_stop_s": variant_stop,
            "base_reached_saved_stop": base_done,
            "variant_reached_saved_stop": variant_done,
            "base_t_last_us": base_t_last * 1e6,
            "variant_t_last_us": variant_t_last * 1e6,
            "post_window_scan": post,
        },
        "checks": {
            "the_pair_differs_only_by_the_declared_model_include": True,
            "the_comparison_window_is_covered_by_both_raws": covered,
            "the_window_stays_inside_both_decks": window_s <= min(base_stop, variant_stop) + _WINDOW_TOL_S,
        },
        "declared_difference": [],
        "limits": limits,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--variant", required=True, choices=tuple(gen.ROLE_FILES))
    ap.add_argument("--role", required=True, choices=("B_CONTROL", "B_CANDIDATE"))
    ap.add_argument("--base-raw", type=Path, required=True)
    ap.add_argument("--variant-raw", type=Path, required=True)
    ap.add_argument("--base-deck", type=Path, required=True)
    ap.add_argument("--variant-deck", type=Path, required=True)
    ap.add_argument("--window-us", type=float, default=COMPARE_WINDOW_US)
    ap.add_argument("--json", type=Path, required=True)
    args = ap.parse_args()
    base_text = args.base_deck.read_text(encoding="utf-8")
    variant_text = args.variant_deck.read_text(encoding="utf-8")
    declared = verify_pair(args.variant, args.role, base_text, variant_text,
                           gen.NEW.read_text(encoding="utf-8"))
    record = compare(args.base_raw.resolve(), args.variant_raw.resolve(),
                     base_text, variant_text, window_us=args.window_us)
    record["declared_difference"] = declared
    record["base_deck"] = str(args.base_deck)
    record["variant_deck"] = str(args.variant_deck)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8", newline="\n")
    checks = record["checks"]
    print(f"Bage model shared window: checks {'ok' if all(checks.values()) else 'FAILED'}; "
          f"variant reached {record['results']['variant_t_last_us']:.3f} us")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

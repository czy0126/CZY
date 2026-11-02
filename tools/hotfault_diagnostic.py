"""Compare a SOLVER_DIAGNOSTIC hot-fault solve with the published record.

PR #20 asks for a documented diagnostic run before the 175..215 us peaks of
the 50 V fault are trusted.  The diagnostic deck changes only ``trtol``,
``abstol`` and the stop time, so the two solutions differ only in how the
solver discretised the same circuit.  Two rules make the comparison honest:

* the same saved window (0 .. the shorter deck's saved stop) is read from both
  raws, so a tolerance change is never mixed with a window change;
* the deck bodies must be identical after comments, ``.tran`` and ``.options``
  are removed -- otherwise it is a circuit change wearing a solver label.

Peaks are maxima over samples, so two runs that sample the same interval at
different points can still differ by one step.  The deltas are therefore
reported as measured, never as a tolerance.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from analyze_v3_transient import first_cross, peak_after
from ascii_raw_window import read_window
from hot_fault_metrics import parse_log, saved_fault_window, saved_stop_s, VOC_TRIP

ROOT = Path(__file__).resolve().parent.parent
NAMES = ["V(oc)", "I(Lr)", "V(out)", "I(VSa1)", "I(VSb1)"]
PEAK_KEYS = (
    "trip_s",
    "ipri_peak_a",
    "sr_forward_peak_a",
    "sr_reverse_peak_a",
    "oc_max_v",
    "vout_min_after_engage_v",
)
ALLOWED_DIRECTIVES = (".tran", ".options")


def _body(text: str) -> list[tuple[int, str]]:
    """(1-based line number, stripped line), without comments / allowed directives."""
    kept = []
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("*"):
            continue
        if stripped.lower().startswith(ALLOWED_DIRECTIVES):
            continue
        kept.append((number, stripped))
    return kept


def circuit_differences(base: str, diag: str) -> list[str]:
    """Every body line that is not identical in the two decks."""
    a, b = _body(base), _body(diag)
    out = []
    for i in range(max(len(a), len(b))):
        left = a[i] if i < len(a) else None
        right = b[i] if i < len(b) else None
        # Compare the directives themselves, not their line numbers: the
        # diagnostic deck carries a header, so numbering is offset by design.
        if left is not None and right is not None and left[1] == right[1]:
            continue
        line = left[0] if left else (right[0] if right else 0)
        out.append(f"line {line}: {left[1] if left else None!r} vs "
                   f"{right[1] if right else None!r}")
    return out


def relative_deltas(base: dict[str, float | None],
                    diag: dict[str, float | None]) -> dict[str, float | None]:
    """(diag/base - 1) per peak; None when either side is missing or base is 0."""
    out: dict[str, float | None] = {}
    for key in PEAK_KEYS:
        b, d = base.get(key), diag.get(key)
        out[key] = None if b in (None, 0.0) or d is None else d / b - 1.0
    return out


def shared_window_s(base_stop_s: float, diag_stop_s: float) -> float:
    """Both raws are read over 0..min(stop): the shorter run sets the window."""
    return min(base_stop_s, diag_stop_s)


def _limits(window_s: float, base_log: dict | None) -> list[str]:
    """What this comparison cannot say; derived, never typed per case."""
    out = [
        "a solver diagnostic bounds numerical error; it is not hardware evidence",
        "peaks are maxima over samples, so one step of sampling difference can move them",
        f"the shared window ends at {window_s * 1e6:.0f} us; nothing after it is covered",
    ]
    if base_log is not None and not base_log.get("solver_completed"):
        out.append("the base log has no completion line, so the base run itself stopped early")
    return out


def window_peaks(raw: Path, deck_text: str, t_end_s: float) -> dict[str, object]:
    """The published peak definitions, restricted to one common window."""
    t, d = read_window(raw, NAMES, 0.0, t_end_s)
    engage = float(saved_fault_window(deck_text)["engage_rebased_s"])
    trip = first_cross(t, d["V(oc)"], VOC_TRIP, engage)
    ipri, ipri_t = peak_after(t, d["I(Lr)"], engage, trip if trip else None)
    after = t >= engage
    return {
        "t_first_s": float(t[0]),
        "t_last_s": float(t[-1]),
        "samples": int(t.size),
        "trip_s": trip,
        "delay_from_engage_us": None if trip is None else (trip - engage) * 1e6,
        "ipri_peak_a": ipri,
        "ipri_peak_ms": None if ipri_t is None else ipri_t * 1e3,
        "sr_forward_peak_a": max(float((-d["I(VSa1)"]).max()),
                                 float((-d["I(VSb1)"]).max())),
        "sr_reverse_peak_a": max(float(d["I(VSa1)"].max()),
                                 float(d["I(VSb1)"].max())),
        "oc_max_v": float(d["V(oc)"].max()),
        "vout_min_after_engage_v": float(d["V(out)"][after].min()) if after.any() else None,
    }


def compare(base_raw: Path, base_deck: Path, diag_raw: Path, diag_deck: Path,
            base_log: Path | None = None, diag_log: Path | None = None) -> dict[str, object]:
    base_text = base_deck.read_text(encoding="utf-8")
    diag_text = diag_deck.read_text(encoding="utf-8")
    window = shared_window_s(saved_stop_s(base_text), saved_stop_s(diag_text))
    base = window_peaks(base_raw, base_text, window)
    diag = window_peaks(diag_raw, diag_text, window)
    delta = {k: (None if base.get(k) is None or diag.get(k) is None
                 else diag[k] - base[k]) for k in PEAK_KEYS}
    differences = circuit_differences(base_text, diag_text)
    overrun = abs(float(base["t_last_s"]) - float(diag["t_last_s"]))
    base_log_data = parse_log(base_log.read_text(encoding="utf-8", errors="replace")) if base_log else None
    diag_log_data = parse_log(diag_log.read_text(encoding="utf-8", errors="replace")) if diag_log else None
    return {
        "kind": "hotfault_solver_diagnostic",
        "evidence_level": "SIMULATED_ONLY / NOT_RATED",
        "base_deck": str(base_deck.relative_to(ROOT)) if base_deck.is_relative_to(ROOT) else str(base_deck),
        "diagnostic_deck": str(diag_deck.relative_to(ROOT)) if diag_deck.is_relative_to(ROOT) else str(diag_deck),
        "window_s": [0.0, window],
        "window_basis": "min(saved stop of the two decks); both raws read over it",
        "solver_setting_changes": {
            "trtol": "7 (default) -> 1",
            "abstol": "1e-12 (default) -> 1e-13",
            "tran_stop": f"{saved_stop_s(diag_text) * 1e6:.1f} us saved axis",
        },
        "results": {
            "base": base,
            "diagnostic": diag,
            "delta": delta,
            "relative": relative_deltas(base, diag),
            "t_last_difference_ns": overrun * 1e9,
        },
        "logs": {"base": base_log_data, "diagnostic": diag_log_data},
        "checks": {
            "the_two_decks_differ_only_on_solver_settings": not differences,
            "both_runs_reach_the_fault": base["trip_s"] is not None and diag["trip_s"] is not None,
            "the_two_runs_cover_the_same_window": overrun <= 10e-9,
        },
        "circuit_differences": differences,
        "limits": _limits(window, base_log_data),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-raw", type=Path, required=True)
    ap.add_argument("--base-deck", type=Path, required=True)
    ap.add_argument("--diag-raw", type=Path, required=True)
    ap.add_argument("--diag-deck", type=Path, required=True)
    ap.add_argument("--base-log", type=Path, default=None)
    ap.add_argument("--diag-log", type=Path, default=None)
    ap.add_argument("--json", type=Path, required=True)
    args = ap.parse_args()
    record = compare(args.base_raw.resolve(), args.base_deck.resolve(),
                     args.diag_raw.resolve(), args.diag_deck.resolve(),
                     args.base_log.resolve() if args.base_log else None,
                     args.diag_log.resolve() if args.diag_log else None)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8", newline="\n")
    checks = record["checks"]
    print(f"solver diagnostic: checks {'ok' if all(checks.values()) else 'FAILED'} "
          f"over 0..{record['window_s'][1] * 1e6:.1f} us")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Regenerate design/baseline/baseline_manifest.json from the files on disk.

The manifest is the single authoritative snapshot for the 2026-10-31 review
follow-up.  Every entry carries a full SHA256, size, role and (for models) a
classification from a fixed vocabulary documented in design/baseline/BASELINE.md.

Decks also record which local model libraries they `.include`, so a report can be
traced to the exact model files without opening every deck.

Usage: python tools/make_baseline.py
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "design" / "baseline" / "baseline_manifest.json"
INCLUDE_RE = re.compile(r"^\s*\.include\s+(\S+)", re.IGNORECASE)

MODELS: dict[str, tuple[str, str, str]] = {
    "models/sr_device_v3.lib": (
        "calibrated_behavioural_model",
        "BSC010N04LS6 surrogate fitted to datasheet curves",
        "package Ld/Ls are estimates; PGD law and temperature not calibrated; not vendor-signed",
    ),
    "models/sr_timing_v3.lib": (
        "sequencing_surrogate_model",
        "UCC24624 digital sequencing surrogate (SLUSD48C sections 7.5/7.6, 8.3.4, 8.4)",
        "typ thresholds only; uncalibrated PGD law; 128/46 ns gate edges vs 23/35 ns typ; "
        "standby, VSS offset current and adaptive 155/275 ns delay not implemented; the 6.7 nF "
        "gate surrogate is a known open driver-model defect (review P1); off-blank starts at "
        "max(Q falling edge, VD>ARM), conservative in the fast-rise case",
    ),
    "models/sr_timing_v3_roff.lib": (
        "sequencing_surrogate_model",
        "copy of sr_timing_v3.lib plus a behavioural 330 uA VSS offset equivalent",
        "the offset network is an equivalent, not a VSS-pin model; the gate loop still returns to S",
    ),
    "models/sr_timing_v2.lib": (
        "sequencing_surrogate_model",
        "older v2 sequencing, still used by the cold-start decks",
        "superseded by v3 for SR decisions; v2 and v3 numbers must not be combined",
    ),
    "models/sr_timing_v2_pin100p.lib": (
        "sequencing_surrogate_model",
        "sr_timing_v2.lib with Cgate 6.7n -> 100p, for real-device benches only",
        "A/B artifact: identical to v2 except the lumped gate capacitor, so the only variable "
        "against sr_timing_v3_* is the state machine; not a model revision",
    ),
    "models/sr_timing_v3_1.lib": (
        "sequencing_surrogate_model",
        "sr_timing_v3.lib plus the CGATE/CPIN gate-load parameters",
        "defaults reproduce v3 exactly; uncalibrated PGD law, typ thresholds only",
    ),
    "models/sr_timing_v3_2.lib": (
        "sequencing_surrogate_model",
        "sr_timing_v3_1.lib plus a soft rail on the off-blank integrator",
        "numerical robustness only, but its turn-off comparator latches one drain ring peak above "
        "OFFTH and cuts the SR off after the on-blank on a real tank; see sr_timing_v3_3.lib and "
        "design/v2/sr_tank_dual_results.md -- do not take SR conduction numbers from it",
    ),
    "models/sr_timing_v3_3.lib": (
        "sequencing_surrogate_model",
        "sr_timing_v3_2.lib with the turn-off comparator latch removed (v2 semantics restored)",
        "typ thresholds only; uncalibrated PGD law; the OFFTH turn-off now needs TOFF of continuous "
        "reverse-drain bias instead of one ringing peak; still not vendor-signed",
    ),
    "models/ucc25600_legacy_behaviour.lib": (
        "uncalibrated_behavioural_model",
        "UCC25600 controller behaviour: oscillator, soft start, OC comparator, dual gate outputs",
        "bootstrap and bias are behavioural; no real bias/enable sequencing circuit",
    ),
    "models/ucc27282_behaviour.lib": (
        "uncalibrated_behavioural_model",
        "UCC27282 gate driver from datasheet SNVSAQ5B: UVLO, EN timing, 16 ns TPD, 3 A/4 ohm drive",
        "no gate-charge or Qg model (the load is the timing model's lumped CGATE, review item 6.7 nF); "
        "delay matching, minimum pulse width and bootstrap reverse recovery not modelled",
    ),
}

SCOPE_GLOBS = (
    "models/*.lib",
    "sim/v2/comm_v3/*.cir",
    "sim/v2/comm_v3/*.log",
    "sim/v2/sr_timing_v3_checks_*.cir",
    "sim/v2/sr_timing_v3_checks_*.log",
    "sim/v2/verify_*.cir",
    "sim/v2/verify_*.log",
    "sim/v2/startup_ct*.cir",
    "sim/v2/startup_ct*.log",
    "sim/v2/sr_tank_dual*.cir",
    "sim/v2/sr_tank_dual*.log",
    "design/review_20261031/comm_review.cir",
    "design/review_20261031/comm_review.log",
    "design/review_20261031/fault_review.json",
    "design/baseline/BASELINE.md",
    "design/baseline/deck_runs_*.json",
    "design/v2/*.md",
    "design/v2/*.json",
    "tools/*.py",
)

NOT_RUN = {
    "sim/v2/comm_v3/sr_corner_10_0_18m.cir": "analytic corner; documented non-convergence (120 s, 67 MB raw); do not run",
    "sim/v2/sr_timing_v3_checks_v2qrace_diag.cir": "negative control; expected convergence failure (v2 deficiency)",
}

DIAGNOSTIC = {
    "sim/v2/comm_v3/sr_commutation_v3_debug.cir": "cannot run: includes removed models/sr_timing_v3_bench.lib; historical debug copy, not evidence",
    "sim/v2/comm_v3/sr_commutation_v3_debug1n.cir": "cannot run: includes removed models/sr_timing_v3_bench.lib; historical debug copy, not evidence",
    "sim/v2/comm_v3/sr_commutation_v3_debug_orig.cir": "pre-fix debug copy kept for comparison; not evidence",
    "sim/v2/comm_v3/probe_hier.cir": "hierarchical .op probe; not a transient benchmark",
    "sim/v2/comm_v3/sr_corner_probe_10_105m.cir": "threshold probe around one corner; not a reported case",
    "sim/v2/comm_v3/sr_corner_probe_40_0_18m.cir": "threshold probe around one corner; not a reported case",
    "sim/v2/sr_commutation.cir": "older forced-sine v2 bench; superseded by comm_v3",
}

ORPHAN_LOGS = {
    "sim/v2/comm_v3/sr_commutation_v3_win15-20.log": "no sibling .cir (deck removed); not evidence",
}


def sha256(path: Path) -> str:
    """Return the full lowercase SHA256 of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def includes(path: Path) -> list[str]:
    """Local model libraries a deck includes, normalised to project-relative paths."""
    found: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = INCLUDE_RE.match(line)
        if not match:
            continue
        target = (path.parent / match.group(1)).resolve()
        try:
            found.append(target.relative_to(ROOT).as_posix())
        except ValueError:
            found.append(match.group(1))
    return found


def classify(rel: str) -> tuple[str, str, str]:
    """Return (sha_class, purpose, caveat) for one project-relative path."""
    if rel in MODELS:
        return MODELS[rel]
    path = Path(rel)
    if path.suffix == ".lib":
        return ("unclassified_model", "model file outside the declared model table", "classification missing")
    if path.suffix == ".cir":
        return ("simulation_deck", "LTspice batch deck", "")
    if path.suffix == ".log":
        return ("numeric_artifact", "LTspice log from one run of the sibling deck", "not physical validation")
    if path.suffix == ".json":
        return ("numeric_artifact", "machine-readable measurement output", "")
    if path.suffix == ".md":
        return ("report", "project report", "read the scope banner; bench results are not hardware validation")
    if path.suffix == ".py":
        return ("analysis_tool", "analysis or runner script", "")
    return ("other", "", "")


def collect() -> list[dict[str, object]]:
    """Build manifest entries for every file in scope, sorted by path."""
    paths: dict[str, Path] = {}
    for pattern in SCOPE_GLOBS:
        for path in ROOT.glob(pattern):
            if path.is_file():
                paths[path.relative_to(ROOT).as_posix()] = path
    entries: list[dict[str, object]] = []
    for rel in sorted(paths):
        path = paths[rel]
        sha_class, purpose, caveat = classify(rel)
        entry: dict[str, object] = {
            "path": rel,
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
            "class": sha_class,
            "purpose": purpose,
            "caveat": caveat,
        }
        if rel.endswith(".cir"):
            entry["includes"] = includes(path)
        if rel in NOT_RUN:
            entry["status"] = "NOT_RUN"
            entry["status_note"] = NOT_RUN[rel]
        elif rel in DIAGNOSTIC:
            entry["status"] = "DIAGNOSTIC"
            entry["status_note"] = DIAGNOSTIC[rel]
        elif rel in ORPHAN_LOGS:
            entry["status"] = "ORPHAN"
            entry["status_note"] = ORPHAN_LOGS[rel]
        elif rel.endswith(".cir"):
            log = path.with_suffix(".log")
            if log.exists() and log.stat().st_mtime < path.stat().st_mtime:
                entry["status"] = "STALE_LOG"
                entry["status_note"] = "log predates the deck; rerun with tools/run_decks.py"
        entries.append(entry)
    return entries


def main() -> None:
    entries = collect()
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "tool": "LTspice 26.0.2 batch (-b), Normal solver, 27 C",
        "scope_note": "Single authoritative baseline for the 2026-10-31 review follow-up; "
        "design/review_20261031/manifest.json is the frozen review-time snapshot and is superseded by this file.",
        "entries": entries,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{len(entries)} entries -> {OUT.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()

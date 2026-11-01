"""Run LTspice batch decks with bounded timeouts and explicit pass/fail/timeout status.

Every run first removes the old .log/.raw so a stale artefact can never be mistaken
for the result of this run.  The JSON report lists, per deck: return code, timeout
flag, elapsed seconds, whether the log exists and contains "Total elapsed time", and
which solver-error markers are present.  A numerically completed run is still not a
physical PASS; this tool only records what happened.

Usage:
  python tools/run_decks.py --stale --timeout 120
  python tools/run_decks.py sim/v2/comm_v3/sr_load_40_120.cir --timeout 30
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

LTSPICE = Path(r"D:/ADI/LTspice/LTspice.exe")
ROOT = Path(__file__).resolve().parents[1]
STALE_ROOTS = (ROOT / "sim" / "v2", ROOT / "design" / "review_20261031")
ERROR_MARKERS = (
    "Error:",
    "Time step too small",
    "Singular matrix",
    "Analysis failed",
    "Voltage not found",
    "Measurement failed",
)


def run_deck(deck: Path, timeout_s: int) -> dict[str, object]:
    """Run one deck, deleting old artefacts first, and report an explicit outcome."""
    log = deck.with_suffix(".log")
    raw = deck.with_suffix(".raw")
    for old in (log, raw):
        if old.exists():
            old.unlink()
    started = time.monotonic()
    timed_out = False
    try:
        proc = subprocess.run(
            [str(LTSPICE), "-b", str(deck)], capture_output=True, timeout=timeout_s, text=True
        )
        rc: int | None = proc.returncode
    except subprocess.TimeoutExpired:
        rc, timed_out = None, True
    elapsed = round(time.monotonic() - started, 2)
    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    return {
        "deck": deck.relative_to(ROOT).as_posix(),
        "rc": rc,
        "timed_out": timed_out,
        "elapsed_s": elapsed,
        "log_exists": log.exists(),
        "finished": "Total elapsed time" in text,
        "error_markers": [m for m in ERROR_MARKERS if m in text],
    }


def stale_decks() -> list[Path]:
    """Decks whose .cir is newer than its .log, i.e. the log is not from this deck."""
    found: list[Path] = []
    for root in STALE_ROOTS:
        for cir in sorted(root.rglob("*.cir")):
            log = cir.with_suffix(".log")
            if log.exists() and cir.stat().st_mtime > log.stat().st_mtime:
                found.append(cir)
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("decks", nargs="*", help="deck paths relative to the project root")
    parser.add_argument("--stale", action="store_true", help="run every deck with an older log")
    parser.add_argument("--exclude", default="", help="comma-separated path substrings to skip")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--out", default="design/baseline/deck_runs.json")
    parser.add_argument("--merge", action="store_true", help="replace only the rerun decks in an existing --out file")
    args = parser.parse_args()

    skip = [item for item in args.exclude.split(",") if item]
    decks = stale_decks() if args.stale else [ROOT / item for item in args.decks]
    decks = [deck for deck in decks if not any(item in deck.as_posix() for item in skip)]
    results = [run_deck(deck, args.timeout) for deck in decks]

    out = ROOT / args.out
    if args.merge and out.exists():
        previous = json.loads(out.read_text(encoding="utf-8"))
        fresh = {item["deck"]: item for item in results}
        results = [fresh.pop(item["deck"], item) for item in previous] + list(fresh.values())
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    for item in results:
        if item["timed_out"]:
            status = "TIMEOUT"
        elif item["error_markers"] or not item["finished"] or item["rc"] != 0:
            status = "ERROR"
        else:
            status = "ok"
        print(f"{status:8s} {item['elapsed_s']:7.2f}s {item['deck']}")
    bad = [item for item in results if item["timed_out"] or item["error_markers"] or not item["finished"]]
    print(f"{len(results)} decks, {len(bad)} not clean -> {out.as_posix()}")


if __name__ == "__main__":
    main()

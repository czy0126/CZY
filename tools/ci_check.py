"""Lightweight offline CI (review 2026-11-01, issue #4).

Two gates, no hardware and no LTspice:

1. ``python -m pytest tools -q`` -- the whole offline suite.
2. Re-generate the v3 manifest and compare it with the committed one.  The
   manifest records size, mtime and hash for every deck, model, tool, result
   and doc, so a stale generated CSV or a changed model shows up as a named
   path instead of a silent mismatch.

The manifest's ``generated`` date and tracked-file mtime are deliberately
not compared: a new checkout or a new day is not a content drift.  The raw files over the hash limit are compared by size and mtime
only, which is why a regenerated raw does fail this check.

Usage:
    python tools/ci_check.py
    python tools/ci_check.py --skip-tests
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "design/v3/manifest_current_candidate.json"
COMPARED = ("entries", "missing", "deck_timing")


def _is_raw(path: str) -> bool:
    return path.endswith(".raw")


def _historical_crlf_equivalent(path: str, old: dict, fresh: dict) -> bool:
    """Recognize exact old Windows-CRLF hashes after a canonical Git-LF checkout.

    The historic manifest was generated on Windows before Git normalized text
    newlines. Match both historic SHA256 and byte count against current source
    re-encoded with CRLF. Actual content changes must still fail.
    """
    if _is_raw(path) or "sha256" not in old or "bytes" not in old:
        return False
    full = ROOT / path
    if not full.is_file():
        return False
    content = full.read_bytes()
    if b"\x00" in content:
        return False
    normalized = content.replace(b"\r\n", b"\n")
    historical = normalized.replace(b"\n", b"\r\n")
    # `fresh` is canonical LF now (see current_manifest.entry), so a CRLF
    # working tree must be compared in its normalised form.
    return (
        len(historical) == old["bytes"]
        and hashlib.sha256(historical).hexdigest() == old["sha256"]
        and hashlib.sha256(normalized).hexdigest() == fresh.get("sha256")
    )


def compare_manifests(committed: dict, fresh: dict) -> list[str]:
    """Return one line per difference; empty means the committed file is current.

    Large ``.raw`` files are deliberately not in Git (424 MB for the ledger run).
    A clean checkout therefore has no raw, and that must not fail CI; when a raw
    *is* present its size/mtime is still compared, so a regenerated raw fails.
    """
    problems: list[str] = []
    old = {row["path"]: row for row in committed.get("entries", [])}
    new = {row["path"]: row for row in fresh.get("entries", [])}
    for path in sorted(set(old) | set(new)):
        if path not in old:
            problems.append(f"{path}: produced now, not in the committed manifest")
        elif path not in new:
            if _is_raw(path):
                continue
            problems.append(f"{path}: in the committed manifest, no longer produced")
        elif _is_raw(path) and new[path].get("status") == "missing":
            # Missing RAW on a clean checkout is intentional, not drift.
            continue
        else:
            # Tracked file mtime is recreated on each checkout. Only hashes and
            # size are portable. Preserve mtime comparison for present RAWs.
            changed = sorted(key for key in set(old[path]) | set(new[path])
                             if (key != "mtime" or _is_raw(path))
                             and old[path].get(key) != new[path].get(key))
            if changed and _historical_crlf_equivalent(path, old[path], new[path]):
                changed = [key for key in changed if key not in ("bytes", "sha256")]
            if changed:
                problems.append(f"{path}: " + ", ".join(changed) + " differ")

    old_missing = set(committed.get("missing", []))
    new_missing = set(fresh.get("missing", []))
    for path in sorted(new_missing - old_missing):
        if _is_raw(path):
            continue
        problems.append(f"{path}: now missing")
    for path in sorted(old_missing - new_missing):
        problems.append(f"{path}: was missing, now present")

    old_timing = {row.get("deck"): row for row in committed.get("deck_timing", [])}
    new_timing = {row.get("deck"): row for row in fresh.get("deck_timing", [])}
    for deck in sorted(set(old_timing) | set(new_timing)):
        before, after = old_timing.get(deck, {}), new_timing.get(deck, {})
        changed = sorted(key for key in set(before) | set(after)
                         if before.get(key) != after.get(key))
        if changed:
            problems.append(f"{deck}: deck timing differs in " + ", ".join(changed))
    return problems


def run_tests() -> int:
    return subprocess.call([sys.executable, "-m", "pytest", "tools", "-q"], cwd=ROOT)


# Pages that only re-state committed artefacts.  They need no kicad-cli: a
# stale one is a reader following a hash or a command that no longer applies,
# so they are checked here rather than left to whoever opens the file next.
VIEWS = [
    ("bench-board manufacturing index", ["tools/manufacturing_index.py", "--check"]),
    ("main-board remaining dependencies",
     ["tools/remaining_dependencies.py", "--check"]),
]


def check_views() -> list[str]:
    problems = []
    for label, command in VIEWS:
        proc = subprocess.run([sys.executable, str(ROOT / command[0]), *command[1:]],
                              cwd=ROOT, capture_output=True, encoding="utf-8",
                              errors="replace")
        if proc.returncode != 0:
            output = (proc.stderr or proc.stdout).strip().splitlines()
            problems.append(f"{label}: {output[-1] if output else 'failed'}")
    return problems


def regenerate() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "manifest.json"
        subprocess.check_call(
            [sys.executable, str(ROOT / "tools/current_manifest.py"),
             "--scope", "v3", "--json", str(out)], cwd=ROOT)
        return json.loads(out.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args(argv)

    if not args.skip_tests:
        code = run_tests()
        if code != 0:
            print(f"pytest failed with exit code {code}", file=sys.stderr)
            return code

    committed = json.loads(MANIFEST.read_text(encoding="utf-8"))
    problems = compare_manifests(committed, regenerate())
    if problems:
        print("manifest is stale:", file=sys.stderr)
        for line in problems:
            print(f"  - {line}", file=sys.stderr)
        print("re-run: python tools/current_manifest.py --scope v3 "
              "--json design/v3/manifest_current_candidate.json", file=sys.stderr)
        return 1
    stale_views = check_views()
    if stale_views:
        print("generated views are stale:", file=sys.stderr)
        for line in stale_views:
            print(f"  - {line}", file=sys.stderr)
        return 1
    suffix = f"; v3 manifest is current; {len(VIEWS)} generated views are current"
    if args.skip_tests:
        print(f"ci: tests skipped{suffix}")
    else:
        print(f"ci: offline suite passed{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

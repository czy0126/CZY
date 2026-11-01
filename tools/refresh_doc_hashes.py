"""Refresh the 16-hex SHA256 prefixes quoted in the design reports from the files on disk.

The reports show hashes in three shapes:

    | `sr_load_10_100.cir` | `c60da98ddefd4336` |          single file
    | `sr_ls_10_0.cir/log` | `0245...` / `0676...` |        deck + sibling log
    | `sr_corner_10_0_2m`  | `e169...` / `efc7...` |        bare stem -> .cir, .log

A backticked token is treated as an owner when it resolves to a file (or a bare stem
with .cir/.log siblings).  Each following 16-hex token is replaced by that owner's
real prefix.  Hashes with no resolvable owner abort the run instead of being left
stale, so the report can never silently disagree with the baseline manifest.

Resolution order for a bare filename: exact project-relative path first, then the
SEARCH_ROOTS order below (models, then the simulation trees, then the frozen review
copy).  A line that deliberately quotes a historical hash carries the
HISTORY_MARKER comment and is skipped, so the audit trail survives refreshes.

Usage:
  python tools/refresh_doc_hashes.py --dry-run design/v2/sr_commutation_v3_results.md
  python tools/refresh_doc_hashes.py design/v2/sr_commutation_v3_results.md
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEARCH_ROOTS = ("models", "sim/v2", "sim/v2/comm_v3", "design/review_20261031", "design/baseline")
BACKTICK_RE = re.compile(r"`([^`]+)`")
HASH16_RE = re.compile(r"^[0-9a-f]{16}$")
HISTORY_MARKER = "<!-- historical-hash -->"
OWNER_RE = re.compile(r"<!--\s*hash-owner:\s*([^>]+?)\s*-->")


def sha16(path: Path) -> str:
    """First 16 hex characters of the file's SHA256."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def build_index() -> dict[str, Path]:
    """Map basenames to their project path, earlier SEARCH_ROOTS winning ties."""
    index: dict[str, Path] = {}
    for root in SEARCH_ROOTS:
        for path in (ROOT / root).rglob("*"):
            if not path.is_file() or path.suffix.lower() not in (".cir", ".log", ".lib", ".json", ".md"):
                continue
            index.setdefault(path.name, path)
    return index


def resolve(token: str, index: dict[str, Path]) -> list[Path]:
    """Files the token owns: exact path, `x.cir/log`, or a bare comm_v3 stem."""
    text = token.strip()
    if text.endswith(".cir/log"):
        # `stem.cir/log` and `dir/stem.cir/log` both mean "the deck and its log";
        # the index is keyed by basename, so drop any directory prefix.
        base = text[: -len(".cir/log")].rsplit("/", 1)[-1]
        pair = [index.get(base + ".cir"), index.get(base + ".log")]
        return [item for item in pair if item is not None]
    if "/" in text:
        exact = (ROOT / text).resolve()
        if exact.is_file():
            return [exact]
    name = text.rsplit("/", 1)[-1]
    if name in index:
        return [index[name]]
    if "." not in name:
        pair = [index.get(name + ".cir"), index.get(name + ".log")]
        return [item for item in pair if item is not None]
    return []


def rewrite_line(line: str, index: dict[str, Path]) -> tuple[str, int, list[str], bool]:
    """Replace hash tokens after their owner; return (line, replaced, unresolved, skipped)."""
    if HISTORY_MARKER in line:
        return line, 0, [], True
    marker = OWNER_RE.search(line)
    forced: list[Path] = []
    if marker:
        for owner in marker.group(1).split(","):
            forced.extend(resolve(owner.strip(), index))
        if not forced:
            return line, 0, [marker.group(1)], False
    pending: list[Path] = list(forced)
    out: list[str] = []
    replaced = 0
    unresolved: list[str] = []
    cursor = 0
    for match in BACKTICK_RE.finditer(line):
        out.append(line[cursor : match.start()])
        inner = match.group(1)
        if HASH16_RE.match(inner):
            if pending:
                out.append("`" + sha16(pending.pop(0)) + "`")
                replaced += 1
            else:
                unresolved.append(inner)
                out.append(match.group(0))
        else:
            if not marker:
                owned = resolve(inner, index)
                if owned:
                    # A hash binds to the NEAREST preceding owner, not the first
                    # one on the line: "`manifest.json` ... `model.lib` `abc123`"
                    # must rewrite abc123 as the model's hash, not the manifest's.
                    pending = list(owned)
            out.append(match.group(0))
        cursor = match.end()
    out.append(line[cursor:])
    return "".join(out), replaced, unresolved, False


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("docs", nargs="+", help="report paths relative to the project root")
    parser.add_argument("--dry-run", action="store_true", help="print changes without writing")
    args = parser.parse_args()

    index = build_index()
    failures: list[str] = []
    for doc_name in args.docs:
        doc = ROOT / doc_name
        lines = doc.read_text(encoding="utf-8").splitlines(keepends=True)
        updated: list[str] = []
        changed = replaced = skipped = 0
        for number, line in enumerate(lines, start=1):
            new, count, unresolved, was_skipped = rewrite_line(line, index)
            skipped += was_skipped
            if unresolved:
                failures.append(f"{doc_name}:{number}: no owner for {', '.join(unresolved)}")
            if new != line:
                changed += 1
            replaced += count
            updated.append(new)
        print(f"{doc_name}: {changed} lines, {replaced} hashes, {skipped} historical lines skipped")
        if not args.dry_run and changed:
            doc.write_text("".join(updated), encoding="utf-8")
        elif args.dry_run and changed:
            for before, after in zip(lines, updated):
                if before != after:
                    print("  - " + before.rstrip())
                    print("  + " + after.rstrip())
    for failure in failures:
        print("ERROR " + failure)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

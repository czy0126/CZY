"""Project the starred rows of docs/agent/TRAP_INDEX.md into the CLAUDE.md hot zone.

The hot zone is the only part of CLAUDE.md that is generated.  Everything else in
that file is hand-written index prose, which is why this tool fails closed: a
manual edit inside the markers is indistinguishable from a stale projection, so
`--check` compares bytes instead of trying to merge.

    python tools/agent_docs.py --write   # rewrite the block between the markers
    python tools/agent_docs.py --check   # byte equality + every home file exists

Exit code is 0 on success, 1 on drift or a broken table/marker pair.  The tool
never edits TRAP_INDEX.md: the index is the source of truth, the hot zone is a
projection of it.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = ROOT / "docs" / "agent"
INDEX = AGENT_DIR / "TRAP_INDEX.md"
HUB = ROOT / "CLAUDE.md"

BEGIN = "<!-- HOT_TABLE:BEGIN -->"
END = "<!-- HOT_TABLE:END -->"
STAR = "★"

HEADER = ("| 硬规则 | 触发（何时读全文） | 全文在 |", "|---|---|---|")


def _cells(line: str) -> list[str]:
    """Split a markdown table row, honouring backslash-escaped pipes."""
    inner = line.strip()
    if not inner.startswith("|"):
        raise ValueError(f"not a table row: {line!r}")
    inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    parts = re.split(r"(?<!\\)\|", inner)
    return [p.strip().replace("\\|", "|") for p in parts]


def index_rows(path: Path = INDEX) -> list[dict[str, str]]:
    """Return every rule row, starred or not, in file order.

    Header and separator rows are skipped by shape: the separator is the only
    row whose first cell is made of dashes, and the header is the first row.
    A row with the wrong column count is a hard error -- silently dropping it
    would make a rule disappear from the index while `--check` still passed.
    """
    rows: list[dict[str, str]] = []
    header_seen = False
    text = path.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = _cells(s)
        if not header_seen:
            header_seen = True
            continue
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
            continue
        if len(cells) != 4:
            raise SystemExit(
                f"{path.name}:{lineno}: expected 4 columns (star|rule|trigger|home), "
                f"got {len(cells)}: {s}"
            )
        star, rule, trigger, home = cells
        rows.append({"star": star, "rule": rule, "trigger": trigger, "home": home})
    if not rows:
        raise SystemExit(f"{path.name}: no rule rows found")
    return rows


def _home_link(cell: str) -> str:
    """Turn `ENVIRONMENT.md §远端` into a relative link from the repo root."""
    m = re.match(r"^([A-Za-z0-9_.-]+\.md)(.*)$", cell)
    if not m:
        return cell
    return f"[{m.group(1)}](docs/agent/{m.group(1)}){m.group(2)}"


def render_block(rows: list[dict[str, str]]) -> list[str]:
    starred = [r for r in rows if r["star"] == STAR]
    if not starred:
        raise SystemExit("TRAP_INDEX.md has no starred rows; refusing to blank the hot zone")
    out = [BEGIN, "", *HEADER]
    for r in starred:
        out.append(f"| {r['rule']} | {r['trigger']} | {_home_link(r['home'])} |")
    out += ["", END]
    return out


def _newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def read_text_exact(path: Path) -> str:
    """Read UTF-8 verbatim, with no universal-newline translation.

    ``Path.read_text(newline=...)`` only accepts ``newline`` from Python 3.13;
    CI pins 3.12, where the keyword raises ``TypeError``.  Reading bytes and
    decoding is the same operation as ``newline=""``: CRLF stays CRLF.
    """
    return path.read_bytes().decode("utf-8")


def split_block(text: str) -> tuple[str, str, str]:
    """Return (before, block, after); the block includes both marker lines."""
    if text.count(BEGIN) != 1 or text.count(END) != 1:
        raise SystemExit(
            f"{HUB.name}: expected exactly one {BEGIN} and one {END}, "
            f"found {text.count(BEGIN)} / {text.count(END)}"
        )
    i = text.index(BEGIN)
    j = text.index(END, i) + len(END)
    return text[:i], text[i:j], text[j:]


def desired_block(rows: list[dict[str, str]], nl: str) -> str:
    return nl.join(render_block(rows))


def write(quiet: bool = False) -> int:
    rows = index_rows()
    text = read_text_exact(HUB)
    nl = _newline(text)
    before, current, after = split_block(text)
    block = desired_block(rows, nl)
    if current == block:
        if not quiet:
            print(f"hot zone already current: {sum(r['star'] == STAR for r in rows)} rows")
        return 0
    HUB.write_text(before + block + after, encoding="utf-8", newline="")
    if not quiet:
        print(f"hot zone rewritten: {sum(r['star'] == STAR for r in rows)} rows")
    return 0


def check_homes(rows: list[dict[str, str]]) -> list[str]:
    missing = []
    for r in rows:
        m = re.match(r"^([A-Za-z0-9_.-]+\.md)", r["home"])
        if not m:
            missing.append(f"unparseable home {r['home']!r} for rule {r['rule']!r}")
        elif not (AGENT_DIR / m.group(1)).is_file():
            missing.append(f"{m.group(1)} (rule: {r['rule']})")
    return missing


def check() -> int:
    rows = index_rows()
    text = read_text_exact(HUB)
    nl = _newline(text)
    _, current, _ = split_block(text)
    block = desired_block(rows, nl)
    problems: list[str] = []
    if current != block:
        problems.append("hot zone differs from the projection of TRAP_INDEX.md")
    problems += [f"missing home file: {p}" for p in check_homes(rows)]
    if problems:
        for p in problems:
            print(f"FAIL {p}")
        print("run: python tools/agent_docs.py --write")
        return 1
    n_star = sum(r["star"] == STAR for r in rows)
    size = len(HUB.read_bytes())
    lines = text.count("\n")
    print(
        f"agent docs ok: {len(rows)} rules, {n_star} hot; "
        f"CLAUDE.md {size} bytes / {lines} lines (no byte budget by design)"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", action="store_true", help="rewrite the hot zone")
    g.add_argument("--check", action="store_true", help="byte-compare, fail on drift")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    return write(quiet=args.quiet) if args.write else check()


if __name__ == "__main__":
    sys.exit(main())

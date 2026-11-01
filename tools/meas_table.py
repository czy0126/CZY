"""Print an LTspice batch log's .meas results as a step-by-measurement table.

LTspice writes one `Measurement: name` block per .meas, each holding one row per
.step case; the .step headers are printed in a separate block at the end.  This
tool re-joins the two so a sweep can be read without eyeballing 8 blocks.

    python tools/meas_table.py sim/v2/comm_v3/sr_commutation_v3_g0.log
    python tools/meas_table.py <log> --only qrev_cyc ebd_cyc
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

STEP_RE = re.compile(r"^\.step (.+)$", re.M)
MEAS_RE = re.compile(r"Measurement: (\w+)\n(.*?)(?=\nMeasurement:|\Z)", re.S)
ROW_RE = re.compile(r"^\s+(\d+)\s+([-+\deE.]+)", re.M)
FLAT_RE = re.compile(r"^(\w+):\s+(.*)$", re.M)
AT_RE = re.compile(r"\sAT\s+([-+]?[\d.]+(?:e[-+]?\d+)?)\s*$")
EQ_RE = re.compile(r"=\s*([-+]?[\d.]+(?:e[-+]?\d+)?)")


def flat_value(rest: str) -> float | None:
    """Extract the result from a flat `name: expression` tail.

    Four shapes appear in LTspice 26 logs:
        V(d1)=-0.265  AT 4.009e-06      -> WHEN: the time after the upper-case AT
        V(c2f) =0 at 5.9e-06            -> FIND: the value, lower-case `at` is the
                                           sample time and comes *after* the result
        MAX(V(g2) )=0 FROM 4e-06 TO 6e-06 -> the value, before the window
        g1r-tc1=1.67e-07                -> the value after the last `=`
    """
    hit = AT_RE.search(rest)
    if hit:
        return float(hit.group(1))
    head = rest.split(" FROM ")[0]
    values = EQ_RE.findall(head)
    return float(values[-1]) if values else None


def parse_log(path: Path) -> tuple[list[str], dict[str, dict[int, float]]]:
    """Return (step labels in order, {measurement: {step index: value}}).

    Swept decks write one `Measurement: name` block per .meas; single-case decks
    write a flat `name: expression=value` line instead.  Both are supported.
    """
    text = path.read_text(errors="replace")
    labels = [m.group(1).strip() for m in STEP_RE.finditer(text)]
    table: dict[str, dict[int, float]] = {}
    for m in MEAS_RE.finditer(text):
        table[m.group(1)] = {int(r.group(1)): float(r.group(2)) for r in ROW_RE.finditer(m.group(2))}
    if not table:
        for m in FLAT_RE.finditer(text):
            value = flat_value(m.group(2))
            if value is not None:
                table.setdefault(m.group(1), {})[1] = value
    return labels, table


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("log", type=Path)
    ap.add_argument("--only", nargs="*", default=None, help="limit to these measurement names (case-insensitive)")
    args = ap.parse_args()

    labels, table = parse_log(args.log)
    names = list(table)
    if args.only:
        wanted = {w.lower() for w in args.only}
        names = [n for n in names if n.lower() in wanted]
    steps = sorted({s for rows in table.values() for s in rows})
    if not labels:
        labels = [f"{s}" for s in steps]

    width = max(len(n) for n in names) if names else 8
    print(f"{'step':>4}  {'case':<40}" + "".join(f"  {n:<{width}}" for n in names))
    for s in steps:
        case = labels[s - 1] if s - 1 < len(labels) else "?"
        cells = "".join(f"  {table[n].get(s, float('nan')):<{width}.10g}" for n in names)
        print(f"{s:>4}  {case:<40}{cells}")


if __name__ == "__main__":
    main()

"""Generate the deck variants issue #4 asks for.

The frozen v3 decks run `Lr=0.92 uH` (external) and `Cout=4 mF`.  The design
package specifies an external Lr of 1.0 uH nominal, a trimmed target of
1.0 uH - leakage, and a 15 x 470 uF = 7.05 mF bank.  Each variant below changes
exactly the named elements and nothing else, so the difference between two
results is the difference between those values.

    prod      0.92 uH external + 7.05 mF   the design tank with the physical bank
    untrimmed 1.0  uH external + 7.05 mF   the part wound to the nominal 1.0 uH
    lrmin     0.875 uH external + 7.05 mF  worst case: 0.125 uH leakage

The frozen decks themselves are never rewritten: `main()` only writes the
variants named on the command line (or all of them when none is named).  Do not
regenerate a deck whose raw is still being produced by a running LTspice.

Usage:
    python tools/make_physical_decks.py                # all variants
    python tools/make_physical_decks.py cout7m         # one variant
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SS_100A = "sim/v3/sr_tank_dual_v33_ss_1ms_100a.cir"
SS_100A_LEDGER = "sim/v3/sr_tank_dual_v33_ss_1ms_100a_ledger.cir"
COLD = "sim/v2/sr_tank_dual_v33_cold.cir"
COLD_OC = "sim/v2/sr_tank_dual_v33_cold_oc.cir"

OLD_LR = "LR_TOTAL=.92u"
OLD_COUT = "Cout out sgnd 4m Rser=0.2m"

LR_RE = re.compile(r"LR_TOTAL=[0-9.]+u")
COUT_RE = re.compile(r"Cout out sgnd [0-9.]+m Rser=0\.2m")
TRAN_RE = re.compile(r"^\.tran ([0-9.]+[a-z]?) ([0-9.]+[a-z]?) ([0-9.]+[a-z]?) ([0-9.]+[a-z]?) uic$", re.M)
LR_TOTAL_RE = re.compile(r"^Lr \S+ \S+ \{LR_TOTAL\} ", re.M)


def variant_text(source: str, lr: str | None = None, cout: str | None = None,
                 step: str | None = None) -> str:
    """Return the deck text with the requested values swapped in.

    ``None`` leaves an element untouched.  Each pattern must occur exactly once:
    a silent zero-match would produce a "variant" deck that is still the old one.
    """
    swaps = []
    if lr is not None:
        swaps.append((LR_RE, f"LR_TOTAL={lr}", "LR_TOTAL"))
    if cout is not None:
        swaps.append((COUT_RE, f"Cout out sgnd {cout} Rser=0.2m", "Cout"))
    for pattern, value, name in swaps:
        count = len(pattern.findall(source))
        if count != 1:
            raise ValueError(f"expected exactly one {name} pattern, found {count}")
        source = pattern.sub(value, source)
    if lr is not None and not LR_TOTAL_RE.search(source):
        raise ValueError("the Lr element does not use LR_TOTAL; the param swap would not reach it")
    if step is not None:
        match = TRAN_RE.search(source)
        if not match:
            raise ValueError("no '.tran <stop> <start> <tstart> <step> uic' line to rewrite")
        source = source[:match.start()] + (
            f".tran {match.group(1)} {match.group(2)} {match.group(3)} {step} uic"
        ) + source[match.end():]
    return source


# name -> (source, target, external Lr, Cout, max timestep)
VARIANTS: dict[str, tuple[str, str, str | None, str | None, str | None]] = {
    "phys": (SS_100A, "sim/v3/sr_tank_dual_v33_ss_1ms_100a_phys.cir", "1u", "7.05m", None),
    "cout7m": (SS_100A, "sim/v3/sr_tank_dual_v33_ss_1ms_100a_cout7m.cir", ".92u", "7.05m", None),
    "lrmin": (SS_100A, "sim/v3/sr_tank_dual_v33_ss_1ms_100a_lrmin.cir", ".875u", "7.05m", None),
    "cold_phys": (COLD, "sim/v3/sr_tank_dual_v33_cold_phys.cir", "1u", "7.05m", None),
    "cold_oc_phys": (COLD_OC, "sim/v3/sr_tank_dual_v33_cold_oc_phys.cir", "1u", "7.05m", None),
    "cold_oc_lrmin": (COLD_OC, "sim/v3/sr_tank_dual_v33_cold_oc_lrmin.cir", ".875u", "7.05m", None),
    # Issue #6: the same instrumented deck at half the timestep, so the
    # port/branch integrals can be compared at 5 ns and 2 ns.
    "ledger2n": (SS_100A_LEDGER, "sim/v3/sr_tank_dual_v33_ss_1ms_100a_ledger2n.cir",
                 None, None, "2n"),
}


def write(name: str) -> None:
    src, dst, lr, cout, step = VARIANTS[name]
    source = (ROOT / src).read_text(encoding="utf-8")
    (ROOT / dst).write_text(variant_text(source, lr, cout, step), encoding="utf-8")
    print(f"wrote {dst}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("names", nargs="*", help="variant names to write; default all")
    args = ap.parse_args(argv)
    unknown = [n for n in args.names if n not in VARIANTS]
    if unknown:
        ap.error(f"unknown variant(s) {unknown}; known: {sorted(VARIANTS)}")
    for name in args.names or VARIANTS:
        write(name)


if __name__ == "__main__":
    main()

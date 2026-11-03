"""Derive a cold-start deck that saves the CT burden voltage (SOURCE-05).

The parent cold deck saves ``I(Lr)`` but not ``V(ocd)``/``V(ocm)``, so the R3
startup power has so far been derived through the ideal-transformer identity
(``tools/startup_burden_pulse.py``).  This variant adds exactly three probes --
``V(ocd)``, ``V(ocm)`` and ``I(Rbur)`` -- and nothing else: the circuit, the
``.tran`` line, the ``.meas`` block and the solver options are byte-identical
to the parent.  It is therefore a diagnostic deck, not a new design point.

Until the raw exists the deck is UNRUN, and the parent raw stays the only
complete 8 ms record.

Usage:
    python tools/make_startup_burden_probe.py --write
"""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "sim/v3/sr_tank_dual_v33_cold_vin48_i120_target.cir"
DESTINATION = ROOT / "sim/v3/sr_tank_dual_v33_cold_vin48_i120_target_burden.cir"

# The last continuation line of the parent's .save block.  A new continuation
# directly after it stays inside the block; anywhere later (after .meas or a
# .model) it would be folded into that statement -- the trap that once made a
# whole probe family save nothing.
ANCHOR = "+ I(VSa1) I(VSb1) I(VSa4) I(VSb4)\n"
PROBES = "+ V(ocd) V(ocm) I(Rbur)\n"
TRAN = ".tran 0 8m 0 10n uic\n"

HEADER = (
    "* DIAGNOSTIC: saves the CT burden nodes through the true cold start.\n"
    "* Adds only V(ocd) V(ocm) I(Rbur) to the parent .save block; circuit,\n"
    "* .tran, .meas and solver options are identical to\n"
    "* sim/v3/sr_tank_dual_v33_cold_vin48_i120_target.cir.\n"
    "* UNRUN until the raw exists; a derived deck, not a hardware rating.\n"
)


def build(text: str) -> str:
    """Return the probe deck, refusing any source that is not the known parent."""
    if text.count(".end\n") != 1:
        raise ValueError("parent deck must have exactly one final .end line")
    if text.count(ANCHOR) != 1 or text.count(TRAN) != 1:
        raise ValueError("source is not the expected true-cold-start deck")
    for element in ("Rbur ocd ocm 10", "Lct1 nr nct 2u", "Lct2 cs1 cs2 20m"):
        if element not in text:
            raise ValueError(f"CT element missing: {element}")
    # The header comment mentions ".meas", so look for an actual .meas line.
    if text.find(ANCHOR) > text.find("\n.meas "):
        raise ValueError("save anchor is not inside the .save block")
    return HEADER + text.replace(ANCHOR, ANCHOR + PROBES, 1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    options = parser.parse_args(argv)
    expected = build(SOURCE.read_text(encoding="utf-8"))
    if options.write:
        DESTINATION.write_text(expected, encoding="utf-8", newline="\n")
    elif not DESTINATION.is_file() or DESTINATION.read_text(encoding="utf-8") != expected:
        raise SystemExit(f"stale cold-start burden probe {DESTINATION}; --write")
    print(DESTINATION.relative_to(ROOT), "UNRUN CT burden diagnostic")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

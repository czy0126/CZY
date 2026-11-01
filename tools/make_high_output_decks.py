"""Build strictly parameter-only high-output LTspice variants from the physical 100 A deck.

Not run or rated. Real achieved current must be measured from the waveform;
the load resistance is a *candidate* chosen for the desired current.
Do not modify controller, SR behaviour, Lr/Cr, protection or startup model here.

A second family, ``PROBE_CASES``, takes the whole `.save` block from the 100 A
*ledger* deck and nothing else.  Without `I(Cin) I(Rin)` the input power is not
in the raw at all, so the candidate has a measured output power but no
efficiency; without the rest of that block (`V(vin)`, `I(Cout)`, the CT nodes,
...) the loss inventory is not in it either.  Copying the block rather than
typing a subset means the candidate is measured by exactly the instruments the
100 A ledger uses -- if that deck gains a probe, this one follows.

Run: python tools/make_high_output_decks.py --write
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "sim/v3/sr_tank_dual_v33_ss_1ms_100a_phys.cir"
PARAM = ".param VIN=48 RL=18.9m LP=10u LR_TOTAL=1u CR_TOTAL=620n"
CASES = {
    "vin48_i110": ("48", "16.9m"),
    "vin48_i120": ("48", "15.4m"),
    "vin50_i110": ("50", "17.8m"),
    "vin50_i120": ("50", "16.3m"),
}
# Same decks plus the 100 A ledger deck's instruments; the save block is the
# only change.
PROBE_CASES = {
    "vin48_i110_cin": ("48", "16.9m"),
}
# The deck whose `.save` block defines what "measured" means for the ledger.
LEDGER_DECK = ROOT / "sim/v3/sr_tank_dual_v33_ss_1ms_100a_ledger.cir"


def build(source: str, vin: str, rl: str) -> str:
    if source.count(PARAM) != 1:
        raise ValueError("base physical deck changed: parameter line is not unique")
    # Insert one audit header. Every SPICE instruction apart from VIN/RL stays exact.
    hdr = (
        "* HIGH OUTPUT SENSITIVITY ONLY - UNRUN, NOT HARDWARE RATED\n"
        f"* VIN={vin} V RL={rl}; actual Iout is an unknown simulation result\n"
        "* Source: sr_tank_dual_v33_ss_1ms_100a_phys.cir; only VIN and RL change.\n"
    )
    return hdr + source.replace(PARAM, f".param VIN={vin} RL={rl} LP=10u LR_TOTAL=1u CR_TOTAL=620n")


def save_block(text: str) -> list[str]:
    """The `.save` directive and its `+` continuation lines, as written.

    LTspice folds those continuations into one directive, so a probe inserted
    into only the first line would silently miss every continuation line --
    which is exactly how the first attempt at this deck lost ``V(vin)``,
    ``I(Cout)`` and the CT nodes the ledger needs.
    """
    lines = text.splitlines(keepends=True)
    start = [i for i, line in enumerate(lines) if line.startswith(".save")]
    if len(start) != 1:
        raise ValueError(f"expected exactly one .save directive, found {len(start)}")
    end = start[0] + 1
    while end < len(lines):
        if lines[end].startswith("+"):
            end += 1
            continue
        # A comment only belongs to the block when a continuation follows it;
        # the decks put section comments between the continuation lines.
        nxt = end
        while nxt < len(lines) and (not lines[nxt].strip()
                                    or lines[nxt].strip().startswith("*")):
            nxt += 1
        if nxt < len(lines) and lines[nxt].startswith("+"):
            end = nxt
            continue
        break
    return lines[start[0]:end]


def build_probe(source: str, vin: str, rl: str, ledger: str | None = None) -> str:
    """The candidate deck with the 100 A ledger deck's `.save` block, nothing else."""
    plain = build(source, vin, rl)
    want = "".join(save_block(LEDGER_DECK.read_text(encoding="utf-8")
                              if ledger is None else ledger))
    have = "".join(save_block(plain))
    if plain.count(have) != 1:
        raise ValueError("base save block is not unique in the candidate deck")
    return plain.replace(have, want, 1)


def filename(name: str) -> Path:
    return ROOT / f"sim/v3/sr_tank_dual_v33_ss_1ms_{name}.cir"


def main() -> int:
    a = argparse.ArgumentParser()
    a.add_argument("--write", action="store_true")
    args = a.parse_args()
    base = BASE.read_text(encoding="utf-8")
    todo = [(name, vin, rl, build(base, vin, rl)) for name, (vin, rl) in CASES.items()]
    todo += [(name, vin, rl, build_probe(base, vin, rl)) for name, (vin, rl) in PROBE_CASES.items()]
    for name, vin, rl, expected in todo:
        dest = filename(name)
        if args.write:
            dest.write_text(expected, encoding="utf-8", newline="\n")
        else:
            if dest.read_text(encoding="utf-8") != expected:
                raise SystemExit(f"stale {dest.name} -- rerun --write")
        print(f"{dest.name}: VIN={vin}, RL={rl}; UNRUN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


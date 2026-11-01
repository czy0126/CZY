"""Turn the golden pin netlist into a placement plan for the native schematic.

`design/v3/pcb/board_netlist.csv` is a *deck-derived* netlist: it names a FET's
pins ``G``/``S``/``D`` because that is what the SPICE subcircuit calls them.
The real package has eight or nine pads, and the exposed pad of a DFN is a
drain pad.  Placing a part from the library and wiring only "the G pin" would
therefore leave six pads unconnected and still look correct in a netlist that
was itself generated from the deck -- the mistake would not show up until
copper.

So every pin mapping here is derived from a *measured* pin dump of the actual
library device (`hardware/dcx_main/library_pins.json`, produced by
`hardware/dcx_main/gen/probe_all_pins.js` against the running EasyEDA client,
which in semi-offline mode carries the full LCSC library).  Nothing in this
module guesses a pin number: a symbol whose pin numbers do not cover the
golden netlist raises instead.

The output is three artifacts:

* ``library_pins.json``      -- the measured pin evidence (written by the probe)
* ``placement_plan.json``    -- per-ref device, page and pin->net assignment
* ``pin_footprint_review.csv`` -- the A3 review sheet: every ref, its MPN, its
  footprint, which golden pins expanded to which pads, and which pads remain
  unconnected on purpose.

Run with ``--write`` to regenerate the two derived files.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "design/v3/pcb/board_netlist.csv"
HW = ROOT / "hardware/dcx_main"
PINS = HW / "library_pins.json"
PLAN = HW / "placement_plan.json"
REVIEW = HW / "pin_footprint_review.csv"

# ref group -> the library part it is drawn as.
# T1-T4, Lr and CT are deliberately absent: see MAGNETIC_GAPS.
GROUPS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("U1",), "UCC25600D"),
    (("U2",), "UCC27282DRCR"),
    (("U3", "U4", "U5", "U6"), "UCC24624DR"),
    (("QH", "QL"), "CSD19531Q5A"),
    (("SR1A", "SR1B", "SR2A", "SR2B", "SR3A", "SR3B", "SR4A", "SR4B"), "BSC010N04LS6"),
    (("D_CT1", "D_CT2", "D_CT3", "D_CT4"), "BAT54"),
    (("D_BT",), "BAT54WS"),
    (("J_IN",), "KF128_2P"),
    (("J_OUT",), "MX126_2P"),
    (("Lr",), "IND_10UH"),
    (("Cr", "Cin", "Cout", "C5", "C6", "C7", "C8", "C9", "C10", "C11", "C12"), "C0603_100n"),
    (("R1", "R2", "R3", "R4", "R5", "R15", "R16", "R17", "R18", "R19",
      "R20", "R21", "R22", "R23", "R24", "R25", "R26", "R27",
      "R28", "R29", "R30", "R31", "R32", "R33", "R34", "R35"), "R0603_10k"),
)

# The six functional blocks the A1 task card asks the sheet to be drawn in.
# They are also the layout order, so the drawing reads as a signal chain
# (input -> tank -> rectifier -> output) with the housekeeping beside it,
# instead of as one alphabetical grid.  Every ref in GROUPS must appear once;
# the test enforces that, so a new part cannot silently land in no block.
SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("1. Input and half bridge", ("J_IN", "Cin", "QH", "QL", "R4", "R5", "R18", "R19")),
    ("2. Resonant tank and T1-T4", ("Lr", "Cr", "CT", "D_CT1", "D_CT2", "D_CT3",
                                    "D_CT4", "R3", "T1", "T2", "T3", "T4")),
    ("3. Four synchronous rectifier groups", ("U3", "U4", "U5", "U6",
                                              "SR1A", "SR1B", "SR2A", "SR2B",
                                              "SR3A", "SR3B", "SR4A", "SR4B",
                                              "R20", "R21", "R22", "R23", "R24", "R25",
                                              "R26", "R27", "R28", "R29", "R30", "R31",
                                              "R32", "R33", "R34", "R35",
                                              "C7", "C8", "C9", "C10")),
    ("4. Control: UCC25600 / UCC27282", ("U1", "U2", "R1", "R2", "C6")),
    ("5. Bias, overcurrent and start-up", ("C5", "D_BT", "R15", "R16", "R17", "C11", "C12")),
    ("6. Output interface", ("J_OUT", "Cout")),
)

# Custom magnetics: no library symbol carries the required pin topology, so
# they cannot be placed as real devices yet.  Recording the gap is the point --
# a schematic that silently drops T1-T4 would still export a plausible netlist.
MAGNETIC_GAPS: dict[str, str] = {
    "T1": "needs a 5-pin 3:1:1 symbol (PRI_A/PRI_B/SEC_A/SEC_B/CTAP); "
          "the library's only 5-pad transformer (EE16_65KHZ) exposes 6 pins",
    "T2": "same custom symbol as T1",
    "T3": "same custom symbol as T1",
    "T4": "same custom symbol as T1",
    "CT": "needs a 4-pin current-transformer symbol; ZHT104A in the library has 2 pins",
}

# Golden pin name -> the pads it must land on.  Derived from the measured dumps
# in library_pins.json; the test re-derives them and fails if they drift.
FET_EXPANSION: dict[str, dict[str, tuple[str, ...]]] = {
    "CSD19531Q5A": {"G": ("4",), "S": ("1", "2", "3"), "D": ("5", "6", "7", "8", "9")},
    "BSC010N04LS6": {"G": ("4",), "S": ("1", "2", "3"), "D": ("5", "6", "7", "8")},
}

DIODE_PINS: dict[str, dict[str, tuple[str, ...]]] = {
    "BAT54": {"A": ("1",), "K": ("3",)},
    "BAT54WS": {"A": ("2",), "K": ("1",)},
}

# Two-terminal passives: the deck calls the ends N1/N2, A/K or P/N.
TWO_TERMINAL: dict[str, tuple[str, str]] = {
    "N1": "1", "N2": "2",
    "A": "1", "K": "2",
    "P": "1", "N": "2",
    "P2": "2", "P1": "1",
}

# Pads that are deliberately left unconnected, and why.  A blank here would be
# indistinguishable from an oversight.
UNCONNECTED: dict[str, dict[str, str]] = {
    "UCC27282DRCR": {"2": "NC by datasheet"},
    "BAT54": {"2": "second anode of the dual diode, unused"},
}

# Pads the *package* requires a connection for that the deck-derived golden
# netlist cannot express.  The SPICE model of UCC27282 has no exposed pad, but
# the VSON-10 package does, and leaving it floating both breaks the thermal
# path and shows up as an ERC warning.  These are design decisions, so they are
# listed here and reported separately rather than folded into the golden nets.
BONDED_PADS: dict[str, dict[str, str]] = {
    "UCC27282DRCR": {"11": "PGND"},          # EP -> VSS/PGND, thermal + reference
}

# A ref may be drawn as a library part that is topologically right but is not
# the part the design calls for.  Saying so on every row keeps the review sheet
# from reading like a finished BOM.
PLACEHOLDER: dict[str, str] = {
    "Lr": "PLACEHOLDER 10 uH SMD inductor; the design is a custom ELP32 3-turn / 1.444 mm gap part",
    "Cr": "PLACEHOLDER 100 nF 0603; the design value is 620 nF film (TO SELECT)",
    "Cin": "PLACEHOLDER 100 nF 0603; the design is a 20 uF input bank (TO SELECT)",
    "Cout": "PLACEHOLDER 100 nF 0603; the design is 15 x 470 uF (TO SELECT)",
    "D_BT": "PLACEHOLDER SOD-323 BAT54WS; the BOM calls for a 0603 >=100 V part",
}
for _r in ("R1", "R2", "R3", "R4", "R5", "R15", "R16", "R17", "R18", "R19"):
    PLACEHOLDER[_r] = "PLACEHOLDER 0603 10k; value is TO ASSIGN"
for _n in range(20, 36):
    PLACEHOLDER[f"R{_n}"] = "PLACEHOLDER 0603 10k; value is TO ASSIGN"
for _n in (5, 6, 7, 8, 9, 10, 11, 12):
    PLACEHOLDER[f"C{_n}"] = "PLACEHOLDER 0603 100 nF; value is TO ASSIGN"
del _r, _n


class MappingError(Exception):
    """A golden pin has no pad on the library symbol."""


def load_golden(path: Path = GOLDEN) -> dict[str, dict[str, str]]:
    """ref -> {pin_id: net}, preserving file order."""
    out: dict[str, dict[str, str]] = {}
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            out.setdefault(row["ref"], {})[row["pin"]] = row["net"]
    return out


def device_of(ref: str) -> str | None:
    for refs, part in GROUPS:
        if ref in refs:
            return part
    return None


def section_of(ref: str) -> str | None:
    for title, refs in SECTIONS:
        if ref in refs:
            return title
    return None


def basis_for(part: str, pin: str, symbol_pins: set[str]) -> str:
    """What the pin->pad claim rests on, for the review sheet's basis column."""
    if part in FET_EXPANSION and pin in FET_EXPANSION[part]:
        return "measured pin dump: pin name -> pad group"
    if part in DIODE_PINS and pin in DIODE_PINS[part]:
        return "measured pin dump: diode A/K -> pad"
    if pin in symbol_pins:
        return "symbol pin name equals golden pin"
    return "two-terminal legend N1/N2, A/K, P/N -> 1/2"


def pads_for(part: str, pin: str, symbol_pins: set[str]) -> tuple[str, ...]:
    """Which library pads a golden pin connects to."""
    if part in FET_EXPANSION and pin in FET_EXPANSION[part]:
        return FET_EXPANSION[part][pin]
    if part in DIODE_PINS and pin in DIODE_PINS[part]:
        return DIODE_PINS[part][pin]
    if pin in symbol_pins:
        return (pin,)
    if pin in TWO_TERMINAL and TWO_TERMINAL[pin] in symbol_pins:
        return (TWO_TERMINAL[pin],)
    raise MappingError(f"{part}: golden pin {pin!r} has no pad (symbol pins {sorted(symbol_pins)})")


def build_plan(golden: dict[str, dict[str, str]],
               library: dict[str, dict]) -> dict[str, object]:
    """Return the placement plan plus the review rows it implies."""
    plan: dict[str, object] = {"refs": {}, "gaps": dict(MAGNETIC_GAPS), "unresolved": []}
    rows: list[dict[str, str]] = []

    for ref, pins in golden.items():
        if ref in MAGNETIC_GAPS:
            plan["unresolved"].append({"ref": ref, "reason": MAGNETIC_GAPS[ref]})
            continue
        part = device_of(ref)
        if part is None:
            plan["unresolved"].append({"ref": ref, "reason": "no device assigned"})
            continue
        dev = library.get(part)
        if dev is None or "pins" not in dev:
            plan["unresolved"].append({"ref": ref, "reason": f"no library dump for {part}"})
            continue

        symbol_pins = {p["num"] for p in dev["pins"]}
        common = {
            "ref": ref, "section": section_of(ref) or "", "mpn": dev["mpn"],
            "lcsc": str(dev.get("lcsc") or ""), "footprint": str(dev.get("footprint") or ""),
        }
        pad_nets: dict[str, str] = {}
        for pin, net in pins.items():
            for pad in pads_for(part, pin, symbol_pins):
                if pad in pad_nets and pad_nets[pad] != net:
                    raise MappingError(f"{ref}: pad {pad} claimed by {pad_nets[pad]} and {net}")
                pad_nets[pad] = net
                rows.append({
                    **common, "golden_pin": pin, "pad": pad, "net": net,
                    "basis": basis_for(part, pin, symbol_pins),
                    "review_status": "MAPPED",
                    "note": PLACEHOLDER.get(ref, ""),
                })

        for pad, net in BONDED_PADS.get(part, {}).items():
            if pad in pad_nets:
                raise MappingError(f"{ref}: bonded pad {pad} already carries {pad_nets[pad]}")
            pad_nets[pad] = net
            rows.append({
                **common, "golden_pin": "", "pad": pad, "net": net,
                "basis": "package pin absent from the deck-derived netlist",
                "review_status": "BONDED BY DESIGN",
                "note": "BONDED BY DESIGN - package pad the deck cannot express",
            })

        for pad in sorted(symbol_pins - set(pad_nets)):
            reason = UNCONNECTED.get(part, {}).get(pad)
            note = reason or "NOT WIRED - unassigned pad, investigate"
            if ref in PLACEHOLDER:
                note = f"{note}; {PLACEHOLDER[ref]}"
            rows.append({
                **common, "golden_pin": "", "pad": pad, "net": "",
                "basis": "no net by design" if reason else "none - not yet decided",
                "review_status": "OPEN - REASON GIVEN" if reason else "OPEN - NEEDS DECISION",
                "note": note,
            })

        plan["refs"][ref] = {
            "part": part, "uuid": dev["uuid"], "pads": pad_nets,
            "section": section_of(ref),
        }

    plan["review_rows"] = rows
    return plan


def write_review(rows: list[dict[str, str]], path: Path = REVIEW) -> None:
    # The column set is the A1 task card's: ref, MPN, symbol pin, footprint pad,
    # net, the basis for the mapping, and a review status.
    cols = ["ref", "section", "mpn", "lcsc", "footprint", "golden_pin", "pad", "net",
            "basis", "review_status", "note"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true", help="write the plan and the review sheet")
    ap.add_argument("--pins", type=Path, default=PINS)
    args = ap.parse_args(argv)

    library = json.loads(args.pins.read_text(encoding="utf-8"))
    plan = build_plan(load_golden(), library)

    unresolved = plan["unresolved"]
    print(f"placed {len(plan['refs'])} refs, {len(plan['review_rows'])} pad rows, "
          f"{len(unresolved)} unresolved")
    for item in unresolved:
        print(f"  UNRESOLVED {item['ref']}: {item['reason']}")

    if args.write:
        PLAN.write_text(json.dumps({k: v for k, v in plan.items() if k != "review_rows"},
                                   indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        write_review(plan["review_rows"])
        print(f"wrote {PLAN.relative_to(ROOT)} and {REVIEW.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

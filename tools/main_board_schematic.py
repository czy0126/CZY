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
PROJECT_SYMBOLS = HW / "project_symbols.json"
PLAN = HW / "placement_plan.json"
REVIEW = HW / "pin_footprint_review.csv"

# ref group -> the library part it is drawn as.
# T1-T4 and CT map to project-library symbols; every other part is a system
# library device.  The distinction matters at placement time: a project device
# is addressed by the project uuid, a system device by the library hash.
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
    (("T1", "T2", "T3", "T4"), "DCX_XFMR_5P"),
    (("CT",), "DCX_CT_4P"),
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
                                              "C7", "C8", "C9", "C10",
                                              "C105", "C106", "C107", "C108",
                                              "C109", "C110", "C111", "C112")),
    ("4. Control: UCC25600 / UCC27282", ("U1", "U2", "R1", "R2", "C6",
                                         "R7", "R8", "R9", "R10", "C13",
                                         "C101", "C102", "C103", "C104")),
    ("5. Bias, overcurrent and start-up", ("C5", "D_BT", "R15", "R16", "R17", "C11", "C12")),
    ("6. Output interface", ("J_OUT", "Cout")),
)

# Custom magnetics are drawn with the two project-library symbols recorded in
# project_symbols.json (no system device has the required topology: the only
# 5-pad transformer symbol exposes 6 pins, ZHT104A exposes 2).  Being placed is
# NOT being verified: the symbol pin numbers are the logical terminal names,
# and the physical terminal -> pad map is still unknown, so these refs stay
# "unverified" everywhere a pass could be claimed.
MAGNETIC_UNVERIFIED: dict[str, str] = {
    "T1": "native symbol placed with logical terminal pins; physical terminal->pad map and DOT UNVERIFIED",
    "T2": "native symbol placed with logical terminal pins; physical terminal->pad map and DOT UNVERIFIED",
    "T3": "native symbol placed with logical terminal pins; physical terminal->pad map and DOT UNVERIFIED",
    "T4": "native symbol placed with logical terminal pins; physical terminal->pad map and DOT UNVERIFIED",
    "CT": "native symbol placed with logical terminal pins; vendor pinout and polarity UNVERIFIED",
}

# Project-library parts, i.e. the ones whose pin numbers are logical names
# rather than measured package pads.
MAGNETIC_PARTS: frozenset[str] = frozenset({"DCX_XFMR_5P", "DCX_CT_4P"})

# Why the review sheet still marks them: the footprint is a stand-in, and the
# phrase has to be present so the fabrication gate counts them as unresolved.
MAGNETIC_NOTE: dict[str, str] = {
    "T1": "PLACEHOLDER footprint XFMR-TH_5P (5 pads); physical terminal->pad map NOT verified",
    "T2": "PLACEHOLDER footprint XFMR-TH_5P (5 pads); physical terminal->pad map NOT verified",
    "T3": "PLACEHOLDER footprint XFMR-TH_5P (5 pads); physical terminal->pad map NOT verified",
    "T4": "PLACEHOLDER footprint XFMR-TH_5P (5 pads); physical terminal->pad map NOT verified",
    "CT": "PLACEHOLDER footprint XFMR-TH_ZHT104A (2 pads for 4 logical terminals); pinout NOT verified",
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

def _decoupling() -> dict[str, dict[str, object]]:
    """One 1 uF and one 100 nF per controller, paired by IC in ref order.

    The BOM row fixes the pair ("1 uF + 100 nF at each of the six ICs") but not
    which designator carries which value.  That assignment is a design decision,
    so it is stated once here rather than being left implicit in the drawing.
    """
    ics = (("U1", "VCC12"), ("U2", "VCC12"), ("U3", "VCC12_S"),
           ("U4", "VCC12_S"), ("U5", "VCC12_S"), ("U6", "VCC12_S"))
    out: dict[str, dict[str, object]] = {}
    for i, (ic, vdd) in enumerate(ics):
        for j, value in enumerate(("1 uF", "100 nF")):
            ref = f"C{101 + 2 * i + j}"
            out[ref] = {
                "part": "C0603_100n", "value": value,
                "pads": {"1": vdd, "2": "PGND"},
                "note": f"PLACEHOLDER 0603 100 nF symbol for {value} at {ic}; MPN TO ASSIGN",
            }
    return out


# Real peripherals a SPICE deck cannot express: EN/RUN default levels, the
# manual run jumper, the EN filter and per-IC VDD decoupling.  Their nets come
# from design/v1/pin_connections.csv (pin *positions* and local circuits) and
# the BOM row's frozen values, not from the deck, so they live in their own
# table.  Folding them into the golden netlist would erase the fact that the
# simulation never modelled them and make "deck complete" look like "board
# complete".
PERIPHERALS: dict[str, dict[str, object]] = {
    "R7": {"part": "R0603_10k", "value": "10 k", "pads": {"1": "RUN", "2": "PGND"},
           "note": "PLACEHOLDER 0603 10k; BOM value frozen (EN pull-down), MPN TO ASSIGN"},
    "R8": {"part": "R0603_10k", "value": "1 k", "pads": {"1": "VCC12", "2": "RUN"},
           "note": "PLACEHOLDER 0603 10k symbol for a 1k RUN jumper; MPN TO ASSIGN"},
    "R9": {"part": "R0603_10k", "value": "10 k", "pads": {"1": "GD1", "2": "PGND"},
           "note": "PLACEHOLDER 0603 10k; BOM value frozen (HI pull-down), MPN TO ASSIGN"},
    "R10": {"part": "R0603_10k", "value": "10 k", "pads": {"1": "GD2", "2": "PGND"},
            "note": "PLACEHOLDER 0603 10k; BOM value frozen (LI pull-down), MPN TO ASSIGN"},
    "C13": {"part": "C0603_100n", "value": "1 nF", "pads": {"1": "RUN", "2": "PGND"},
            "note": "PLACEHOLDER 0603 100 nF symbol for a 1 nF EN filter; MPN TO ASSIGN"},
    **_decoupling(),
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
for _r in ("R1", "R2", "R4", "R5", "R15", "R16", "R17", "R18", "R19"):
    PLACEHOLDER[_r] = "PLACEHOLDER 0603 10k; value is TO ASSIGN"
# R3 is the OC burden: the BOM freezes 10 ohm, but the 0805 0.125 W part is
# ruled out by the measured 125.7 mW continuous burden, so package and MPN are
# back to selection while the resistance is not.
PLACEHOLDER["R3"] = ("PLACEHOLDER 0603 10k; BOM freezes a 10 ohm OC burden, but the "
                     "0805 0.125 W part fails at 125.7 mW (mean(V^2)/R), so the "
                     "resistance is frozen and the package/MPN are TO SELECT")
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


def project_library(spec: dict) -> dict[str, dict]:
    """Reshape project_symbols.json into the same record shape as the pin dump.

    Keeping one shape means ``pads_for``/``basis_for`` need no special case for
    custom parts, and a project device can never be mistaken for a measured
    system one: the ``library`` field says which it is.
    """
    out: dict[str, dict] = {}
    for name, sym in spec["symbols"].items():
        fp = sym["placeholder_footprint"]
        out[name] = {
            "mpn": name,
            "lcsc": "",
            "footprint": fp["name"],
            "uuid": sym["device_uuid"],
            "library": "project",
            "footprint_uuid": fp["uuid"],
            "pins": [{"num": p["num"], "nm": p["name"]} for p in sym["pins"]],
        }
    return out


def load_library(pins: Path = PINS, symbols: Path = PROJECT_SYMBOLS) -> dict[str, dict]:
    """Measured system-library pins, with the project-library symbols merged in."""
    library = json.loads(pins.read_text(encoding="utf-8"))
    library.update(project_library(json.loads(symbols.read_text(encoding="utf-8"))))
    return library


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
    if part in MAGNETIC_PARTS:
        return ("logical terminal name equals native symbol pin number; "
                "physical terminal drawing NOT verified")
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
    plan: dict[str, object] = {"refs": {}, "unverified_magnetics": dict(MAGNETIC_UNVERIFIED),
                               "unresolved": []}
    rows: list[dict[str, str]] = []

    for ref, pins in golden.items():
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
        # A magnetic's nets are wired correctly but its pads are logical names,
        # so calling the row MAPPED would read as a completed physical map.
        magnetic = part in MAGNETIC_PARTS
        status = "OPEN - REASON GIVEN" if magnetic else "MAPPED"
        note = MAGNETIC_NOTE.get(ref, PLACEHOLDER.get(ref, ""))
        pad_nets: dict[str, str] = {}
        for pin, net in pins.items():
            for pad in pads_for(part, pin, symbol_pins):
                if pad in pad_nets and pad_nets[pad] != net:
                    raise MappingError(f"{ref}: pad {pad} claimed by {pad_nets[pad]} and {net}")
                pad_nets[pad] = net
                rows.append({
                    **common, "golden_pin": pin, "pad": pad, "net": net,
                    "basis": basis_for(part, pin, symbol_pins),
                    "review_status": status,
                    "note": note,
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
            # placement needs to know which library holds the device, and which
            # footprint name to stamp on the instance (a project device has no
            # device-level footprint; without the property the netlist export
            # returns null for the whole sheet)
            "library": dev.get("library", "system"),
            "footprint": {"name": str(dev.get("footprint") or ""),
                          "uuid": dev.get("footprint_uuid")},
            "unverified": bool(magnetic),
        }

    for ref, spec in PERIPHERALS.items():
        part = str(spec["part"])
        dev = library.get(part)
        if dev is None:
            raise MappingError(f"{ref}: no library dump for {part}")
        symbol_pins = {p["num"] for p in dev["pins"]}
        pad_nets = dict(spec["pads"])  # type: ignore[arg-type]
        unknown = set(pad_nets) - symbol_pins
        if unknown:
            raise MappingError(f"{ref}: pads {sorted(unknown)} do not exist on {part}")
        common = {
            "ref": ref, "section": section_of(ref) or "", "mpn": dev["mpn"],
            "lcsc": str(dev.get("lcsc") or ""), "footprint": str(dev.get("footprint") or ""),
        }
        for pad, net in pad_nets.items():
            rows.append({
                **common, "golden_pin": "", "pad": pad, "net": net,
                "basis": "BOM peripheral; net from design/v1/pin_connections.csv",
                "review_status": "MAPPED",
                "note": str(spec["note"]),
            })
        for pad in sorted(symbol_pins - set(pad_nets)):
            rows.append({
                **common, "golden_pin": "", "pad": pad, "net": "",
                "basis": "none - not yet decided",
                "review_status": "OPEN - NEEDS DECISION",
                "note": "NOT WIRED - unassigned pad, investigate",
            })
        plan["refs"][ref] = {
            "part": part, "uuid": dev["uuid"], "pads": pad_nets,
            "section": section_of(ref), "peripheral": True,
            "library": dev.get("library", "system"),
            "footprint": {"name": str(dev.get("footprint") or ""),
                          "uuid": dev.get("footprint_uuid")},
            "unverified": False,
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
    ap.add_argument("--symbols", type=Path, default=PROJECT_SYMBOLS)
    args = ap.parse_args(argv)

    library = load_library(args.pins, args.symbols)
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

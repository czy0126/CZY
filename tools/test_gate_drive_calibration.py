"""Pin the gate-drive calibration to the datasheets.

Two numbers have been floating around the project without a shared definition:

  * `design/v1/pin_connections.csv` says the external gate resistor is 2.2 ohm,
  * the simulated decks say Rgh/Rgl = 3.2 ohm.

They are not the same quantity, and the datasheets say which is which:

  * `models/sr_timing_v3.lib` drives the SR gates as a Thevenin source with
    8.7 ohm on the way up and 3.1 ohm on the way down.  The UCC24624 specifies
    RVG_PU 6.5 ohm typ and RVG_PD 0.9 ohm typ, so 8.7 = 6.5 + 2.2 and
    3.1 = 0.9 + 2.2.  The external resistor in that model *is* the pin map's 2.2.
  * the half-bridge deck instead puts an ideal source behind one 3.2 ohm lump.
    The UCC27282 is a different output stage: 0.13 V at -100 mA (1.3 ohm) up and
    0.085 V at +100 mA (0.85 ohm) down, so with the same 2.2 ohm external the
    real path is 3.5 ohm up and 3.05 ohm down.  A single 3.2 ohm lump sits
    between them, which is why the deck is a fair approximation and why 2.2 ohm
    is still the number that goes on the board.

These tests fail if anyone edits the model, the datasheets' numbers, or the pin
map without keeping that arithmetic true.  The UCC27282 rows have no MIN column
in the extraction, so the two values are read as TYP and MAX; that reading is
asserted rather than assumed.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "models/sr_timing_v3.lib"
UCC24624 = ROOT / "references/datasheets/ucc24624.txt"
UCC27282 = ROOT / "references/datasheets/ucc27282.txt"
PIN_MAP = ROOT / "design/v1/pin_connections.csv"
DECK = ROOT / "sim/v3/sr_tank_dual_v33_ss_1ms_100a.cir"

R_EXT_OHM = 2.2


def lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def numbers_after(path: Path, label: str, count: int) -> list[float]:
    """The first `count` numeric-only lines following `label`."""
    text = lines(path)
    start = next(i for i, line in enumerate(text) if line.strip() == label)
    out: list[float] = []
    for line in text[start + 1:]:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            out.append(float(stripped))
        except ValueError:
            if out:
                break
        if len(out) == count:
            break
    assert len(out) == count, f"{label}: found {out}"
    return out


def timing_model_impedances() -> tuple[float, float]:
    """(source, sink) ohms out of the 'if(V(drv,S)>V(G,S),8.7,3.1)' expression."""
    match = re.search(r"if\(V\(drv,S\)>V\(G,S\),([0-9.]+),([0-9.]+)\)", LIB.read_text(encoding="utf-8"))
    assert match, "sr_timing_v3.lib no longer has the expected drive expression"
    return float(match.group(1)), float(match.group(2))


def test_the_sr_timing_model_is_the_ucc24624_plus_the_external_resistor():
    source, sink = timing_model_impedances()
    pu_min, pu_typ, pu_max = numbers_after(UCC24624, "VG pull-up resistance", 3)
    pd_min, pd_typ, pd_max = numbers_after(UCC24624, "VG pull-down resistance", 3)
    assert pu_min < pu_typ < pu_max and pd_min < pd_typ < pd_max
    assert source == pytest.approx(pu_typ + R_EXT_OHM, abs=0.05)
    assert sink == pytest.approx(pd_typ + R_EXT_OHM, abs=0.05)


def test_the_primary_driver_has_a_different_output_stage():
    """UCC27282 is ~1.3 / 0.85 ohm, not the UCC24624's 6.5 / 0.9 -- the two share no model."""
    v_low, v_low_max = numbers_after(UCC27282, "ILO = 100 mA", 2)
    v_high, v_high_max = numbers_after(UCC27282, "ILO = -100 mA, VLOH = VDD – VLO", 2)
    assert v_low < v_low_max and v_high < v_high_max      # TYP then MAX, no MIN column
    r_sink = v_low / 0.1
    r_source = v_high / 0.1
    assert r_sink == pytest.approx(0.85, abs=0.01)
    assert r_source == pytest.approx(1.3, abs=0.01)
    pu_typ = numbers_after(UCC24624, "VG pull-up resistance", 3)[1]
    assert r_source < pu_typ / 2, "a 6.5 ohm model would make the primary turn-on far too slow"


def test_the_deck_lump_sits_between_the_two_ucc27282_paths():
    """3.05 ohm sinking < 3.2 ohm simulated < 3.5 ohm sourcing."""
    r_sink = 0.85 + R_EXT_OHM
    r_source = 1.3 + R_EXT_OHM
    deck = []
    for line in lines(DECK):
        if line.startswith(("Rgh ", "Rgl ")):
            deck.append(float(line.split()[3]))
    assert deck == [3.2, 3.2]
    assert r_sink <= deck[0] <= r_source


def test_the_pin_map_puts_2r2_on_every_gate():
    with PIN_MAP.open(encoding="utf-8-sig", newline="") as fh:
        gates = [row for row in csv.DictReader(fh) if re.search(r"2\.2ohm\s*->\s*\S+\.G", row["connection"])]
    # QH, QL and eight SR gates
    assert len(gates) == 10
    assert all("2.2ohm" in row["connection"] for row in gates)

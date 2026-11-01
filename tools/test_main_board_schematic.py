"""Guard the golden-netlist -> library-pad mapping.

The thing worth testing is not that the code runs; it is that no golden pin is
dropped on the floor.  A FET whose ``S`` lands on one pad instead of three
still produces a netlist that matches the deck, because the deck only ever had
one ``S``.  These tests re-derive the expansion from the measured pin dumps so
a library update that renumbers pads cannot pass silently.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

import main_board_schematic as mbs

ROOT = Path(__file__).resolve().parent.parent
LIBRARY = json.loads((ROOT / "hardware/dcx_main/library_pins.json").read_text(encoding="utf-8"))
GOLDEN = mbs.load_golden()


def plan() -> dict:
    return mbs.build_plan(GOLDEN, LIBRARY)


def test_every_golden_ref_is_either_placed_or_named_as_a_gap():
    p = plan()
    unresolved = {u["ref"] for u in p["unresolved"]}
    assert unresolved | set(p["refs"]) == set(GOLDEN), "a ref vanished without a reason"
    assert unresolved == set(mbs.MAGNETIC_GAPS)


def test_every_golden_pin_lands_on_at_least_one_pad():
    p = plan()
    for ref, pins in GOLDEN.items():
        if ref in mbs.MAGNETIC_GAPS:
            continue
        got = p["refs"][ref]["pads"]
        for pin in pins:
            assert pin in [
                r["golden_pin"] for r in p["review_rows"] if r["ref"] == ref
            ], f"{ref}.{pin} was dropped"


def test_the_fet_expansion_matches_the_measured_pin_names():
    """Re-derive G/S/D groups from the library dump rather than trusting the
    constants.  If a future library version renumbers the TDSON pads this is
    the test that should go red."""
    for part in ("CSD19531Q5A", "BSC010N04LS6"):
        by_name: dict[str, set[str]] = {}
        for pin in LIBRARY[part]["pins"]:
            by_name.setdefault(pin["nm"], set()).add(pin["num"])
        for name, pads in mbs.FET_EXPANSION[part].items():
            assert set(pads) == by_name[name], (part, name, pads, by_name[name])
        assert set(mbs.FET_EXPANSION[part]) == set(by_name), (
            f"{part} has pin names {sorted(by_name)} the expansion does not cover")


def test_the_exposed_pad_of_the_primary_fet_is_a_drain():
    """The DFN-8's ninth pad is the thermal pad and is electrically D.  Leaving
    it out would give a board whose drain current has nowhere to go."""
    assert "9" in mbs.FET_EXPANSION["CSD19531Q5A"]["D"]
    names = {p["num"]: p["nm"] for p in LIBRARY["CSD19531Q5A"]["pins"]}
    assert names["9"] == "D"


def test_the_half_bridge_driver_exposed_pad_is_bonded_not_floating():
    """UCC27282 is a 9-pin netlist on an 11-pad package.  The golden netlist
    cannot express EP, so the review sheet has to say what happens to it.

    Leaving EP floating was the earlier behaviour and is wrong: on a VSON-10 it
    is the thermal path and the reference the gate driver switches against.
    It is bonded to PGND, and must be reported as a bond the *deck* never asked
    for rather than quietly added to the golden nets."""
    p = plan()
    rows = [r for r in p["review_rows"] if r["ref"] == "U2"]
    assert {r["pad"] for r in rows} == {s["num"] for s in LIBRARY["UCC27282DRCR"]["pins"]}
    ep = next(r for r in rows if r["pad"] == "11")
    assert ep["net"] == mbs.BONDED_PADS["UCC27282DRCR"]["11"]
    assert "BONDED BY DESIGN" in ep["note"]
    # the other unconnected pad keeps an explicit reason instead of a blank
    nc = next(r for r in rows if r["pad"] == "2")
    assert nc["net"] == "" and nc["note"] == mbs.UNCONNECTED["UCC27282DRCR"]["2"]


def test_an_unknown_golden_pin_raises_instead_of_being_ignored():
    with pytest.raises(mbs.MappingError):
        mbs.pads_for("UCC25600D", "nonsense", {"1", "2"})


def test_placing_the_same_pad_twice_with_different_nets_is_rejected(monkeypatch):
    """Two golden pins that expand onto one pad with different nets is a short
    in the making -- it must raise, not silently keep the last one."""
    golden = {"SR1A": {"S": "PGND", "G": "GA1", "D": "SEC1_A"}}
    monkeypatch.setitem(mbs.FET_EXPANSION, "BSC010N04LS6",
                        {"G": ("4",), "S": ("1", "2", "3"), "D": ("3",)})
    with pytest.raises(mbs.MappingError):
        mbs.build_plan(golden, LIBRARY)


def test_the_review_sheet_says_which_parts_are_placeholders():
    p = plan()
    notes = {r["ref"]: r["note"] for r in p["review_rows"]}
    assert notes["Lr"].startswith("PLACEHOLDER")
    assert "ELP32" in notes["Lr"]
    # a part that is genuinely the design part carries no placeholder note
    assert notes["U1"] == ""


def test_golden_netlist_pin_count_is_still_193():
    """A change here means the deck changed; every downstream artifact (the
    plan, the review CSV, the native schematic) then needs regenerating."""
    assert sum(len(v) for v in GOLDEN.values()) == 193
    assert len(GOLDEN) == 66


def test_the_written_review_sheet_matches_a_fresh_build(tmp_path):
    p = plan()
    out = tmp_path / "review.csv"
    mbs.write_review(p["review_rows"], out)
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert len(rows) == len(p["review_rows"])
    assert set(rows[0]) == {"ref", "mpn", "lcsc", "footprint", "golden_pin", "pad", "net", "note"}
    assert all(r["net"] for r in rows if r["golden_pin"]), "a wired pad has no net"

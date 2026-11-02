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
_PINS = json.loads((ROOT / "hardware/dcx_main/library_pins.json").read_text(encoding="utf-8"))
_SYMBOLS = json.loads((ROOT / "hardware/dcx_main/project_symbols.json").read_text(encoding="utf-8"))
LIBRARY = mbs.load_library()
GOLDEN = mbs.load_golden()


def plan() -> dict:
    return mbs.build_plan(GOLDEN, LIBRARY)


def test_every_golden_ref_is_placed():
    """Nothing is left unplaced now that the magnetics have native symbols.
    Before this, the five of them were the whole 'unresolved' list."""
    p = plan()
    assert p["unresolved"] == []
    assert set(p["refs"]) == set(GOLDEN) | set(mbs.PERIPHERALS)


def test_every_golden_pin_lands_on_at_least_one_pad():
    p = plan()
    for ref, pins in GOLDEN.items():
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
    assert set(rows[0]) == {"ref", "section", "mpn", "lcsc", "footprint", "golden_pin",
                            "pad", "net", "basis", "review_status", "note"}
    assert all(r["net"] for r in rows if r["golden_pin"]), "a wired pad has no net"


def test_every_placed_ref_sits_in_exactly_one_section():
    """The six blocks are the drawing order.  A part in no section would be
    placed at an arbitrary spot; a part in two would be placed twice."""
    seen: dict[str, str] = {}
    for title, refs in mbs.SECTIONS:
        for ref in refs:
            assert ref not in seen, f"{ref} is in {seen[ref]!r} and {title!r}"
            seen[ref] = title
    expected = set(GOLDEN) | set(mbs.PERIPHERALS)
    assert set(seen) == expected, (
        f"not sectioned: {sorted(expected - set(seen))}; "
        f"sectioned but unknown: {sorted(set(seen) - expected)}")


def test_every_review_row_carries_a_status_and_a_basis():
    """An empty status cell is indistinguishable from a reviewed one."""
    rows = plan()["review_rows"]
    assert all(r["review_status"] for r in rows)
    assert all(r["basis"] for r in rows)
    statuses = {r["review_status"] for r in rows}
    assert statuses <= {"MAPPED", "BONDED BY DESIGN",
                        "OPEN - REASON GIVEN", "OPEN - NEEDS DECISION"}, statuses
    # nothing may be left in the "needs decision" bucket on a finished sheet
    assert "OPEN - NEEDS DECISION" not in statuses, [
        (r["ref"], r["pad"]) for r in rows if r["review_status"] == "OPEN - NEEDS DECISION"]


def test_the_seventeen_real_peripherals_are_declared():
    """The BOM gap is 17 refs: four U2 defaults, the EN filter and 12
    decouplers.  Dropping one silently would put the fabrication gate back to
    where it started."""
    assert set(mbs.PERIPHERALS) == (
        {"R7", "R8", "R9", "R10", "C13"} | {f"C{i}" for i in range(101, 113)})
    assert len(mbs.PERIPHERALS) == 17


def test_each_controller_gets_one_1u_and_one_100n():
    """The BOM fixes the values per IC but not the designator; the pairing is
    the design decision this table makes."""
    ics = (("U1", "VCC12"), ("U2", "VCC12"), ("U3", "VCC12_S"),
           ("U4", "VCC12_S"), ("U5", "VCC12_S"), ("U6", "VCC12_S"))
    for i, (ic, vdd) in enumerate(ics):
        for j, value in enumerate(("1 uF", "100 nF")):
            spec = mbs.PERIPHERALS[f"C{101 + 2 * i + j}"]
            assert spec["pads"] == {"1": vdd, "2": "PGND"}, ic
            assert spec["value"] == value, ic


def test_every_peripheral_net_is_a_net_the_golden_netlist_already_uses():
    """A typo such as 12V_P (the pin-connections name) or SGND would create a
    silently floating part: the native export would show a net no golden pin
    shares, which is exactly how a decoupler fails without anyone noticing."""
    golden_nets = {net for pins in GOLDEN.values() for net in pins.values()}
    for ref, spec in mbs.PERIPHERALS.items():
        for net in spec["pads"].values():
            assert net in golden_nets, f"{ref} claims net {net!r}, which no golden pin uses"


def test_peripherals_reach_the_review_sheet_as_placeholders():
    rows = [r for r in plan()["review_rows"] if r["ref"] in mbs.PERIPHERALS]
    assert {r["ref"] for r in rows} == set(mbs.PERIPHERALS)
    assert all(r["review_status"] == "MAPPED" for r in rows)
    assert all("PLACEHOLDER" in r["note"] for r in rows), [
        r["ref"] for r in rows if "PLACEHOLDER" not in r["note"]]


def test_a_peripheral_on_a_pad_the_symbol_lacks_raises(monkeypatch):
    monkeypatch.setitem(mbs.PERIPHERALS, "R7", {
        "part": "R0603_10k", "value": "10 k", "pads": {"3": "RUN"},
        "note": "deliberately broken"})
    with pytest.raises(mbs.MappingError):
        mbs.build_plan(GOLDEN, LIBRARY)


def test_magnetics_are_placed_in_a_section():
    """Their block must exist on the sheet, and now they are drawn in it."""
    p = plan()
    for ref in mbs.MAGNETIC_UNVERIFIED:
        assert mbs.section_of(ref) is not None, f"{ref} belongs to no section"
        assert ref in p["refs"], f"{ref} is sectioned but not placed"


def test_a_placed_magnetic_is_never_reported_as_mapped():
    """The pins are logical terminal names.  Marking the row MAPPED would say
    the physical pad map is done, which is the one claim this board cannot
    make yet."""
    p = plan()
    for ref in mbs.MAGNETIC_UNVERIFIED:
        rows = [r for r in p["review_rows"] if r["ref"] == ref]
        assert rows, ref
        assert all(r["review_status"] == "OPEN - REASON GIVEN" for r in rows), ref
        assert all("NOT verified" in r["basis"] for r in rows), ref
        assert all("PLACEHOLDER" in r["note"] for r in rows), ref
        assert p["refs"][ref]["unverified"] is True, ref


def test_the_magnetic_symbols_use_the_logical_terminal_names_as_pin_numbers():
    """Inventing '1-5' would look like a vendor terminal drawing.  The numbers
    are the same names the golden netlist uses, so the diff stays meaningful."""
    for name, sym in _SYMBOLS["symbols"].items():
        nums = [p["num"] for p in sym["pins"]]
        assert nums == [p["name"] for p in sym["pins"]], name
        assert all(not n.isdigit() for n in nums), name
        assert len(set(nums)) == len(nums), name


def test_project_symbols_start_from_the_measured_pin_dump():
    """load_library must not silently drop or renumber the measured devices."""
    assert set(_PINS) <= set(LIBRARY)
    for name in _PINS:
        assert LIBRARY[name]["pins"] == _PINS[name]["pins"], name
    for name in _SYMBOLS["symbols"]:
        assert LIBRARY[name]["library"] == "project", name
        assert LIBRARY[name]["footprint_uuid"], name


def test_a_project_device_that_lost_its_symbol_raises(monkeypatch):
    """Placement of a magnetic needs the recorded device uuid.  If the symbol
    is absent from the merged library the plan must say so, not invent pads."""
    broken = dict(LIBRARY)
    broken.pop("DCX_CT_4P")
    p = mbs.build_plan(GOLDEN, broken)
    assert {"ref": "CT", "reason": "no library dump for DCX_CT_4P"} in p["unresolved"]
    assert "CT" not in p["refs"]

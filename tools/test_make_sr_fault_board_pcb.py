"""Tests for the SR validation board's layout pass 1.

The generator is only useful if four things hold, and none of them are "the
script ran":

* every pad on the board carries exactly the net the schematic gave it -- a
  board whose pads are all netless opens, looks fine and DRCs *clean*, because
  nothing is connected;
* courtyards are placed where the library puts them, which is not always
  centred on the footprint origin (the MX126 terminal block runs from -3.5 to
  +8 mm in x, the four-pin one to +18 mm);
* no part is rotated, because kicad-cli 10.0.6 flags any rotated footprint as
  ``lib_footprint_mismatch`` and the honest response is to keep the parts
  upright, not to silence the check;
* the DRC reader sees ``unconnected_items``, which kicad-cli writes to a
  separate top-level array from ``violations``.

Run:
    python -m pytest tools/test_make_sr_fault_board_pcb.py -q
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import main_board_mechanical as mbm
import make_sr_fault_board as sch
import make_sr_fault_board_pcb as pcb

OUT = pcb.OUT
DRC = OUT / "drc.json"


# ---------------------------------------------------------------- helpers
def _normalised(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def _footprints(text: str) -> list[tuple[str, float, float, float, list[dict]]]:
    """``(ref, x, y, rot, pads)`` for every footprint on the board.

    Parsed straight out of the ``.kicad_pcb`` rather than read back from the
    generator's own tables: reading the generator's answer back would test
    nothing.
    """
    out = []
    i = 0
    while True:
        j = text.find('(footprint "', i)
        if j < 0:
            return out
        end = sch.block_end(text, j)
        fp = text[j:end]
        at = re.search(r"\(at ([-\d.]+) ([-\d.]+) ([-\d.]+)\)", fp)
        ref = re.search(r'\(property "Reference" "([^"]+)"', fp)
        pads = []
        k = 0
        while True:
            m = fp.find('(pad "', k)
            if m < 0:
                break
            pend = sch.block_end(fp, m)
            blk = fp[m:pend]
            num = re.match(r'\(pad "([^"]*)"', blk).group(1)
            net = re.search(r'\(net (\d+) "([^"]*)"\)', blk)
            pads.append({"number": num,
                         "net": net.group(2) if net else None,
                         "index": int(net.group(1)) if net else None})
            k = pend
        out.append((ref.group(1), float(at.group(1)), float(at.group(2)),
                    float(at.group(3)), pads))
        i = end


@pytest.fixture(scope="module")
def board_text() -> str:
    return (OUT / pcb.BOARD).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def placed() -> list[pcb.Placed]:
    return pcb.placement()


# ---------------------------------------------------------------- geometry
def test_the_terminal_block_courtyard_is_not_centred():
    """The reason ``Placed`` carries a box instead of a width.

    Treating the box as centred on the origin would place this part 2.25 mm to
    the left and its four-pin sibling 7.25 mm to the left -- more than the
    0.75 mm gap the packer claims to keep.
    """
    x0, y0, x1, y1 = pcb.bounds("TerminalBlock:TerminalBlock_MaiXu_MX126-5.0-02P_1x02_P5.00mm")
    assert x0 == pytest.approx(-3.5)
    assert x1 == pytest.approx(8.0)
    assert (x0 + x1) / 2 > 2.0, "this part is only useful as a test if it is off-centre"

    x0, _, x1, _ = pcb.bounds("TerminalBlock:TerminalBlock_MaiXu_MX126-5.0-04P_1x04_P5.00mm")
    assert x1 - x0 == pytest.approx(21.5)
    assert (x0 + x1) / 2 > 7.0


def test_a_placed_part_translates_its_whole_box(placed):
    """``rect`` must be the origin plus the local box, not a box around the origin."""
    for p in placed:
        x0, y0, x1, y1 = p.bounds
        assert p.rect == (p.x + x0, p.y + y0, p.x + x1, p.y + y1), p.ref


def test_every_part_is_inside_the_outline(placed):
    for p in placed:
        x0, y0, x1, y1 = p.rect
        assert 0.0 <= x0 and x1 <= pcb.BOARD_W_MM, p.ref
        assert 0.0 <= y0 and y1 <= pcb.BOARD_D_MM, p.ref


def test_no_two_courtyards_are_closer_than_the_gap(placed):
    rects = [(p.ref, p.rect) for p in placed]
    for i, (ra, a) in enumerate(rects):
        for rb, b in rects[i + 1:]:
            assert not pcb._overlaps(a, b, pcb.GAP_MM), f"{ra} and {rb} overlap"
    for i, hole in enumerate(pcb._hole_rects(), start=1):
        for ref, r in rects:
            assert not pcb._overlaps(hole, r, pcb.GAP_MM), f"H{i} and {ref} overlap"


# ---------------------------------------------------------------- placement
def test_every_footprinted_part_is_placed_exactly_once(placed):
    table = [p for p in sch.parts() if p.footprint]
    refs = [p.ref for p in placed]
    assert len(refs) == len(set(refs)) == len(table)
    assert set(refs) == {p.ref for p in table}


def test_no_part_is_rotated(placed):
    """kicad-cli 10.0.6 reports any rotated footprint as lib_footprint_mismatch.

    Rotating a part to make DRC quiet would be trading a real layout for a
    suppressed finding, so the placement keeps every part upright.
    """
    assert {p.rot for p in placed} == {0.0}


def test_a_rotation_is_refused_with_the_reason(monkeypatch):
    monkeypatch.setitem(pcb.FIXED, "R1", (74.0, 50.0, 90.0))
    with pytest.raises(SystemExit) as err:
        pcb.placement()
    assert "lib_footprint_mismatch" in str(err.value)


def test_a_part_in_two_blocks_is_refused(monkeypatch):
    monkeypatch.setitem(pcb.BLOCK_ORDER, "fault", pcb.BLOCK_ORDER["fault"] + ["Rg1"])
    with pytest.raises(SystemExit) as err:
        pcb._assignment([p for p in sch.parts() if p.footprint])
    assert "Rg1" in str(err.value)


# ---------------------------------------------------------------- nets
def test_every_pad_carries_the_schematic_net(board_text, placed):
    """A netless board is a drawing; this is what makes it a layout.

    Every symbol pin that has a pad gets that net; every pad the schematic does
    not name (``#NC`` or a pad with no schematic pin) stays netless, which is
    deliberate -- a no-connect must not be quietly tied to something.  The pins
    with no pad of their own are the ones the report names, no others.
    """
    data = pcb.report(placed)
    mapping = data["pad_pin_mapping"]["symbol_pins_without_a_pad"]
    table = {p.ref: p for p in sch.parts() if p.footprint}
    seen = set()
    for ref, _, _, _, pads in _footprints(board_text):
        part = table.get(ref)
        if part is None:
            assert re.fullmatch(r"H[1-4]", ref), f"{ref} is on the board but not in the table"
            continue
        seen.add(ref)
        expected = {num: name for num, name in part.nets.items() if name != sch.NC}
        unmapped = set(expected) - {pad["number"] for pad in pads}
        got = {pad["number"]: pad["net"] for pad in pads if pad["net"]}
        assert got == {k: v for k, v in expected.items() if k not in unmapped}, ref
        assert unmapped == set(mapping.get(ref, [])), ref
    assert seen == set(table)


def test_the_drain_lands_share_one_pad_number_and_that_is_reported(placed):
    """The vendored TDSON-8 numbers all five drain lands "5"; the symbol models
    the real device, whose drain is pins 5-8.  All five lands still carry the
    drain net, so nothing floats -- but the gap is stated, not rounded off."""
    data = pcb.report(placed)
    assert data["pad_pin_mapping"]["symbol_pins_without_a_pad"] == {
        "Q1": ["6", "7", "8"], "Q2": ["6", "7", "8"]}
    pads = pcb.pad_numbers("Package_SON:Infineon_PG-TDSON-8_6.15x5.15mm")
    assert pads.count("5") == 5
    assert {"6", "7", "8"}.isdisjoint(pads)
    text = (OUT / pcb.BOARD).read_text(encoding="utf-8")
    for ref, _, _, _, ps in _footprints(text):
        if ref not in ("Q1", "Q2"):
            continue
        drain = [p for p in ps if p["number"] == "5"]
        assert len(drain) == 5
        assert {p["net"] for p in drain} == {"SEC_A" if ref == "Q1" else "SEC_B"}


def test_a_pad_the_schematic_never_names_stays_netless(board_text):
    """SOT-23 is the three-pin package for a two-pin zener: pad 3 exists and is
    left unconnected.  Unused copper is fine; copper tied to an undeclared net
    would not be -- that is how a stray short gets onto a board."""
    table = {p.ref: p for p in sch.parts() if p.footprint}
    spare = 0
    for ref, _, _, _, pads in _footprints(board_text):
        part = table.get(ref)
        if part is None:
            continue
        for pad in pads:
            if pad["number"] in part.nets and part.nets[pad["number"]] != sch.NC:
                continue
            assert pad["net"] is None, (ref, pad["number"])
            spare += 1
    assert spare, "no unused pad anywhere: the assertion above checked nothing"


def test_every_pad_net_index_points_at_the_right_name(board_text):
    names = {i: name for i, name in enumerate(pcb.net_table(
        [p for p in sch.parts() if p.footprint]))}
    for _, _, _, _, pads in _footprints(board_text):
        for pad in pads:
            if pad["net"]:
                assert names[pad["index"]] == pad["net"]


def test_the_board_has_no_tracks_or_vias(board_text):
    assert "(segment " not in board_text
    assert "(via " not in board_text
    assert "(zone " not in board_text


def test_the_fp_lib_table_points_only_at_vendored_or_generated_libraries():
    table = pcb.fp_lib_table()
    for uri in re.findall(r'\(uri "([^"]+)"\)', table):
        assert uri.startswith("${KIPRJMOD}"), uri
    assert "stock_footprints" in table and "dcx.pretty" in table


# ---------------------------------------------------------------- assembly
def test_the_board_and_the_bom_list_the_same_parts(placed):
    """The BOM is read back from disk, so this compares two artefacts rather
    than the generator against itself."""
    data = pcb.report(placed)
    a = data["assembly_review"]
    assert a["source"] == "BOM.csv beside the board file"
    assert a["bom_rows"] == a["parts_on_board"] == 71
    assert a["in_bom_but_not_on_the_board"] == []
    assert a["on_the_board_but_not_in_the_bom"] == []
    assert a["value_or_footprint_mismatch"] == []
    assert a["duplicate_bom_rows"] == []
    assert data["checks"]["the_bom_and_the_board_are_the_same_parts"] is True


def test_the_assembly_review_can_fail(tmp_path, monkeypatch, placed):
    """A check that cannot go red is not a check."""
    import csv as _csv
    rows = list(_csv.DictReader((OUT / "BOM.csv").open(encoding="utf-8", newline="")))
    keep = [r for r in rows if r["Reference"] != "Rsh1"]
    for r in keep:
        if r["Reference"] == "Rg1":
            r["Value"] = "wrong"
    with (tmp_path / "BOM.csv").open("w", encoding="utf-8", newline="") as fh:
        w = _csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(keep + [dict(keep[0])])          # duplicate one row as well
    monkeypatch.setattr(pcb, "OUT", tmp_path)
    table = {p.ref: p for p in sch.parts() if p.footprint}
    a = pcb.assembly_review(placed, table)
    assert a["on_the_board_but_not_in_the_bom"] == ["Rsh1"]
    assert a["value_or_footprint_mismatch"] == ["Rg1"]
    assert a["duplicate_bom_rows"] == [keep[0]["Reference"]]


def test_the_through_hole_parts_are_the_connectors(placed):
    """A position file would need to know these are hand-soldered, not placed."""
    a = pcb.report(placed)["assembly_review"]
    assert a["through_hole_refs"] == ["J1", "J2", "J3", "J4", "JP1", "JP2", "JP3"]
    assert "position file" in a["position_file_note"]


def test_the_dnp_parts_are_still_placed(placed):
    """DNP means "do not populate", not "do not place": the pads have to exist."""
    data = pcb.report(placed)
    dnp = data["assembly_review"]["dnp_parts_placed"]
    assert len(dnp) == 10
    on_board = {p.ref for p in placed}
    assert set(dnp) <= on_board


# ---------------------------------------------------------------- DRC reader
def test_the_drc_reader_sees_unconnected_items(tmp_path):
    """kicad-cli writes ``unconnected_items`` to its own top-level array.

    A reader that opens only ``violations`` therefore reports zero unconnected
    items on a board carrying a hundred, and the guard "an unrouted board with
    no ratsnest means the netlist never reached the board" fires backwards.
    """
    path = tmp_path / "drc.json"
    path.write_text(json.dumps({
        "violations": [{"type": "silk_overlap"}],
        "unconnected_items": [{"type": "unconnected_items"}] * 3,
        "schematic_parity": [{"type": "missing_footprint"}],
    }), encoding="utf-8")
    items = pcb.drc_items(path)
    assert len(items["violations"]) == 1
    assert len(items["unconnected_items"]) == 3
    assert len(items["schematic_parity"]) == 1


def test_a_missing_drc_file_is_not_read_as_a_clean_board(tmp_path):
    items = pcb.drc_items(tmp_path / "absent.json")
    assert items == {name: [] for name in pcb.DETAIL_ARRAYS}


@pytest.mark.skipif(not DRC.exists(), reason="no drc.json in this checkout")
def test_the_committed_drc_found_no_placement_defect():
    items = pcb.drc_items()
    real = [v for v in items["violations"] if v["type"] in pcb.PLACEMENT_ERRORS]
    assert real == []
    assert items["schematic_parity"] == []


@pytest.mark.skipif(not DRC.exists(), reason="no drc.json in this checkout")
def test_the_routing_backlog_covers_every_multi_pad_net():
    """The 111 unconnected items are the routing work, not a defect.

    Two nets show fewer items than they have pads: the TDSON-8 splits its drain
    into five pad instances all numbered 5, and KiCad counts touching copper as
    one node.  That is why the invariant is "every net with at least two pads
    appears" and not "items == pads - nets".
    """
    items = pcb.drc_items()["unconnected_items"]
    assert items, "an unrouted board must have a non-empty ratsnest"
    backlog: set[str] = set()
    for item in items:
        nets = {re.search(r"\[([^\]]+)\]$", i["description"]).group(1) for i in item["items"]}
        assert len(nets) == 1, item["description"]
        backlog |= nets
    pads_per_net: dict[str, int] = {}
    for _, _, _, _, ps in _footprints((OUT / pcb.BOARD).read_text(encoding="utf-8")):
        for pad in ps:
            if pad["net"]:
                pads_per_net[pad["net"]] = pads_per_net.get(pad["net"], 0) + 1
    for name, pads in pads_per_net.items():
        if pads >= 2:
            assert name in backlog, name


def test_the_project_file_raises_missing_courtyard_to_error():
    """``missing_courtyard`` is IGNORED by default, so a board with no courtyards
    at all reports "0 violations".  The severity has to live in the project file
    because that is the only place kicad-cli reads rule severities from."""
    project = json.loads((OUT / "sr_fault_validation.kicad_pro").read_text(encoding="utf-8"))
    assert project["board"]["design_settings"]["rule_severities"]["missing_courtyard"] == "error"
    if DRC.exists():
        ignored = {row["key"] for row in
                   json.loads(DRC.read_text(encoding="utf-8")).get("ignored_checks", [])}
        assert "missing_courtyard" not in ignored


# ---------------------------------------------------------------- artefacts
def test_the_committed_board_is_what_the_generator_produces(board_text, placed):
    assert board_text == pcb.board_file(placed)


def test_the_committed_report_is_what_the_generator_produces(placed):
    on_disk = json.loads((OUT / pcb.REPORT).read_text(encoding="utf-8"))
    assert on_disk == pcb.report(placed)


def test_the_mounting_hole_library_is_generated(placed):
    lib = OUT / "dcx.pretty" / "MountingHole_3.2mm_M3.kicad_mod"
    assert lib.read_text(encoding="utf-8") == pcb.mounting_hole_source()


def test_the_honesty_flags_stay_false():
    data = pcb.report()
    assert data["routed"] is False
    assert data["hardware_built"] is False
    assert data["fabrication_approved"] is False
    assert data["manufacturing_package"] == "NOT_RELEASED"
    assert data["status"].endswith("NOT_FABRICABLE")
    assert (OUT / pcb.BOARD).read_text(encoding="utf-8").count("(segment ") == 0


def test_no_manufacturing_files_were_exported():
    """An unrouted board with a drill file looks orderable and is not."""
    for pattern in ("*.gbr", "*.drl", "*.g*", "*.pos", "*.csv.tmp"):
        assert not list(OUT.glob(pattern)), pattern


# ---------------------------------------------------------------- provenance
def test_the_vendored_footprints_match_the_installed_library():
    """Cross-check every vendored copy against a real KiCad install, if there is one."""
    share = mbm.find_kicad_share()
    if share is None:
        pytest.skip("no KiCad install found: the vendored copies were NOT compared "
                    "against the official library here")
    compared = 0
    for lib_id in sorted(set(pcb._used_footprints()) - {"dcx:MountingHole_3.2mm_M3"}):
        lib, name = lib_id.split(":", 1)
        installed = share / "footprints" / f"{lib}.pretty" / f"{name}.kicad_mod"
        if not installed.exists():
            continue
        compared += 1
        assert _normalised(pcb.stock_path(lib_id)) == _normalised(installed), (
            f"{lib_id} no longer matches the installed library -- update the copy and "
            f"hardware/stock_footprints/PROVENANCE.md together")
    assert compared, "no vendored footprint existed in this KiCad install to compare"

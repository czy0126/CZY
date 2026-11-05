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
import sys
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


def test_each_drain_pin_owns_a_land(placed):
    """The vendored TDSON-8 numbered all five drain lands "5", so the symbol's
    pins 6-8 had no copper of their own.  The digitised land pattern gives the
    four drain fingers pads 5-8 on a common base, which closes the gap -- and
    this test is what stops a future edit from quietly reverting to a generic
    footprint and re-opening it."""
    data = pcb.report(placed)
    assert data["pad_pin_mapping"]["symbol_pins_without_a_pad"] == {}
    pads = pcb.pad_numbers(pcb.BSC_LIB_ID)
    assert pads.count("5") == 2                  # the base and drain finger 5
    assert {"6", "7", "8"} <= set(pads)
    text = (OUT / pcb.BOARD).read_text(encoding="utf-8")
    for ref, _, _, _, ps in _footprints(text):
        if ref not in ("Q1", "Q2"):
            continue
        drain = [p for p in ps if p["number"] in ("5", "6", "7", "8")]
        assert len(drain) == 5
        assert {p["number"] for p in drain} == {"5", "6", "7", "8"}
        assert {p["net"] for p in drain} == {"SEC_A" if ref == "Q1" else "SEC_B"}


def test_a_pad_the_schematic_never_names_stays_netless(board_text):
    """SOT-23 is the three-pin package for a two-pin transistor: the spare pad
    is a solderable surface with no net.  Unused copper is fine; copper tied to
    an undeclared net would not be -- that is how a stray short gets onto a
    board.  (D40 used to be the example here, which is exactly why it went
    unnoticed that its *third* pad was carrying the cathode; the clamp now sits
    on a two-pad land and is checked by the test below.)"""
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


def _band_pad(lib_id: str) -> tuple[str, float]:
    """The pad that sits under the footprint's cathode band, and that band's x.

    The marking is read out of the vendored ``.kicad_mod``: the band is the one
    vertical ``F.SilkS`` line (the body outline contributes horizontal ones plus
    two vertical ends, so the band is the *shorter* vertical).  Reading the
    library is the point -- a part's polarity is a physical marking, not
    something the generator may assert about itself.
    """
    text = pcb.stock_text(lib_id)
    verticals = []
    for a, b, c, d in re.findall(
            r"\(fp_line\s*\(start ([-\d.]+) ([-\d.]+)\)\s*\(end ([-\d.]+) ([-\d.]+)\)."
            r"*?\(layer \"F\.SilkS\"\)", text, re.S):
        if a == c:
            verticals.append((float(a), abs(float(d) - float(b))))
    band_x, _ = min(verticals, key=lambda v: v[1])
    pads = [(num, float(x)) for num, x, _ in re.findall(
        r"\(pad \"(\d+)\"[^(]*\(at ([-\d.]+) ([-\d.]+)\)", text)]
    assert len(pads) == 2, (lib_id, pads)
    return min(pads, key=lambda p: abs(p[1] - band_x))


def test_the_shutdown_clamp_cathode_has_a_pad_and_lands_on_the_gate(board_text):
    """D40 must conduct: the banded pad is the cathode, and it goes to FAULT_G.

    On the previous SOT-23 land the symbol's pin 1 (K) reached pad 1 while the
    BZX84 die puts its cathode on pin 3, so ``FAULT_G`` was tied to an anode and
    ``PGND`` to a no-connect -- a clamp that never clamps, on the board whose
    job is to validate the crowbar.  A two-pad package makes the band the only
    sane reference, so the pin-to-pad mapping is settled by the marking.
    """
    d40 = next(p for p in sch.parts() if p.ref == "D40")
    band, band_x = _band_pad(d40.footprint)
    assert band == "1", f"the band sits over pad {band}, not pad 1"
    assert d40.nets["1"] == "FAULT_G"
    assert d40.nets["2"] == "PGND"
    on_board = next(pads for ref, _, _, _, pads in _footprints(board_text)
                    if ref == "D40")
    assert {pad["number"]: pad["net"] for pad in on_board} == {
        "1": "FAULT_G", "2": "PGND"}
    assert band_x < 0, "the band is drawn on the -x end; pad 1 must be there too"


def test_every_pad_net_index_points_at_the_right_name(board_text):
    names = {i: name for i, name in enumerate(pcb.net_table(
        [p for p in sch.parts() if p.footprint]))}
    for _, _, _, _, pads in _footprints(board_text):
        for pad in pads:
            if pad["net"]:
                assert names[pad["index"]] == pad["net"]


def test_the_board_carries_routed_copper(board_text):
    """The router emits both tracks and the vias that join the two layers."""
    assert "(segment " in board_text
    assert "(via " in board_text


# ---------------------------------------------------------------- pours
def _zones(text: str) -> list[dict]:
    """Every ``(zone ...)`` block, parsed from the board text.

    Read out of the file, not out of the generator's own zone table: a test
    that reads the answer back from the code that wrote it cannot see a
    record that never made it into the file.
    """
    out = []
    i = 0
    while True:
        j = text.find("(zone ", i)
        if j < 0:
            return out
        end = sch.block_end(text, j)
        block = text[j:end]
        name = re.search(r'\(net_name "([^"]+)"\)', block)
        layer = re.search(r'\(layer "([^"]+)"\)', block)
        pts = [(float(x), float(y)) for x, y in
               re.findall(r"\(xy ([-\d.]+) ([-\d.]+)\)", block)]
        out.append({"net": name.group(1) if name else None,
                    "layer": layer.group(1) if layer else None,
                    "points": pts,
                    "filled": "(filled_polygon" in block})
        i = end


def test_every_power_net_carries_a_pour(board_text):
    """A track is how a net escapes a land; a pour is how it carries current.

    The board's ceiling is 10 A.  Five power nets routed at 0.8 mm on one
    layer is the state this test exists to stop being the final one: the
    copper that carries the current has to be a filled region, not the
    widest track that fits between two SOIC lands.
    """
    zones = _zones(board_text)
    assert {z["net"] for z in zones} == set(pcb.POWER_NETS)
    for z in zones:
        assert z["layer"] in {"F.Cu", "B.Cu"}, z
        assert len(z["points"]) >= 4, z


def test_the_committed_board_stores_outlines_and_no_fills(board_text):
    """Fills are a build product, so the file keeps only the outline.

    Two reasons, one mechanical and one about honesty.  A committed
    ``filled_polygon`` is a snapshot of one KiCad version's fill algorithm: it
    would have to be regenerated whenever anything moved, and it drifts from
    the outline it came from.  Measured on this board: the outline-only file is
    about 2.5k lines; the same board with fills written back is 33.6k.  DRC
    fills from the outline itself (``--refill-zones``), so the outline is the
    complete description of the design.
    """
    zones = _zones(board_text)
    assert zones, "no zone in the board text"
    assert not any(z["filled"] for z in zones), "a fill was committed with the outline"


def test_every_pour_sits_inside_the_board_outline(board_text):
    """An outline that runs past ``Edge.Cuts`` is a short to the milled edge."""
    zones = _zones(board_text)
    assert zones, "no zone in the board text"     # else the loop below is vacuous
    for z in zones:
        for x, y in z["points"]:
            assert 0 <= x <= pcb.BOARD_W_MM, (z["net"], x, y)
            assert 0 <= y <= pcb.BOARD_D_MM, (z["net"], x, y)


def test_a_drc_that_did_not_run_refuses_the_previous_report(tmp_path):
    """A failed load must leave nothing to misread.

    ``kicad-cli`` exits non-zero when it cannot load the board and writes no
    report; a reader that keeps the old ``drc.json`` then reports the previous
    board's numbers.  This happened once, for real: a zone token this KiCad
    does not accept made every load fail with exit 3 and the check printed the
    old run's "0 unconnected, 4 silk".  ``sys.executable`` stands in for the
    CLI here -- any command that fails without writing the report will do.
    """
    board = tmp_path / "b.kicad_pcb"
    board.write_text("(kicad_pcb)\n", encoding="utf-8")
    out = tmp_path / "drc.json"
    out.write_text('{"violations": []}', encoding="utf-8")      # a stale report
    with pytest.raises(SystemExit):
        pcb.run_drc(Path(sys.executable), board, out)
    assert not out.exists(), "the stale report survived a DRC that did not run"


def test_the_drc_refills_the_zones_before_it_judges_them():
    """Without ``--refill-zones`` DRC judges an unfilled outline.

    ``--save-board`` is not passed: the fill would then be written into the
    committed file, which is exactly what the outline-only rule forbids.
    """
    argv = pcb.drc_command(Path("kicad-cli"), OUT / pcb.BOARD, OUT / "drc.json")
    assert "--refill-zones" in argv
    assert "--save-board" not in argv


# ------------------------------------------------------------------ fill
def _filled_board(net: str = "A") -> str:
    """A board text with one zone and one filled patch (square with a hole)."""
    return """(kicad_pcb
\t(zone
\t\t(net "%s")
\t\t(layer "F.Cu")
\t\t(polygon (pts (xy 0 0) (xy 10 0) (xy 10 10) (xy 0 10)))
\t\t(filled_polygon
\t\t\t(layer "F.Cu")
\t\t\t(pts
\t\t\t\t(xy 0 0) (xy 10 0) (xy 10 10) (xy 0 10)
\t\t\t)
\t\t\t(pts
\t\t\t\t(xy 4 4) (xy 6 4) (xy 6 6) (xy 4 6)
\t\t\t)
\t\t)
\t)
)
""" % net


class _Pad:
    def __init__(self, ref, number, net, x, y):
        self.ref, self.number, self.net, self.x, self.y = ref, number, net, x, y


# The pour spec the synthetic boards below are written against.
_A = [("A", "F.Cu", 0, [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)])]


def test_a_fill_is_measured_from_the_polygons_and_not_from_the_outline():
    """The outline is the design; the fill is what the tool decided to keep.

    The patch here is a 10x10 square with a 2x2 hole, so its area is 96, not
    the 100 the outline encloses -- measuring the outline would report copper
    that was never poured.
    """
    patches = pcb.fill_patches(_filled_board())["A"]
    assert len(patches) == 1
    assert patches[0]["area_mm2"] == pytest.approx(96.0)
    assert len(patches[0]["holes"]) == 1


def test_a_pad_in_a_fill_hole_is_reported_as_not_covered():
    """A thermal-relief hole is not copper under the pad.

    It does not mean the pad is unconnected -- the spokes connect it -- but it
    does mean a point-in-polygon test has to look at the holes, or every
    thermally relieved pad reads as covered when its centre is empty.
    """
    pads = [_Pad("R1", "1", 1, 1.0, 1.0), _Pad("R2", "1", 1, 5.0, 5.0),
            _Pad("R3", "1", 1, 20.0, 20.0)]
    report = pcb.fill_report(_filled_board(), pads=pads, names=["", "A"], specs=_A)
    pour = report["pours"]["A"]
    assert pour["pads_in_outline"] == 2          # the third pad is outside
    assert pour["pads_covered"] == ["R1.1"]
    assert pour["pads_uncovered"] == ["R2.1"]
    assert pour["area_mm2"] == pytest.approx(96.0)


def test_a_zone_with_no_fill_is_reported_rather_than_skipped():
    text = '(kicad_pcb\n\t(zone\n\t\t(net "A")\n\t\t(layer "F.Cu")\n'
    text += "\t\t(polygon (pts (xy 0 0) (xy 10 0) (xy 10 10)))\n\t)\n)\n"
    report = pcb.fill_report(text, pads=[], names=["", "A"], specs=_A)
    assert report["pours"]["A"]["patches"] == 0
    assert report["checks"]["every_pour_has_fill"] is False


@pytest.mark.skipif(not (OUT / "fill.json").exists(), reason="no fill.json in this checkout")
def test_the_committed_fill_report_covers_every_pour():
    data = json.loads((OUT / "fill.json").read_text(encoding="utf-8"))
    assert set(data["pours"]) == set(pcb.POWER_NETS)
    assert data["checks"]["every_pour_has_fill"] is True
    assert data["checks"]["no_pour_patch_is_isolated"] is True


@pytest.mark.skipif(not (OUT / "fill.json").exists(), reason="no fill.json in this checkout")
def test_the_corridors_keep_their_copper():
    """Keeping a pour whole is what makes it a conductor, so the retention is the
    thing to lock.  With signals routed across the corridors the fills kept
    2.5 %-65 % of their outlines; with ``keep_clear`` pressure they kept 79 %-94 %
    -- until a footprint change moved one PGND track across the output band and
    VOUT fell to 11.3 %, because a price only wins when the detour costs more
    than the crossing.  The band is now a barrier (``Pour.barrier``) and every
    pour keeps 75 %-98 % as a single patch.  The threshold stays at 0.70: it is
    well below the measured values, which leaves room for a KiCad fill-algorithm
    change without letting the corridors quietly go back to being slits, and it
    is not lowered to accommodate a bad route.
    """
    data = json.loads((OUT / "fill.json").read_text(encoding="utf-8"))
    for net, pour in data["pours"].items():
        share = pour["area_mm2"] / pour["outline_area_mm2"]
        assert share >= 0.70, f"{net} keeps only {share:.1%} of its outline"
    for net in ("SEC_A", "SEC_B"):
        assert data["pours"][net]["patches"] == 1, net


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


def test_an_isolated_pour_is_a_gate_and_not_a_note():
    """A fill that touches no pad of its own net is a pour that never reached.

    It has to fail the check: the copper is what carries the current, so a
    pour pruned out from under its pads leaves the net on the 0.8 mm escape
    track alone -- which is the state the pours were added to end.  KiCad calls
    it ``isolated_copper``; leaving it in an "unclassified" bucket would still
    fail, but with a message that reads like an unknown DRC type.
    """
    buckets = pcb.classify_violations([
        {"type": "isolated_copper", "severity": "warning"},
        {"type": "silk_overlap", "severity": "warning"},
        {"type": "clearance", "severity": "error"},
    ])
    assert [v["type"] for v in buckets["pours"]] == ["isolated_copper"]
    assert [v["type"] for v in buckets["placement"]] == ["clearance"]
    assert [v["type"] for v in buckets["cosmetic"]] == ["silk_overlap"]
    assert buckets["other"] == []
    assert pcb.POUR_ERRORS.isdisjoint(pcb.PLACEMENT_ERRORS | pcb.COSMETIC_TYPES)


@pytest.mark.skipif(not DRC.exists(), reason="no drc.json in this checkout")
def test_the_committed_pours_all_reach_a_pad():
    pours = pcb.classify_violations(pcb.drc_items()["violations"])["pours"]
    assert pours == [], [v["description"] for v in pours]


@pytest.mark.skipif(not DRC.exists(), reason="no drc.json in this checkout")
def test_the_committed_board_has_no_unrouted_net():
    """An empty ratsnest alone proves nothing, so both halves are asserted.

    A board whose netlist never reached the copper has no ratsnest either --
    that is the guard the old backlog test carried.  The router's own count is
    the other half: 121 connections attempted, 121 made.
    """
    items = pcb.drc_items()
    assert items["unconnected_items"] == []
    routing = pcb.report()["routing"]
    assert routing["routed"] is True
    assert routing["connections_made"] == routing["connections_attempted"] > 0


def test_the_reference_text_is_shifted_only_where_the_silk_would_touch():
    """Four reference texts shared silkscreen with a neighbour: "Rg1"/"Rg2"
    have a descender that reaches their own silk line, TP13 and TP17 sit 3.5 mm
    from their pair while 1 mm text is wider than that.  The fix moves the text
    on those instances only, so the control is R1 -- the same 0805 library
    footprint, left at the offset the library gives it.
    """
    text = (OUT / "sr_fault_validation.kicad_pcb").read_text(encoding="utf-8")

    def offset(ref: str) -> tuple[float, float]:
        match = re.search(r'\(property "Reference" "' + re.escape(ref) +
                          r'"\s*\(at (-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?)', text)
        assert match, ref
        return float(match.group(1)), float(match.group(2))

    assert offset("Rg1") == pytest.approx((0.0, -2.45))
    assert offset("Rg2") == pytest.approx((0.0, -2.45))
    assert offset("TP13") == pytest.approx((0.0, 1.452))
    assert offset("TP17") == pytest.approx((0.0, 1.452))
    assert offset("R1") == pytest.approx((0.0, -1.65))
    assert set(pcb.REFERENCE_TEXT_SHIFT_MM) == {"Rg1", "Rg2", "TP13", "TP17"}


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


def test_the_bsc_land_library_is_generated_from_the_digitised_page():
    """The footprint is a consumer of the measurement, not a second copy of it.

    ``tools/bsc010n04ls6_land.py`` refuses to write unless every printed callout
    matches its model; this asserts the emitted library is that model, so a
    hand-edit of either file shows up as a failure rather than as two files that
    disagree about the same copper.
    """
    lib = OUT / "dcx.pretty" / "BSC010N04LS6.kicad_mod"
    assert lib.read_text(encoding="utf-8") == pcb.bsc_source()
    land = pcb.bsc_land()
    assert len(pcb.pad_numbers(pcb.BSC_LIB_ID)) == sum(
        1 for pad in land["pads"] if pad["number"])


def test_the_mask_and_stencil_are_their_own_pads():
    """Three layers of the drawing, three kinds of pad.

    Letting a copper pad imply its mask opening would replace the drawn 0.05 mm
    expansion with the land outline, and imply a stencil as large as the land.
    """
    land = pcb.bsc_land()
    assert {"mask", "paste"} <= {pad["kind"].split(":")[0] for pad in land["pads"]}
    assert all(pad["number"] == "" for pad in land["pads"]
               if pad["layers"] in (["F.Mask"], ["F.Paste"]))
    assert all(pad["layers"] == ["F.Cu"] for pad in land["pads"]
               if pad["number"])


def test_the_honesty_flags_keep_the_board_unreleased():
    """``routed`` is a fact about connectivity, not a release.

    Every net is connected, DRC is clean of placement defects, the pours have
    been refilled and measured, BSC010N04LS6 carries a land pattern digitised
    from its datasheet, and a fabrication package exists -- and nothing has
    been built.  ``routed`` is a fact about connectivity, never a release.
    """
    data = pcb.report()
    assert data["routed"] is True
    assert data["hardware_built"] is False
    assert data["fabrication_approved"] is False
    assert data["manufacturing_package"] == pcb.MANUFACTURING_PACKAGE_EXPORTED
    assert data["status"].endswith("NOT_RELEASED")
    assert (OUT / pcb.BOARD).read_text(encoding="utf-8").count("(segment ") > 0


def test_the_fab_files_live_under_fab_and_nowhere_else():
    """A drill file next to the board looks orderable; one under fab/ has a manifest.

    The point of the directory is the manifest: it binds every file to the
    board hash and says what the package is not.
    """
    for pattern in ("*.gbr", "*.drl", "*.g*", "*.pos", "*.csv.tmp"):
        assert not list(OUT.glob(pattern)), pattern
    assert (pcb.FAB / "manifest.json").is_file()


def test_the_package_ships_the_assembly_drawing_and_lists_every_file():
    """Two separate risks.

    A file in ``fab/`` that the manifest does not list is a file nobody hashed
    -- it could change without the package noticing.  And the drawing is the
    only artefact a person reads to learn that ten parts stay empty on purpose,
    so it has to be in the package, not in a directory beside it.
    """
    manifest = json.loads((pcb.FAB / "manifest.json").read_text(encoding="utf-8"))
    listed = {row["name"] for row in manifest["files"]}
    on_disk = {p.name for p in pcb.FAB.iterdir()
               if p.is_file() and p.name != pcb.FAB_MANIFEST.name}
    assert on_disk == listed, sorted(on_disk ^ listed)
    assert "assembly.svg" in listed
    assert "assembly" in manifest["what_this_is"]
    drawing = (pcb.FAB / "assembly.svg").read_text(encoding="utf-8")
    for ref in pcb._dnp_refs():
        assert f'data-ref="{ref}"' in drawing, ref


def test_the_fab_manifest_binds_the_files_to_the_board():
    manifest = json.loads((pcb.FAB / "manifest.json").read_text(encoding="utf-8"))
    board = OUT / pcb.BOARD
    assert manifest["board_sha256"] == pcb._sha256(board)
    assert manifest["files"], "the manifest lists no exported file"
    for row in manifest["files"]:
        path = pcb.FAB / row["name"]
        assert path.is_file(), row["name"]
        assert path.stat().st_size == row["bytes"]
        assert pcb._sha256(path) == row["sha256"], row["name"]
    assert manifest["copper_weight_oz"] == pcb.FAB_COPPER_WEIGHT_OZ
    assert manifest["layers"][0] == "F.Cu" and "Edge.Cuts" in manifest["layers"]
    # Requested and plotted are recorded separately because kicad-cli drops an
    # undeclared layer silently; a package that ships fewer plots than it
    # claims is the failure this pair exists to expose.
    assert sorted(manifest["plotted_layers"]) == sorted(manifest["layers"])
    assert manifest["flags"] == {"hardware_built": False, "fabrication_approved": False}


def test_the_board_declares_the_paste_and_mask_layers_it_plots():
    """kicad-cli plots only layers the board's ``(layers)`` table declares.

    Pads may name F.Mask/F.Paste all day; if the board's own table omits them
    the plot returns 0 and writes nothing for that layer.  The first package
    came out with five of nine layers and a manifest claiming nine.
    """
    text = (OUT / pcb.BOARD).read_text(encoding="utf-8")
    block = re.search(r"\t\(layers\n(.*?)\n\t\)\n", text, re.S)
    assert block, "the board has no (layers) table"
    body = block.group(1)
    for name in pcb.FAB_GERBER_SUFFIX:
        declared = {"F.Silkscreen": "F.SilkS", "B.Silkscreen": "B.SilkS"}.get(name, name)
        assert f'"{declared}"' in body, f"{name} is plotted but not declared"


def test_a_layer_the_export_did_not_plot_fails_the_package(tmp_path: Path):
    """The count alone is not enough: the failure names the layer."""
    for suffix in pcb.FAB_GERBER_SUFFIX.values():
        (tmp_path / f"board{suffix}").write_text("x", encoding="utf-8")
    pcb.check_plotted_layers(tmp_path)          # nine of nine: no complaint
    (tmp_path / "board.gts").unlink()           # the front soldermask vanishes
    with pytest.raises(SystemExit, match="F.Mask"):
        pcb.check_plotted_layers(tmp_path)


def test_the_position_file_places_no_dnp_part():
    """The CSV is what a machine follows, so this reads the CSV, not the manifest.

    ``--exclude-dnp`` reads the footprint's ``(attr ... dnp)``.  The first export
    passed the flag on a board where no footprint carried it, and all ten DNP
    parts -- the gate clamps that are meant to stay empty -- came back in the
    placement file.
    """
    refs = pcb.position_refs(pcb.FAB / "sr_fault_validation-pos.csv")
    assert refs, "the position file is empty"
    assert not (refs & pcb._dnp_refs()), sorted(refs & pcb._dnp_refs())
    assert {"Q1", "Q2", "U1"} <= refs      # the populated parts are still there


def test_a_position_file_that_places_a_dnp_part_fails_the_package(tmp_path: Path):
    path = tmp_path / "pos.csv"
    dnp_ref = sorted(pcb._dnp_refs())[0]
    path.write_text("Ref,Val,Package,PosX,PosY,Rot,Side\n"
                    f"{dnp_ref},x,y,0,0,0,top\n", encoding="utf-8")
    with pytest.raises(SystemExit, match=dnp_ref):
        pcb.check_position_excludes_dnp(path)


def test_the_process_requirements_say_where_each_number_comes_from():
    """A package a fabricator can quote needs thickness, weight, finish, minimums.

    Two numbers are measured on the board, four are the router's design rules,
    and the rest are our choice.  The three lists must partition the fields, so
    a reader never has to guess whether "1 oz" was measured or assumed.
    """
    pr = pcb.report()["process_requirements"]
    declared = pr["measured_here"] + pr["design_rules"] + pr["our_choice_not_measured"]
    fields = {key for key, value in pr.items() if not isinstance(value, list)}
    assert len(declared) == len(set(declared)), "a field is in two families"
    assert set(declared) == fields, sorted(fields ^ set(declared))
    assert pr["min_track_mm"] > 0 and pr["min_track_mm"] <= pcb.ROUTE_POWER_MM
    assert pr["min_drill_mm"] == pcb.router.VIA_DRILL_MM
    assert pr["thickness_mm"] == pcb.THICKNESS_MM


def test_the_fab_manifest_repeats_the_rating_rather_than_pointing_at_it():
    """The fabricator gets the package, not the repository."""
    manifest = json.loads((pcb.FAB / "manifest.json").read_text(encoding="utf-8"))
    rating = manifest["current_rating"]
    assert set(rating["nets"]) == {"SEC_A", "SEC_B"}
    for row in rating["nets"].values():
        assert row["rating"], row["rating"]
    assert manifest["current_rating"] == pcb.report()["power_path"]["escape_rating"]


# ---------------------------------------------------------------- current rating
def test_the_escape_rating_reads_the_copper_the_router_laid():
    """The elements come from the route, not from a table in this file."""
    data = pcb.report()["power_path"]["escape_rating"]
    for net in ("SEC_A", "SEC_B"):
        row = data["nets"][net]
        assert row["tracks"] >= 1 and row["vias"] >= 2, row
        assert row["narrowest_track_mm"] == pytest.approx(pcb.ROUTE_POWER_MM, abs=1e-9)
        # The pour edge is x 43 and the drain land starts at x 46.87, so the box
        # has to span that gap; a box that missed it would rate nothing.
        x0, x1 = row["escape_box_mm"][0], row["escape_box_mm"][1]
        assert x0 < row["pour_right_mm"] < x1
        assert x0 < row["drain_land_left_mm"] < x1
        assert row["pour_right_mm"] == pytest.approx(43.0)
        assert row["drain_land_left_mm"] == pytest.approx(46.87, abs=0.005)


def test_the_via_barrel_binds_the_pulse_not_the_track():
    """A 0.3 mm drill with 0.020 mm of plating is less copper than 0.8 mm of 1 oz.

    Both are the same length, so the barrel is the element that reaches the
    temperature first at every copper weight -- which is why widening the track
    would not change the pulse number.
    """
    data = pcb.report()["power_path"]["escape_rating"]
    for row in data["nets"].values():
        for oz in pcb.COPPER_WEIGHTS_OZ:
            rating = row["rating"][f"{oz}oz"]
            assert rating["binding_element"].startswith("via_barrel"), rating
    barrel = pcb.via_element(pcb.router.VIA_DRILL_MM, pcb.THICKNESS_MM)
    assert barrel["area_mm2"] < pcb.ROUTE_POWER_MM * pcb.COPPER_OZ_MM


def test_the_adiabatic_i2t_is_independent_of_length_and_fourfold_at_2oz():
    """I2t = mc dT / R with m and R both proportional to length.

    Both identities hold on the unrounded quantities; the reported fields carry
    three decimals, so each comparison has to allow the rounding of its operands
    (4 x 0.0005 + 0.0005 for the fourfold, 10 x 0.0005 + 0.0005 for the length
    scaling) rather than a relative epsilon.  At the 0.8 mm track's 1.54 A2s the
    former is 2e-3 relative, and at its 0.618 mOhm the latter is 9e-3 relative
    -- the identity, not the arithmetic, is what the test is for.
    """
    short = pcb.track_element(0.8, pcb.COPPER_OZ_MM, 1.0)
    long = pcb.track_element(0.8, pcb.COPPER_OZ_MM, 10.0)
    assert short["i2t_a2s"] == pytest.approx(long["i2t_a2s"])
    assert short["r20_mohm"] * 10.0 == pytest.approx(long["r20_mohm"], abs=0.006)
    double = pcb.track_element(0.8, 2.0 * pcb.COPPER_OZ_MM, 1.0)
    assert double["i2t_a2s"] == pytest.approx(4.0 * short["i2t_a2s"], abs=0.003)


def test_the_chart_reproduces_the_ipc2221_numbers_the_documents_quote():
    """Anchors, not a re-derivation: these are the figures the prose repeats."""
    assert pcb.chart_current_a(0.8, pcb.COPPER_OZ_MM, 10.0) == pytest.approx(2.03, abs=0.02)
    assert pcb.chart_current_a(0.8, pcb.COPPER_OZ_MM, 20.0) == pytest.approx(2.75, abs=0.02)
    assert pcb.chart_current_a(0.8, 2 * pcb.COPPER_OZ_MM, 10.0) == pytest.approx(3.35, abs=0.03)
    assert pcb.chart_current_a(3.61, 2 * pcb.COPPER_OZ_MM, 10.0) == pytest.approx(10.0, abs=0.1)



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

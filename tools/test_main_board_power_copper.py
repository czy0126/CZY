"""A5 power copper: routing is a connectivity claim, and ampacity is a result.

The board this module writes is a *draft*: every routable net is connected and
kicad-cli agrees, but a 0.8 mm track can never carry 100 A.  That split is the
whole reason these tests exist:

* the structural gates (connected, no ratsnest, no placement violation) are
  checks and must pass;
* "the output path meets 0.15 mOhm" is a physical result and must *fail*, and
  it must be possible for both to be true at once.  A test that let the failing
  verdict leak into ``checks`` would invite the next person to loosen the
  0.15 mOhm basis until the board went "green" -- the exact failure CLAUDE.md
  records for the 100 A ledger.

The measurement tests are synthetic on purpose.  The real board routes in ~40 s
and takes ~2 min more to pour and solve, so the interesting geometry (tracks
that only meet *inside* a pad) is pinned on a four-segment fixture where the
expected numbers can be read off by hand.

The pour tests follow the same rule one level down.  ``mesh_squares`` is
verified on a strip and a plate whose sheet resistance is known exactly --
20 x 200 cells is ten squares, a square plate is one -- before any number from
a board is quoted.  Both fixtures read one cell short (199/20 and 39/40) because
the electrodes are one cell wide; that is the mesh's own bias, and the pour
figures inherit it, so the expectations are exact rather than rounded.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import main_board_power_copper as m   # noqa: E402
import sr_board_router as router      # noqa: E402


@pytest.fixture(scope="module")
def routed():
    """Route once; the router is deterministic, so every test can share it."""
    return m.route_board(m.placement_text())


# ---------------------------------------------------------------- the route
def test_every_routable_net_is_connected(routed):
    result, _, _, single = routed
    assert result.connections_attempted > 100
    assert result.connections_made == result.connections_attempted
    assert result.unrouted == []
    assert result.failures == []
    # one pad per net is not a connection to make; it is a net that leaves the board
    assert len(single) == 5


def test_the_five_single_pad_nets_are_the_off_board_ends_of_the_taps(routed):
    """These leave the board for the control area, the CT bridge and the crowbar.

    They are reported rather than dropped: a net with one pad draws no ratsnest
    line, so silence would read as "already connected" -- the same trap A5's
    ``single_pad_nets`` exists for.

    The set has moved three times under package C.  Placing the gate resistors
    turned GA*/GB*/GH/GL into two-pad nets; placing U3-U6 took all sixteen
    VD*/VG* off the list and put REG1-REG4 on it; placing the REG crowbar took
    REG1-REG4 off again -- each now reaches its 4.7 ohm -- and put FAULT_IN on
    it, the crowbar's one off-board end.  The *set* is asserted, not a count: a
    count would not have noticed which nets moved.
    """
    _, _, _, single = routed
    assert sorted(single) == sorted(["CS1", "CS2", "FAULT_IN", "GH_DRV", "GL_DRV"])


def test_the_12v_bus_reaches_all_four_controllers(routed):
    """``VCC12_S`` is the board's longest four-pad net, and it lost its lane.

    Pin 7 of each UCC24624 sits in a 1.27 mm column of four occupied pins --
    PGND (5), VD (6), VCC12_S (7), VG (8) -- and the four parts are 38 mm
    apart, so this bus has to cross every corridor on the board to reach them.
    It ran after ten nets that have more pads (PGND, VOUT, SW, the eight SEC*
    groups), and on 2026-11-06 all three of its connections failed at U3.

    The repair pass could not rescue it: ``_rip_victims`` measured distance to
    the two *endpoints*, so a blocker halfway down a 38 mm run was never a
    candidate and the failure was permanent.  The fix is the width split --
    at 0.25 mm a track fits the 0.67 mm air between the pins, at 0.8 mm it
    needs 1.2 mm and never can.  Naming the net rather than asserting the
    count is deliberate: "198/198" would go green again if the failure moved
    somewhere else.
    """
    result, ids, _, _ = routed
    net = ids["VCC12_S"]
    assert str(net) not in result.unrouted, "the 12 V bus lost a controller"
    assert sum(1 for s in result.segments if s.net == net) > 0


def test_only_the_measured_output_nets_keep_a_power_width(routed):
    """Two widths, and each one has a reason that is written down.

    ``path_budget`` walks VOUT and PGND only, so those two keep 0.8 mm -- the
    width ``what_a_track_would_need`` answers in, and the width the budget's
    "a track would have to be wider than the board" argument is phrased
    against.  Every other net on this board is a connectivity placeholder:
    the status line already says the tracks cannot carry their currents, so
    0.8 mm bought no rating and cost a lane every time it crossed one.

    Splitting the widths is not cosmetic either -- it is the fix for the
    twelve-volt bus.  A single width meant the four-pin UCC24624 column had to
    give 1.2 mm of a 0.67 mm gap, so ``VCC12_S`` (four pads, routed after ten
    nets that have more) could not leave its last three pins.
    """
    _, ids, pads, _ = routed
    widths, order, _ = m.route_plan(pads, ids)
    name = {i: n for n, i in ids.items()}
    power = {name[n] for n, w in widths.items() if w == m.POWER_WIDTH_MM}
    signal = {name[n] for n, w in widths.items() if w == m.SIGNAL_WIDTH_MM}
    assert power == set(m.OUTPUT_NETS)
    assert signal == {name[n] for n in order} - power
    assert signal, "a one-width board is what lost VCC12_S; do not go back to it"
    assert m.SIGNAL_WIDTH_MM < m.POWER_WIDTH_MM


def test_a_power_track_cannot_leave_a_controller_pin_column(routed):
    """The geometry, measured off the placement rather than quoted.

    Pads 5-8 of a UCC24624 share one 1.27 mm column, so the widest track that
    can pass between two of them is the pad-to-pad gap less two clearances.
    Measuring it here means the second width cannot be retired by editing a
    constant, and that the claim is checked against the board that ships.
    """
    _, _, pads, _ = routed
    column = sorted((p for p in pads if p.ref == "U3" and p.number in {"5", "6", "7", "8"}),
                    key=lambda p: p.y)
    assert {p.number for p in column} == {"5", "6", "7", "8"}
    assert len({round(p.x, 3) for p in column}) == 1, "the four pins are one column"
    gaps = [column[i + 1].y - column[i].y - (column[i + 1].h + column[i].h) / 2.0
            for i in range(3)]
    gap = min(gaps)
    assert m.POWER_WIDTH_MM + 2 * router.CLEARANCE_MM > gap, (
        "an 0.8 mm track now fits the pin column -- re-measure before dropping the "
        "signal width")
    assert m.SIGNAL_WIDTH_MM < gap


def test_the_route_is_deterministic(routed):
    """Byte-reproducible without KiCad is what lets --check run in CI."""
    again = m.route_board(m.placement_text())
    assert m.copper_lines(again[0]) == m.copper_lines(routed[0])


def test_the_board_carries_copper_and_does_not_claim_approval(routed):
    result, ids, _, _ = routed
    board = m.board_file(m.placement_text(), result, ids)
    assert "(segment" in board and "(via" in board
    assert "no routing" not in board
    assert "NETTED PLACEMENT" not in board
    data = m.report(board, result, ids, routed[2], routed[3])
    assert data["flags"] == {"routed": True, "poured": False,
                             "fabrication_approved": False, "hardware_built": False}


# ---------------------------------------------------------------- the guard rails
def test_the_title_block_is_rewritten_or_the_write_fails(routed):
    """Silently keeping "no routing" would make the board misdescribe itself."""
    result, ids, _, _ = routed
    with pytest.raises(SystemExit, match="comment line changed"):
        m.board_file(m.placement_text().replace("NETTED PLACEMENT", "PLACEMENT"), result, ids)


def test_the_generator_name_is_rewritten(routed):
    result, ids, _, _ = routed
    board = m.board_file(m.placement_text(), result, ids)
    assert '(generator "main_board_power_copper")' in board
    assert '(generator "main_board_mechanical")' not in board


def test_the_project_file_carries_the_routed_name(routed):
    project = json.loads(m.project_file())
    assert project["meta"]["filename"] == "power_stage_routed.kicad_pro"


def test_a_stale_board_fails_the_check(tmp_path, monkeypatch, routed):
    stale = tmp_path / "power_stage_routed.kicad_pcb"
    stale.write_text("(kicad_pcb (version 20240108)\n)\n", encoding="utf-8")
    monkeypatch.setattr(m, "BOARD", stale)
    monkeypatch.setattr(m, "route_board", lambda text: routed)
    with pytest.raises(SystemExit, match="stale"):
        m.check()


def test_a_report_that_does_not_match_the_board_fails_the_check(tmp_path, monkeypatch, routed):
    """The board can be current while the numbers beside it were hand-edited."""
    result, ids, _, _ = routed
    board = m.board_file(m.placement_text(), result, ids)
    live = tmp_path / "power_stage_routed.kicad_pcb"
    live.write_text(board, encoding="utf-8")
    report = tmp_path / "routed_copper.json"
    report.write_text(json.dumps({"board": {"board_sha256": "0" * 64},
                                  "budget": {"worst_group_mohm_at_2oz": 1.0,
                                             "design_basis_mohm": 0.15,
                                             "meets_design_basis_at_2oz": True}}),
                      encoding="utf-8")
    monkeypatch.setattr(m, "BOARD", live)
    monkeypatch.setattr(m, "REPORT", report)
    monkeypatch.setattr(m, "route_board", lambda text: routed)
    with pytest.raises(SystemExit, match="not derived from the committed board"):
        m.check()


# ---------------------------------------------------------------- checks vs results
def test_the_structural_gates_pass_while_the_power_target_fails():
    """Both statements have to be true at once, or the report is lying.

    A routed-but-inadequate board is the honest state of package C: connectivity
    is finished, ampacity is not.  If this ever fails because someone edited the
    committed JSON, the failure is the point.
    """
    data = json.loads(m.REPORT.read_text(encoding="utf-8"))
    assert data["checks"], "checks must not be empty"
    assert all(data["checks"].values()), data["checks"]
    assert data["results"]["power_path_meets_the_0p15_mohm_basis"] is False
    assert data["results"]["worst_group_mohm_at_2oz"] > 100 * data["budget"]["design_basis_mohm"]


def test_the_drc_counts_the_second_top_level_array():
    """kicad-cli puts the ratsnest in ``unconnected_items``, not in ``violations``.

    Reading only ``violations`` reports "0 unconnected" for a board with no
    copper at all -- the trap A5 and the SR board both hit.
    """
    summary = m.drc_summary({"violations": [], "unconnected_items": [{}, {}],
                             "schematic_parity": [], "ignored_checks": []})
    assert summary["violations"] == 0
    assert summary["unconnected_items"] == 2


def test_a_board_with_a_ratsnest_fails_the_structural_check():
    data = {"route": {"connections_made": 1, "connections_attempted": 1,
                      "unrouted_nets": [], "segments": 1},
            "drc_reproduced": True,
            "drc": {"unconnected_items": 3, "counts": {"placement": 0}},
            "interfaces": {"provisional_land_patterns": [
                {"ref": ref} for ref in sorted(m.MAGNETIC_REFS)]},
            "budget": {"meets_design_basis_at_2oz": False,
                       "worst_group_mohm_at_2oz": 999.0}}
    m._set_checks(data)
    assert data["checks"]["drc_reports_no_unconnected_items"] is False
    assert data["checks"]["every_routable_net_is_connected"] is True


# ---------------------------------------------------------------- measurement
def _pad(ref, number, x, y, w=2.0, h=2.0, layers=(0,), net=1):
    return router.Pad(ref=ref, number=number, net=net, x=x, y=y, w=w, h=h, layers=layers)


def _seg(x0, y0, x1, y1, width=1.0, layer=0, net=1):
    return router.Segment(net=net, layer=layer, width=width,
                          x0=x0, y0=y0, x1=x1, y1=y1)


def _result(*segments, vias=()):
    return router.RouteResult(segments=list(segments), vias=list(vias))


def test_tracks_that_only_meet_inside_a_pad_are_one_path():
    """The bug this test pins: consecutive connections leave from *different
    cells of the same pad*, so the emitted tracks share no grid node.  Without
    contracting pads into nodes the VOUT graph fell into eight components and
    every path came back ``None``.
    """
    pad_a = _pad("X1", "1", 0, 0, 4, 4)         # spans x -2..2
    pad_b = _pad("X2", "1", 10, 0)              # spans x 9..11
    result = _result(_seg(1.5, 0, 5, 0),        # starts inside pad A
                     _seg(5, 0, 9, 0),          # ends inside pad B
                     _seg(-1.5, 0, -1.5, 3))    # dead end, also inside pad A
    assert m.path_squares(result, [pad_a, pad_b], pad_a, pad_b) == {
        "length_mm": 7.5, "squares": 7.5}


def test_squares_are_summed_per_segment_width():
    """A path that changes width must not be charged at one width throughout."""
    pad_a = _pad("X1", "1", 0, 0, 4, 4)
    pad_b = _pad("X2", "1", 10, 0)
    result = _result(_seg(1.5, 0, 5, 0, width=1.0), _seg(5, 0, 9, 0, width=2.0))
    path = m.path_squares(result, [pad_a, pad_b], pad_a, pad_b)
    assert path == {"length_mm": 7.5, "squares": 5.5}


def test_a_track_on_the_other_layer_does_not_reach_a_pad():
    """A pad on F.Cu and a B.Cu track share no copper without a via."""
    pad_a = _pad("X1", "1", 0, 0, 4, 4, layers=(0,))
    pad_b = _pad("X2", "1", 10, 0, layers=(0,))
    result = _result(_seg(1.5, 0, 9, 0, layer=1))
    assert m.path_squares(result, [pad_a, pad_b], pad_a, pad_b) is None


def test_a_via_bridges_the_two_layers():
    pad_a = _pad("X1", "1", 0, 0, 4, 4, layers=(0,))
    pad_b = _pad("X2", "1", 10, 0, layers=(1,))
    result = _result(_seg(1.5, 0, 5, 0, layer=0),
                     _seg(5, 0, 9, 0, layer=1),
                     vias=[router.Via(net=1, x=5, y=0)])
    assert m.path_squares(result, [pad_a, pad_b], pad_a, pad_b)["length_mm"] == 7.5


def test_an_unconnected_pair_reports_none_rather_than_zero():
    pad_a = _pad("X1", "1", 0, 0, 4, 4)
    pad_b = _pad("X2", "1", 10, 0)
    result = _result(_seg(1.5, 0, 5, 0))
    assert m.path_squares(result, [pad_a, pad_b], pad_a, pad_b) is None


def test_the_magnetics_are_reported_as_provisional_interfaces():
    """The copper lands on outline pads, and the report has to say so.

    The placement's own ``evidence`` label calls the ELP32 cores
    ``generated-json`` while their footprint text still says "Terminal positions
    PROVISIONAL", so the interface list is read from the footprint, not the
    label.  If the word is deleted without a terminal drawing, this goes red.
    """
    import main_board_mechanical as a5
    data = json.loads(m.REPORT.read_text(encoding="utf-8"))
    listed = {row["ref"] for row in data["interfaces"]["provisional_land_patterns"]}
    assert m.MAGNETIC_REFS <= listed
    labelled = {p.ref: p.evidence for p in a5.PARTS if p.ref in m.MAGNETIC_REFS}
    assert labelled["T1"] != "PROVISIONAL", (
        "the placement now labels the cores PROVISIONAL -- the descr scan can go, "
        "but not silently")
    assert data["checks"]["every_magnetic_is_reported_as_a_provisional_interface"] is True


def test_the_budget_reports_what_a_track_would_need():
    """The shortest way to say why planes are not optional."""
    data = json.loads(m.REPORT.read_text(encoding="utf-8"))
    need = data["budget"]["what_a_track_would_need"]
    assert need["required_width_mm"] > need["board_width_mm"]
    assert data["budget"]["meets_design_basis_at_2oz"] is False
    assert data["pours"]["count"] == len(m.POUR_PATHS)


# ---------------------------------------------------------------- the pour
def test_the_mesh_counts_squares_of_a_strip():
    """A 20 x 200 strip is 10 squares: the sheet resistance is the *shape*.

    This is the fixture the solver was verified on before it was pointed at a
    board.  9.95 rather than 10.00 is the mesh doing its job -- the electrodes
    are one cell wide, so the ends cost half a cell each.
    """
    import numpy as np
    mask = np.zeros((24, 208), bool)
    mask[2:22, 4:204] = True
    source = mask & False
    sink = mask & False
    source[2:22, 4] = True
    sink[2:22, 203] = True
    solved = m.mesh_squares(mask, source, sink)
    assert solved["converged"]
    # The electrodes are one cell wide and sit *in* the strip, so the measured
    # span is 199 cells of 20 -- 9.95, not 10.00.  That 0.5 % is the mesh's own
    # bias and the pour numbers carry it too.
    assert solved["squares"] == pytest.approx(199 / 20, rel=1e-6)


def test_the_mesh_counts_one_square_of_a_plate():
    """Two opposite edges of an equal-sided plate are one square per side."""
    import numpy as np
    mask = np.zeros((40, 40), bool)
    mask[0:40, 0:40] = True
    source = mask & False
    sink = mask & False
    source[:, 0] = True
    sink[:, 39] = True
    solved = m.mesh_squares(mask, source, sink)
    # 39 of 40 cells between the electrode columns: the same one-cell bias.
    assert solved["squares"] == pytest.approx(39 / 40, rel=1e-6)


def test_a_hole_in_the_fill_is_not_copper():
    """KiCad concatenates a contour and its holes into one ``(pts ...)`` list.

    The only delimiter is the repeated first point, and the hole is wound the
    other way.  If the rasteriser ignored either, a board-wide pour would read
    as solid and every resistance here would be too low.
    """
    text = ('(filled_polygon (layer "F.Cu") (pts (xy 0 0) (xy 10 0) (xy 10 10) '
            '(xy 0 10) (xy 0 0) (xy 3 3) (xy 3 7) (xy 7 7) (xy 7 3) (xy 3 3)))')
    contours = m.fill_contours(text, "F.Cu")
    assert len(contours) == 2
    shape, x0, y0 = m.raster_fill(contours, 0.25)
    assert shape[1, 1], "the corner of the outer contour must be copper"
    cy = int((5 - y0) / 0.25)
    cx = int((5 - x0) / 0.25)
    assert not shape[cy, cx], "the hole must not be copper"


def test_the_pour_covers_both_output_nets_and_fails_the_basis():
    """The number that decides the topology: a solid 4 oz pour is still over.

    If this ever passes, someone lowered the basis or poured a different board;
    the busbar conclusion rests on it failing.
    """
    data = json.loads(m.REPORT.read_text(encoding="utf-8"))
    pours = data["pours"]
    assert {p["net"] for p in pours["paths"]} == {"VOUT", "PGND"}
    assert all(p["every_terminal_lands_in_the_fill"] for p in pours["paths"])
    assert data["results"]["pour_meets_the_0p15_mohm_basis_at_2oz"] is False
    assert pours["series_mohm"]["4oz"] > 1.0 * 0.15
    assert pours["series_mohm"]["4oz"] < pours["series_mohm"]["1oz"]
    assert "not" in pours["not_a_layout"].lower() or "not a design" in pours["not_a_layout"]


def test_the_committed_board_is_what_the_route_produces(routed):
    result, ids, _, _ = routed
    board = m.board_file(m.placement_text(), result, ids)
    committed = m.BOARD.read_bytes().decode("utf-8").replace("\r\n", "\n")
    assert committed == board, "run python tools/main_board_power_copper.py --json"

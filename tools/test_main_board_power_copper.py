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

The measurement tests are synthetic on purpose.  The real board routes in ~40 s,
so the interesting geometry (tracks that only meet *inside* a pad) is pinned on
a four-segment fixture where the expected numbers can be read off by hand.
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
    assert len(single) == 12


def test_the_twelve_single_pad_nets_are_the_gate_returns_and_ct_secondaries(routed):
    """These leave the board for the gate resistors and the CT bridge.

    They are reported rather than dropped: a net with one pad draws no ratsnest
    line, so silence would read as "already connected" -- the same trap A5's
    ``single_pad_nets`` exists for.
    """
    _, _, _, single = routed
    assert sorted(single) == sorted(
        ["CS1", "CS2", "GH", "GL"]
        + [f"GA{i}" for i in range(1, 5)]
        + [f"GB{i}" for i in range(1, 5)])


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
    assert data["pours"]["count"] == 0


def test_the_committed_board_is_what_the_route_produces(routed):
    result, ids, _, _ = routed
    board = m.board_file(m.placement_text(), result, ids)
    committed = m.BOARD.read_bytes().decode("utf-8").replace("\r\n", "\n")
    assert committed == board, "run python tools/main_board_power_copper.py --json"

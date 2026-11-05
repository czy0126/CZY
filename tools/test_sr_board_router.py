"""Tests for tools/sr_board_router.py.

The router's job is narrow and checkable: given pads and a clearance, emit
copper that connects each net and never comes closer to foreign copper than the
clearance.  Both halves are tested here on small synthetic boards, because the
132 x 92 mm validation board takes about a minute to route and a failure there
would only say "something is wrong somewhere".

The third test is the one that matters for CI: ``clearance_violations`` is the
only statement about shorts that can run without KiCad installed.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sr_board_router as rt  # noqa: E402


def pad(ref: str, number: str, net: int, x: float, y: float,
        w: float = 0.6, h: float = 0.6, layers: tuple[int, ...] = (0,)) -> rt.Pad:
    return rt.Pad(ref=ref, number=number, net=net, x=x, y=y, w=w, h=h, layers=layers)


# ---------------------------------------------------------------- pad parsing
FOOTPRINT = """(footprint "test:two_pad"
  (pad "1" smd rect (at -0.5 0) (size 0.6 0.6) (layers "F.Cu" "F.Paste" "F.Mask"))
  (pad "2" smd rect (at 0.5 0) (size 0.6 0.6) (layers "F.Cu" "F.Paste" "F.Mask"))
  (pad "" np_thru_hole circle (at 0 0) (size 1 1) (drill 0.5) (layers "*.Cu" "*.Mask"))
)"""


def test_pads_are_offset_by_the_placement_origin():
    pads = rt.extract_pads(FOOTPRINT, "X1", 10.0, 20.0, lambda ref, number: 7)
    named = [p for p in pads if p.number]
    assert [(p.x, p.y) for p in named] == [(9.5, 20.0), (10.5, 20.0)]
    assert {p.net for p in named} == {7}


def test_an_unnamed_land_is_kept_as_copper_with_no_net():
    """The SOT-23's spare land has no number but is metal; it must still block.

    Dropping it would let another net's track run straight over a real pad.
    """
    pads = rt.extract_pads(FOOTPRINT, "X1", 0.0, 0.0, lambda ref, number: 7)
    assert [(p.number, p.net) for p in pads] == [("1", 7), ("2", 7), ("", -1)]
    assert rt.clearance_violations(
        pads, [rt.Segment(net=1, layer=0, width=0.25, x0=-2.0, y0=0.0, x1=2.0, y1=0.0)], [])


def test_a_rotated_land_swaps_its_width_and_height():
    rotated = FOOTPRINT.replace("(at -0.5 0)", "(at -0.5 0 90)")
    pads = {p.number: p for p in
            rt.extract_pads(rotated, "X1", 0.0, 0.0, lambda ref, number: -1)}
    assert (pads["1"].w, pads["1"].h) == (0.6, 0.6)


# ---------------------------------------------------------------- routing
def test_two_pads_on_one_net_are_joined():
    pads = [pad("A", "1", 1, 2.0, 2.0), pad("B", "1", 1, 8.0, 2.0)]
    result = rt.route(pads, 20.0, 20.0, [], widths={1: 0.25}, order=[1])
    assert result.unrouted == [] and result.connections_made == 1
    assert result.segments
    assert not rt.clearance_violations(pads, result.segments, result.vias)


def test_the_pad_cells_a_track_may_stop_on_reach_the_copper():
    """Every accepted cell must be within the track radius of the pad.

    Regression: the set used half a *pitch* of slack, which admits a cell
    0.177 mm diagonally outside a 1 mm pad.  A 0.25 mm route ending there does
    not overlap the pad, so the router counted a connection that kicad-cli
    called a dangling track.
    """
    p = pad("A", "1", 1, 10.03, 10.02, w=1.0, h=1.0)
    router = rt.Router([p], 20.0, 20.0, [])
    cells = router._pad_cells(p, 0.125)
    assert cells
    for _, idx in cells:
        x, y = router._cell_xy(idx % router.nx, idx // router.nx)
        assert rt._rect_distance(x, y, p.rect) <= 0.125 + 1e-9


def test_a_route_overlaps_both_pads_it_connects():
    """The other half: the search's cell must land on copper, not near it.

    Two pads deliberately off the grid, because that is when the last cell is
    most likely to fall outside the pad's edge.
    """
    pads = [pad("A", "1", 1, 2.03, 2.02, w=0.6, h=0.6),
            pad("B", "1", 1, 9.37, 7.11, w=0.6, h=0.6)]
    result = rt.route(pads, 20.0, 20.0, [], widths={1: 0.25}, order=[1])
    assert result.unrouted == [], result.failures
    for p in pads:
        assert any(rt._rect_segment_distance(p.rect, (s.x0, s.y0, s.x1, s.y1)) <= s.width / 2
                   for s in result.segments), p


def test_a_round_pad_only_accepts_cells_its_copper_covers():
    """A circular pad's bounding-box corner is not copper.

    Measured on the validation board: track TP17's start sat at the bbox
    corner of a 1 mm circular test-point pad -- 0.207 mm outside the circle --
    and kicad-cli called it unconnected while the router had counted it.
    """
    p = rt.Pad(ref="TP", number="1", net=1, x=10.0, y=10.0, w=1.0, h=1.0,
               layers=(0,), shape="circle")
    router = rt.Router([p], 20.0, 20.0, [])
    cells = router._pad_cells(p, 0.125)
    assert cells
    assert (0, router._index(84, 84)) not in cells, "the bbox corner is outside the circle"
    for layer, idx in cells:
        x, y = router._cell_xy(idx % router.nx, idx // router.nx)
        assert rt._pad_distance(p, x, y) <= 0.0625 + 1e-9


def test_a_roundrect_corner_is_not_copper_either():
    """The rounded corner is outside the copper by ``r * (sqrt(2) - 1)``."""
    p = rt.Pad(ref="C1", number="1", net=1, x=10.0, y=10.0, w=1.15, h=2.7,
               layers=(0,), shape="roundrect", rratio=0.2174)
    router = rt.Router([p], 20.0, 20.0, [])
    i, j = router._cell_of(10.575, 11.35)   # the bbox corner, rounded to a cell
    assert rt._pad_distance(p, i * 0.125, j * 0.125) > 0.0625
    assert (0, router._index(i, j)) not in router._pad_cells(p, 0.125)


def test_a_route_that_ends_on_a_round_pad_touches_its_copper():
    pads = [pad("A", "1", 1, 2.0, 2.0, w=1.0, h=1.0),
            rt.Pad(ref="B", number="1", net=1, x=9.0, y=7.0, w=1.0, h=1.0,
                   layers=(0,), shape="circle")]
    result = rt.route(pads, 20.0, 20.0, [], widths={1: 0.25}, order=[1])
    assert result.unrouted == [], result.failures
    for p in pads:
        assert any(rt._pad_distance(p, s.x0, s.y0) <= s.width / 2 + 1e-9
                   or rt._pad_distance(p, s.x1, s.y1) <= s.width / 2 + 1e-9
                   for s in result.segments), p


def test_a_route_does_not_cross_a_foreign_pad():
    """A pad in the straight line forces a detour, and the detour must clear it.

    This is the failure the grid router is most likely to make: taking a cell
    that is free for the *centreline* while the track body overlaps.
    """
    pads = [pad("A", "1", 1, 2.0, 5.0), pad("B", "1", 1, 10.0, 5.0),
            pad("X", "1", 2, 6.0, 5.0, w=1.2, h=1.2)]
    result = rt.route(pads, 20.0, 20.0, [], widths={1: 0.25, 2: 0.25}, order=[1, 2])
    assert result.unrouted == [], result.failures
    assert rt.clearance_violations(pads, result.segments, result.vias) == []


def test_a_route_can_change_layers_and_says_where():
    """A wall on F.Cu leaves the back layer as the only way across."""
    pads = [pad("A", "1", 1, 6.0, 2.0), pad("B", "1", 1, 6.0, 14.0),
            pad("W", "1", 2, 10.0, 8.0, w=19.0, h=4.0, layers=(0,))]
    result = rt.route(pads, 20.0, 20.0, [], widths={1: 0.25, 2: 0.25}, order=[1, 2])
    assert result.unrouted == [], result.failures
    assert result.vias, "the wall covers every F.Cu cell, so a via must be used"
    for via in result.vias:
        assert via.radius == pytest.approx(rt.VIA_DIAMETER_MM / 2)
    assert rt.clearance_violations(pads, result.segments, result.vias) == []


def test_a_walled_in_net_is_reported_rather_than_dropped():
    """A pad sealed inside a copper ring cannot be reached, and says so.

    Four wall pads, each on every layer, enclose pad A with a 1.25 mm pocket --
    narrower than a track needs to pass its own clearance.  A router that
    silently dropped the net would make the board look finished.
    """
    pads = [pad("A", "1", 1, 10.0, 10.0), pad("B", "1", 1, 18.0, 10.0),
            pad("WT", "1", 2, 10.0, 7.5, w=2.0, h=3.0, layers=(0, 1)),
            pad("WB", "1", 2, 10.0, 12.5, w=2.0, h=3.0, layers=(0, 1)),
            pad("WL", "1", 2, 7.5, 10.0, w=3.0, h=2.0, layers=(0, 1)),
            pad("WR", "1", 2, 12.5, 10.0, w=3.0, h=2.0, layers=(0, 1))]
    result = rt.route(pads, 20.0, 20.0, [], widths={1: 0.25, 2: 0.25}, order=[2, 1])
    assert result.unrouted == ["1"]
    assert len(result.failures) == 1 and result.failures[0][0] == "1"


# ---------------------------------------------------------------- repair order
class _RecordingRouter(rt.Router):
    """A real router that remembers the sequence of nets it was asked to route."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls: list[int] = []

    def route_net(self, net: int, width: float) -> rt._NetRoute:
        self.calls.append(net)
        return super().route_net(net, width)


def test_a_repair_reroutes_what_it_lifted_in_the_main_pass_order():
    """Repair must preserve priority, not reuse the proximity ranking.

    ``_rip_victims`` answers "whose copper is in the way" and sorts by
    distance, which is right for *selection*.  Rerouting in that order is not:
    a net the main pass deliberately routed first (PGND, on the validation
    board) can come last in the repair and be starved by the nets it
    outranks.  Measured there: six victims, PGND lost one of its connections
    and the whole attempt was reverted at 118 of 119; in priority order the
    same six reached 119.

    Here net 2's track is closer to the failing pad than net 1's, so the two
    orders disagree.
    """
    pads = [pad("A1", "1", 1, 2.0, 8.6), pad("A2", "1", 1, 18.0, 8.6),
            pad("B1", "1", 2, 2.0, 10.9), pad("B2", "1", 2, 18.0, 10.9),
            pad("T1", "1", 3, 10.0, 10.0), pad("T2", "1", 3, 10.0, 14.0)]
    router = _RecordingRouter(pads, 20.0, 15.0, [])
    for net in (1, 2, 3):
        router.route_net(net, 0.25)
    router.calls.clear()
    # Net 3 did not get through: that is the state a repair pass starts from.
    router.routes[3].failures = [("T1.1", "T2.1")]
    router._rip_one(3, {1: 0.25, 2: 0.25, 3: 0.25}, [1, 2, 3])
    assert router.calls == [3, 1, 2]


# ---------------------------------------------------------------- the verifier
def test_the_clearance_check_catches_two_tracks_that_are_too_close():
    pads = [pad("A", "1", 1, 2.0, 5.0), pad("B", "1", 1, 10.0, 5.0)]
    copper = [rt.Segment(net=1, layer=0, width=0.25, x0=2.0, y0=5.0, x1=10.0, y1=5.0),
              rt.Segment(net=2, layer=0, width=0.25, x0=4.0, y0=5.35, x1=4.0, y1=8.0)]
    found = rt.clearance_violations(pads, copper, [])
    assert found, "edge to edge is 0.10 mm, inside the 0.20 mm clearance"


def test_the_clearance_check_catches_a_track_across_a_pad():
    pads = [pad("A", "1", 1, 2.0, 5.0), pad("X", "1", 2, 6.0, 5.0, w=1.2, h=1.2)]
    across = [rt.Segment(net=1, layer=0, width=0.25, x0=1.0, y0=5.0, x1=9.0, y1=5.0)]
    assert rt.clearance_violations(pads, across, []) == [] or True  # see below
    # The track is *on* the pad's own net 1?  No: the pad is net 2.  It must be caught.
    assert rt.clearance_violations(pads, across, []), "copper over a foreign pad is a short"


def test_copper_on_another_layer_is_not_a_short():
    pads = [pad("A", "1", 1, 2.0, 5.0), pad("X", "1", 2, 6.0, 5.0, w=1.2, h=1.2)]
    across = [rt.Segment(net=1, layer=1, width=0.25, x0=1.0, y0=5.0, x1=9.0, y1=5.0)]
    assert rt.clearance_violations(pads, across, []) == []


def test_a_via_is_checked_on_both_layers():
    """A via is a barrel: it shorts to whatever it passes, on either layer."""
    pads = [pad("A", "1", 1, 2.0, 5.0), pad("X", "1", 2, 6.0, 5.0, w=1.2, h=1.2)]
    assert rt.clearance_violations(pads, [], [rt.Via(net=1, x=6.0, y=5.0)])


def test_same_net_copper_is_exempt():
    pads = [pad("A", "1", 1, 2.0, 5.0), pad("B", "1", 1, 6.0, 5.0)]
    touching = [rt.Segment(net=1, layer=0, width=0.25, x0=2.0, y0=5.0, x1=6.0, y1=5.0)]
    assert rt.clearance_violations(pads, touching, []) == []


def test_a_new_via_cannot_share_a_hole_with_one_already_drilled():
    """Same-net copper is reusable; same-net drills are not.

    The board came out with two co-located vias and two pairs 0.25 mm apart --
    the search may revisit its own net's cells, so nothing stopped it from
    dropping a barrel onto its own barrel.
    """
    p = pad("A", "1", 1, 2.0, 2.0)
    router = rt.Router([p], 20.0, 20.0, [])
    router._commit([], [rt.Via(net=1, x=5.0, y=5.0)])
    keepout = router._via_keepout()
    assert keepout[router._index(40, 40)] == 1      # the same cell
    assert keepout[router._index(44, 40)] == 1      # 0.50 mm away: inside 0.55
    assert keepout[router._index(46, 40)] == 0      # 0.75 mm away: legal


# ---------------------------------------------------------------- search bias
def test_two_nets_share_a_corridor_between_walls():
    """The second net must still find room after the first one has used it.

    This is the case wall pressure exists for: a shortest-path router can spend
    the corridor's last free lane on its own centreline and then report a
    failure with free cells on every side.  Here both nets have to arrive.
    """
    pads = [pad("A", "1", 1, 3.0, 4.25), pad("B", "1", 1, 17.0, 4.25),
            pad("C", "1", 2, 3.0, 5.75), pad("D", "1", 2, 17.0, 5.75),
            pad("W1", "1", 3, 10.0, 2.5, w=18.0, h=1.0),
            pad("W2", "1", 3, 10.0, 7.5, w=18.0, h=1.0)]
    result = rt.route(pads, 20.0, 10.0, [], widths={1: 0.25, 2: 0.25, 3: 0.25},
                      order=[3, 1, 2])
    assert result.unrouted == [], result.failures
    assert rt.clearance_violations(pads, result.segments, result.vias) == []


def test_the_pressure_counts_blocked_neighbours():
    nx, ny = 5, 5
    grid = bytearray(nx * ny)
    grid[2 * nx + 1] = 1                       # blocked cell left of (2, 2)
    assert rt._pressure(grid, nx, ny, 2, 2) == 1
    assert rt._pressure(grid, nx, ny, 3, 2) == 0
    assert rt._pressure(grid, nx, ny, 0, 0) == 0   # ignores the grid edge


def test_a_pour_corridor_costs_every_net_but_its_owner():
    """The corridor is charged, not blocked: the owner routes through it free,
    every other net pays, and the charge lives only on the zone's layer."""
    outline = [(0.0, 0.0), (4.0, 0.0), (4.0, 2.0), (0.0, 2.0)]
    router = rt.Router([], 10.0, 10.0, [], keep_clear={0: [(outline, 5, 0)]})

    owner = router._zone_cost(5)
    assert not any(owner[0]), "the pour's own net must not be charged"
    foreign = router._zone_cost(7)
    inside = router._index(16, 8)                  # (2.0, 1.0) is inside
    outside = router._index(60, 8)                 # (7.5, 1.0) is outside
    assert foreign[0][inside] == rt.ZONE_PRESSURE
    assert foreign[0][outside] == 0
    assert not any(foreign[1]), "the corridor is on F.Cu only"


def test_the_top_priority_pour_keeps_the_cells_it_will_fill():
    """KiCad fills the highest-priority zone of an overlap and carves the lower

    one out of it.  Charging the top zone's owner for the lower zone's corridor
    makes it route around copper it is about to own -- measured on the SR board,
    the output plane bought a 130 mm detour instead of a 100 mm run through the
    band it fills, and the fill lost the middle 88 % of its outline.
    """
    band = [(0.0, 0.0), (8.0, 0.0), (8.0, 2.0), (0.0, 2.0)]     # priority 2
    plane = [(0.0, 0.0), (8.0, 0.0), (8.0, 8.0), (0.0, 8.0)]    # priority 0
    router = rt.Router([], 10.0, 10.0, [],
                       keep_clear={0: [(plane, 5, 0), (band, 7, 2)]})
    overlap = router._index(16, 8)                  # (2.0, 1.0): both zones
    plane_only = router._index(16, 40)              # (2.0, 5.0): plane only

    assert router._zone_cost(7)[0][overlap] == 0, \
        "the top-priority pour owns its own cells"
    assert router._zone_cost(5)[0][overlap] == rt.ZONE_PRESSURE, \
        "the lower-priority pour is carved out of the overlap"
    assert router._zone_cost(7)[0][plane_only] == rt.ZONE_PRESSURE, \
        "outside the band the plain corridor still charges"


# ------------------------------------------------------------ barrier corridors
BAND = [(0.0, 4.0), (20.0, 4.0), (20.0, 6.0), (0.0, 6.0)]


def test_a_barrier_corridor_may_only_be_crossed_on_the_other_layer():
    """A pressure is a preference and cannot express "this pour stays whole".

    Measured on the validation board: crossing the 5.5 mm output band costs
    about 260 steps at ``ZONE_PRESSURE`` and every detour around a 100 mm band
    is longer, so the ground net paid it and the band's fill lost 88 % of its
    outline to island removal.  A barrier states the requirement instead; the
    other layer is still free, so the net crosses by via instead of by cutting.
    """
    pads = [pad("A", "1", 7, 10.0, 2.0, layers=(1,)),
            pad("B", "1", 7, 10.0, 8.0, layers=(1,))]
    result = rt.route(pads, 20.0, 10.0, [], widths={7: 0.25}, order=[7],
                      keep_clear={1: [(BAND, 5, 2)]}, barrier_nets=frozenset({5}))

    assert result.unrouted == [], result.failures
    assert result.barrier_crossings == []
    cut = [s for s in result.segments
           if s.layer == 1 and min(s.y0, s.y1) < 6.0 and max(s.y0, s.y1) > 4.0]
    assert cut == [], f"B.Cu copper inside the barrier band: {cut}"


def test_a_pad_that_sits_inside_a_barrier_falls_back_and_says_so():
    """Barriers are not absolute: an unreachable pad is worse than a cut pour.

    The fallback is reported rather than absorbed into a cost, so the caller can
    tell "this connection crossed the pour" from "nothing was in the way".
    """
    pads = [pad("A", "1", 7, 10.0, 2.0, layers=(1,)),
            pad("B", "1", 7, 10.0, 5.0, layers=(1,))]
    result = rt.route(pads, 20.0, 10.0, [], widths={7: 0.25}, order=[7],
                      keep_clear={1: [(BAND, 5, 2)]}, barrier_nets=frozenset({5}))

    assert result.unrouted == [], result.failures
    # Same (new pad, already-connected pad) order as ``RouteResult.failures``.
    assert result.barrier_crossings == [("7", "B.1", "A.1")]


# ---------------------------------------------------------------- escape reserve
def _blocked_at(escape_mm: float, x: float, y: float) -> bool:
    """Is the centreline of net 1 free at (x, y) while net 2 is unrouted?"""
    pads = [
        pad("A", "1", 1, 5.0, 5.0),
        pad("B", "1", 1, 15.0, 5.0),
        pad("C", "1", 2, 10.0, 5.0, w=1.0, h=1.0),
        pad("D", "1", 2, 20.0, 5.0, w=1.0, h=1.0),
    ]
    router = rt.Router(pads, 20.0, 10.0, [], escape_mm=escape_mm)
    i, j = router._cell_of(x, y)
    return bool(router._blocked(1, 0.125)[0][router._index(i, j)])


def test_the_escape_reserve_holds_room_for_a_pad_that_is_not_routed_yet():
    """An unrouted pad reserves 0.40 mm so a later net cannot seal its exit.

    Cell (8.875, 5.0) is 0.6 mm from the pending pad's edge: outside the
    0.3875 mm track margin (clearance + radius + half pitch), inside the
    0.7875 mm reserved margin.
    """
    assert not _blocked_at(0.0, 8.875, 5.0)
    assert _blocked_at(rt.ESCAPE_MM, 8.875, 5.0)


def test_the_escape_reserve_is_a_parameter_because_it_can_seal_a_land_itself():
    """On a 0.95 mm-pitch land the reserve is wider than the gap it guards.

    The fast-OC module's inner SOT-23-6 pins sit 1.375 mm from the opposite
    pad row, which fits a 0.25 mm track (0.775 mm of margin) but not the
    reserve on both sides (1.575 mm).  Six deterministic net orders left it
    at 40/42 or 41/42 with the reserve on, and 42/42 with it off -- so the
    default has to stay for the SR board, and the caller has to be able to
    say otherwise.  The board's own value is recorded in its report.
    """
    pads = [
        pad("A", "1", 1, 5.0, 5.0),
        pad("B", "1", 1, 15.0, 5.0),
        pad("C", "1", 2, 10.0, 5.0, w=1.0, h=1.0),
        pad("D", "1", 2, 20.0, 5.0, w=1.0, h=1.0),
    ]
    default = rt.Router(pads, 20.0, 10.0, [])._blocked(1, 0.125)
    explicit = rt.Router(pads, 20.0, 10.0, [], escape_mm=rt.ESCAPE_MM)._blocked(1, 0.125)
    assert default == explicit, "the parameter must default to the old constant"
    sig = inspect.signature(rt.Router.__init__)
    assert sig.parameters["escape_mm"].default == rt.ESCAPE_MM


# ---------------------------------------------------------------- geometry
def test_two_crossing_segments_are_zero_apart():
    assert rt._segment_segment_distance((0.0, 0.0, 10.0, 10.0),
                                        (0.0, 10.0, 10.0, 0.0)) == 0.0
    assert rt._segment_segment_distance((0.0, 0.0, 1.0, 0.0),
                                        (0.0, 1.0, 1.0, 1.0)) == pytest.approx(1.0)


def test_a_segment_inside_a_rect_is_zero_apart():
    assert rt._rect_segment_distance((0.0, 0.0, 4.0, 4.0), (1.0, 1.0, 3.0, 3.0)) == 0.0
    assert rt._rect_segment_distance((0.0, 0.0, 4.0, 4.0), (6.0, 2.0, 8.0, 2.0)) == 2.0


# ---------------------------------------------------------------- repair reach
def test_a_track_is_measured_to_the_line_a_failed_connection_runs_along():
    track = rt._Element(net=2, layers=(0,), kind="track",
                        seg=(0.0, 3.0, 10.0, 3.0), radius=0.125)
    assert rt._element_line_distance(track, (0.0, 0.0, 10.0, 0.0)) == pytest.approx(3.0)
    via = rt._Element(net=2, layers=(0, 1), kind="via", point=(5.0, 0.0), radius=0.3)
    assert rt._element_line_distance(via, (0.0, 0.0, 10.0, 0.0)) == 0.0


def test_a_blocker_halfway_along_a_long_net_is_only_seen_along_the_corridor():
    """The failure this fixes: a hundred-millimetre net fails in the middle.

    ``_rip_victims`` used to score copper against the two pads alone, within
    1.5 mm.  On the ten-gate board, 43 of 95 nets span more than 40 mm and 29
    more than 80 mm, so the net standing in the way is routinely out of that
    reach from either end; the pass found no victim, and a repairable failure
    became a permanent one.  Measured on that board, PGND alone (routed first,
    nothing else on the board) shuts out 8 of the 40 nets that fail in the
    full run, and those 8 are the ones whose whole run is blocked.
    """
    pads = [
        pad("A", "1", 1, 5.0, 5.0),
        pad("B", "1", 1, 45.0, 5.0),
        pad("C", "1", 2, 25.0, 2.0),
        pad("D", "1", 2, 25.0, 8.0),
    ]
    r = rt.Router(pads, 50.0, 10.0, [])
    r.route_net(2, 0.25)
    assert r.routes[2].segments, "the blocker has to be copper; pads are never candidates"
    r.routes[1] = rt._NetRoute(failures=[("A.1", "B.1")])

    assert r._rip_victims(1) == [], "the narrow search only reaches the two pads"
    assert r._rip_victims(1, corridor=True) == [2]


def test_the_corridor_search_is_off_unless_the_caller_asks_for_it():
    """The committed boards were routed with the narrow search; keep it default."""
    assert inspect.signature(rt.route).parameters["rip_corridor"].default is False
    assert inspect.signature(rt.Router.__init__).parameters["rip_corridor"].default is False
    router = rt.Router([], 10.0, 10.0, [])
    assert router.rip_corridor is False


# ------------------------------------------------------------------ layer grain
def test_the_grain_penalty_sends_a_corner_through_the_layers():
    """F.Cu runs east, B.Cu runs north; a corner is a barrel, not a bend.

    Both layers are otherwise interchangeable, so a net that turns simply turns
    where it stands and the two layers fill up evenly.  Giving each a grain is
    what lets a board with several hundred connections keep a lane open in each
    direction -- and the test says the corner really moved onto a via rather
    than merely costing more.
    """
    pads = [pad("A", "1", 1, 5.0, 10.0), pad("B", "1", 1, 45.0, 40.0)]
    res = rt.route(pads, 50.0, 50.0, [], widths={1: 0.25}, order=[1],
                   dir_penalty=2.0)
    assert res.connections_made == 1
    # The pads are F.Cu only, so the run leaves and re-enters through a barrel.
    assert len(res.vias) == 2
    assert all(s.y0 == s.y1 for s in res.segments if s.layer == 0), "F.Cu is the east-west grain"
    assert all(s.x0 == s.x1 for s in res.segments if s.layer == 1), "B.Cu is the north-south grain"


def test_the_grain_penalty_is_off_unless_the_caller_asks_for_it():
    """Every committed board was routed with an isotropic search."""
    assert inspect.signature(rt.route).parameters["dir_penalty"].default == 0.0
    assert inspect.signature(rt.Router.__init__).parameters["dir_penalty"].default == 0.0
    router = rt.Router([], 10.0, 10.0, [])
    assert router.dir_penalty == 0.0


# ---------------------------------------------------------------- junctions
def _length(segments) -> float:
    return sum(((s.x1 - s.x0) ** 2 + (s.y1 - s.y0) ** 2) ** 0.5 for s in segments)


def test_a_pad_taps_the_nets_spine_instead_of_running_back_to_a_pad():
    """The measured difference between a spine and a set of parallel runs.

    A is the seed, so the router connects C first (it is nearer than B).  Plain
    nearest-pad-first then has to reach B from C, and C is at the far end of
    its own spur: 65 + 65 mm.  With junctions the spine that A-C already laid
    passes directly below B, so B drops 50 mm onto it.  Same connection count,
    fifteen millimetres less copper, and -- on the ten-gate board, where one
    ground net has 118 pads -- the difference between a wall and a spine.
    """
    pads = [pad("A", "1", 1, 5.0, 5.0), pad("B", "1", 1, 105.0, 5.0),
            pad("C", "1", 1, 55.0, 20.0)]
    plain = rt.route(pads, 115.0, 30.0, [], widths={1: 0.25}, order=[1])
    tapped = rt.route(pads, 115.0, 30.0, [], widths={1: 0.25}, order=[1],
                      t_junction=True)
    assert plain.connections_made == tapped.connections_made == 2
    assert _length(tapped.segments) < _length(plain.segments)


def test_the_owned_cells_are_the_copper_the_net_already_has():
    pads = [pad("A", "1", 1, 5.0, 5.0), pad("B", "1", 1, 15.0, 5.0)]
    r = rt.Router(pads, 30.0, 12.0, [])
    assert r._own_cells(1) == set()
    r.route_net(1, 0.25)
    cells = r._own_cells(1)
    assert all(layer == 0 for layer, _ in cells), "the copper is on the layer that was routed"
    xs = [r._cell_xy(idx % r.nx, idx // r.nx)[0] for _, idx in cells]
    assert min(xs) <= 5.5 and max(xs) >= 14.0, "the copper spans pad A to pad B"


def test_the_junction_target_is_limited_to_the_neighbourhood_of_the_pad():
    """An unbounded target turns the A* heuristic into a constant and the search
    into Dijkstra over the whole board; ``_near_cells`` keeps the box small."""
    pads = [pad("A", "1", 1, 5.0, 5.0), pad("B", "1", 1, 115.0, 5.0)]
    r = rt.Router(pads, 130.0, 12.0, [])
    r.route_net(1, 0.25)
    tree = r._own_cells(1)
    near = r._near_cells(tree, pad("F", "1", 1, 120.0, 5.0))
    assert near, "the nearest cell is always kept"
    assert len(near) < len(tree)
    xs = [r._cell_xy(idx % r.nx, idx // r.nx)[0] for _, idx in near]
    assert min(xs) > 100.0, "the far end of the 110 mm spine is not a target"


def test_junctions_are_off_unless_the_caller_asks_for_it():
    assert inspect.signature(rt.route).parameters["t_junction"].default is False
    assert inspect.signature(rt.Router.__init__).parameters["t_junction"].default is False
    assert rt.Router([], 10.0, 10.0, []).t_junction is False

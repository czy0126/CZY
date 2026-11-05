"""Deterministic two-layer grid router for the single-pair SR validation board.

Why a router at all
-------------------
`make_sr_fault_board_pcb` stopped at placement: footprints and nets, no copper.
That is a layout, not a board that can be ordered, and the roadmap's next
deliverable is a fabricable SR validation PCB.  The routing job here is small
(30 nets, 147 pads, 132 x 92 mm, two layers) and the board is bench equipment
with a 10 A ceiling, so a grid router is enough -- and unlike a hand-drawn
ratsnest it can be re-run, diffed and tested.

What the router is told, and what it is not
-------------------------------------------
Widths, clearance and the via size are inputs, not discoveries: this module
never decides that a 3 mm loop is safe, it only guarantees that whatever width
it is given is respected and that nothing is routed closer than the clearance
it was given.  The power-loop widths come from `ROUTE_WIDTH_MM` in the board
generator, which records the current each net carries.

The one thing a grid router cannot do is judge: it will happily run a track
under a part, ignore the sense/shunt Kelvin split, and prefer a shorter path
over a better one.  So the placement -- not this file -- is what keeps
`VSS` off the power return; the router only has to not connect them.

Usage (through the board generator; this module has no CLI of its own):
    route(pads, width_mm, depth_mm, holes) -> RouteResult
"""

from __future__ import annotations

import heapq
import math
import re
from collections.abc import Iterator
from dataclasses import dataclass, field

import make_sr_fault_board as sch

PITCH_MM = 0.125           # parts sit on a 0.75 mm gap; see ``_corridor_ok``
CLEARANCE_MM = 0.20        # KiCad's default net clearance
EDGE_CLEARANCE_MM = 0.50   # copper to board edge
HOLE_CLEARANCE_MM = 0.25   # copper to a drilled hole wall
VIA_DIAMETER_MM = 0.6
VIA_DRILL_MM = 0.3
VIA_HOLE_SPACING_MM = 0.25  # KiCad's hole-to-hole minimum, edge to edge
VIA_COST_MM = 6.0          # a via costs the same as 6 mm of track
ESCAPE_MM = 0.40           # extra keep-out around a pad whose net is unrouted
WALL_PRESSURE = 2          # cell costs added per blocked orthogonal neighbour
ZONE_PRESSURE = 6          # cell costs for a foreign net inside a pour corridor
# Extra obstacle margin, on top of the clearance.  Clearance is stamped at cell
# centres, so between two cells it can read low by up to half a pitch; this is
# what makes the emitted copper clear the rule instead of the grid.
CLEARANCE_MARGIN_MM = PITCH_MM / 2.0
RIP_UP_ROUNDS = 4          # how many times a failed net may displace its neighbours
RIP_RADIUS_MM = 1.5        # how close an occupying track must be to be a candidate
RIP_MAX_VICTIMS = 6        # cap so one rip-up stays cheap and local

_NUM = r"(-?\d+(?:\.\d+)?)"
_DIRECTIONS = ((1, 0), (-1, 0), (0, 1), (0, -1))

# One pour corridor: its outline, the net that owns it, and its fill priority.
# The priority is KiCad's number -- the higher zone fills first and the lower
# one is carved out of the overlap -- so it decides which net owns a cell.
Zone = tuple[list[tuple[float, float]], int, int]
KeepClear = dict[int, list[Zone]]


@dataclass(frozen=True)
class Pad:
    """One copper pad, already placed in board coordinates."""

    ref: str
    number: str
    net: int                      # -1 when the pad carries no net
    x: float
    y: float
    w: float
    h: float
    layers: tuple[int, ...]       # 0 = F.Cu, 1 = B.Cu
    shape: str = "rect"           # rect | circle | oval | roundrect
    rratio: float = 0.0           # corner radius / min(w, h), roundrect only

    @property
    def rect(self) -> tuple[float, float, float, float]:
        return (self.x - self.w / 2, self.y - self.h / 2,
                self.x + self.w / 2, self.y + self.h / 2)


@dataclass(frozen=True)
class Segment:
    net: int
    layer: int
    width: float
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def radius(self) -> float:
        return self.width / 2.0


@dataclass(frozen=True)
class Via:
    net: int
    x: float
    y: float

    @property
    def radius(self) -> float:
        return VIA_DIAMETER_MM / 2.0


@dataclass
class RouteResult:
    segments: list[Segment] = field(default_factory=list)
    vias: list[Via] = field(default_factory=list)
    unrouted: list[str] = field(default_factory=list)
    failures: list[tuple[str, str, str]] = field(default_factory=list)
    # Connections that were made only by entering a corridor declared a
    # barrier; see ``Router.route_net``.
    barrier_crossings: list[tuple[str, str, str]] = field(default_factory=list)
    connections_attempted: int = 0
    connections_made: int = 0

    @property
    def complete(self) -> bool:
        return not self.unrouted


@dataclass
class _NetRoute:
    """One net's copper, kept separately so it can be lifted back off the board."""

    segments: list[Segment] = field(default_factory=list)
    vias: list[Via] = field(default_factory=list)
    failures: list[tuple[str, str]] = field(default_factory=list)   # pad pairs
    crossings: list[tuple[str, str]] = field(default_factory=list)  # barrier entries
    attempted: int = 0

    @property
    def made(self) -> int:
        return self.attempted - len(self.failures)


# ---------------------------------------------------------------- pads
def extract_pads(text: str, ref: str, ox: float, oy: float,
                 net_of) -> list[Pad]:
    """Every copper pad of one footprint, in board coordinates.

    A pad with no copper layer is skipped: it can never be a routing endpoint
    and is not copper either.  A pad with copper but no number is *kept*, with
    net -1: it is a metal island another net still has to clear, and dropping
    it would let a track run over it.  Pad rotation is folded into
    width/height -- all placements here are upright, but a library pad may be
    drawn sideways.
    """
    out: list[Pad] = []
    i = 0
    while True:
        j = text.find("(pad ", i)
        if j < 0:
            break
        end = sch.block_end(text, j)
        block = text[j:end]
        i = end
        head = re.match(r'\(pad "([^"]*)"\s+(\S+)\s+(\S+)', block)
        if head is None:
            continue
        number = head.group(1)                    # smd / thru_hole / np_thru_hole
        at = re.search(rf"\(at {_NUM} {_NUM}(?: {_NUM})?\)", block)
        size = re.search(rf"\(size {_NUM} {_NUM}\)", block)
        if at is None or size is None:
            continue
        rot = float(at.group(3)) if at.group(3) else 0.0
        w, h = float(size.group(1)), float(size.group(2))
        if int(round(rot)) % 180 == 90:
            w, h = h, w
        layers = _copper_layers(block)
        if not layers:
            continue
        # An unnamed land has no net by definition, whatever the callback says:
        # the schematic refers to pads by number, and "" is not a number.
        net = net_of(ref, number) if number else -1
        rratio = re.search(rf"\(roundrect_rratio {_NUM}\)", block)
        out.append(Pad(ref=ref, number=number, net=net,
                       x=ox + float(at.group(1)), y=oy + float(at.group(2)),
                       w=w, h=h, layers=layers, shape=head.group(3),
                       rratio=float(rratio.group(1)) if rratio else 0.0))
    return out


def _copper_layers(block: str) -> tuple[int, ...]:
    match = re.search(r"\(layers ([^)]*)\)", block)
    if match is None:
        return ()
    names = set(re.findall(r'"([^"]*)"', match.group(1)))
    layers = []
    if names & {"*.Cu", "F&B.Cu", "F.Cu"}:
        layers.append(0)
    if names & {"*.Cu", "F&B.Cu", "B.Cu"}:
        layers.append(1)
    return tuple(layers)


# ---------------------------------------------------------------- geometry
def _rect_distance(px: float, py: float,
                   rect: tuple[float, float, float, float]) -> float:
    x0, y0, x1, y1 = rect
    dx = max(x0 - px, 0.0, px - x1)
    dy = max(y0 - py, 0.0, py - y1)
    return math.hypot(dx, dy)


def _pad_distance(pad: Pad, x: float, y: float) -> float:
    """Shortest distance from a point to the pad's *copper*, by its shape.

    A pad is not its bounding box.  On the validation board 114 lands are
    roundrects and 30 are circles, so the bbox corner can be 0.1-0.2 mm away
    from metal.  A track that stops there overlaps the rectangle the router
    imagined and nothing kicad-cli can see: TP17 came out dangling with its
    track end exactly on a 1 mm circle's bbox corner.

    Unknown shapes fall back to the bbox, which is conservative for clearance
    and optimistic for landing -- `_pad_cells` then still lands inside.
    """
    x0, y0, x1, y1 = pad.rect
    if pad.shape == "circle":
        return max(0.0, math.hypot(x - pad.x, y - pad.y) - min(pad.w, pad.h) / 2.0)
    if pad.shape == "oval":
        r = min(pad.w, pad.h) / 2.0
        seg = ((x0 + r, pad.y, x1 - r, pad.y) if pad.w >= pad.h
               else (pad.x, y0 + r, pad.x, y1 - r))
        return max(0.0, _segment_distance(x, y, *seg) - r)
    if pad.shape == "roundrect" and pad.rratio > 0.0:
        r = pad.rratio * min(pad.w, pad.h)
        core = (x0 + r, y0 + r, x1 - r, y1 - r)
        if core[0] > core[2] or core[1] > core[3]:     # corner radius swallows an axis
            core = (pad.x, pad.y, pad.x, pad.y)
        return max(0.0, _rect_distance(x, y, core) - r)
    return _rect_distance(x, y, pad.rect)


def _segment_distance(px: float, py: float, x0: float, y0: float,
                      x1: float, y1: float) -> float:
    vx, vy = x1 - x0, y1 - y0
    wx, wy = px - x0, py - y0
    length2 = vx * vx + vy * vy
    t = 0.0 if length2 == 0.0 else max(0.0, min(1.0, (wx * vx + wy * vy) / length2))
    return math.hypot(px - (x0 + t * vx), py - (y0 + t * vy))


def _segment_segment_distance(a: tuple[float, float, float, float],
                              b: tuple[float, float, float, float]) -> float:
    """Shortest distance between two line segments (crossing -> 0)."""
    ax, ay, bx, by = a
    cx, cy, dx, dy = b

    def orient(px, py, qx, qy, rx, ry):
        return (qx - px) * (ry - py) - (qy - py) * (rx - px)

    def on_seg(px, py, qx, qy, rx, ry):
        return (min(px, qx) <= rx <= max(px, qx)
                and min(py, qy) <= ry <= max(py, qy))

    d1 = orient(ax, ay, bx, by, cx, cy)
    d2 = orient(ax, ay, bx, by, dx, dy)
    d3 = orient(cx, cy, dx, dy, ax, ay)
    d4 = orient(cx, cy, dx, dy, bx, by)
    if ((d1 > 0 >= d2) or (d1 < 0 <= d2)) and ((d3 > 0 >= d4) or (d3 < 0 <= d4)):
        return 0.0
    if d1 == 0 and on_seg(ax, ay, bx, by, cx, cy):
        return 0.0
    if d2 == 0 and on_seg(ax, ay, bx, by, dx, dy):
        return 0.0
    return min(_segment_distance(cx, cy, ax, ay, bx, by),
               _segment_distance(dx, dy, ax, ay, bx, by),
               _segment_distance(ax, ay, cx, cy, dx, dy),
               _segment_distance(bx, by, cx, cy, dx, dy))


def _rect_segment_distance(rect: tuple[float, float, float, float],
                           seg: tuple[float, float, float, float]) -> float:
    x0, y0, x1, y1 = rect
    cx, cy, dx, dy = seg
    if x0 <= cx <= x1 and y0 <= cy <= y1:
        return 0.0
    if x0 <= dx <= x1 and y0 <= dy <= y1:
        return 0.0
    edges = ((x0, y0, x1, y0), (x1, y0, x1, y1),
             (x1, y1, x0, y1), (x0, y1, x0, y0))
    return min(_segment_segment_distance(seg, edge) for edge in edges)


def _point_in_polygon(poly: list[tuple[float, float]], x: float, y: float) -> bool:
    """Ray-cast test; the pour outlines are simple polygons (rectangles and one L)."""
    inside = False
    n = len(poly)
    for k in range(n):
        x0, y0 = poly[k]
        x1, y1 = poly[(k + 1) % n]
        if (y0 > y) != (y1 > y):
            if x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
                inside = not inside
    return inside


def _pressure(grid: bytearray, nx: int, ny: int, i: int, j: int) -> int:
    """How many orthogonal neighbours of cell ``(i, j)`` are blocked.

    A pure shortest-path router hugs whatever it is routing past, because the
    inside of a corridor and its edge cost the same.  The copper then closes
    the corridor behind itself and a later net -- with abundant free cells
    everywhere -- finds no way through.  Charging a small extra cost per
    blocked neighbour makes a route prefer the middle of a gap, which is what
    leaves room for the nets that come after.
    """
    count = 0
    for di, dj in _DIRECTIONS:
        ni, nj = i + di, j + dj
        if 0 <= ni < nx and 0 <= nj < ny and grid[nj * nx + ni]:
            count += 1
    return count


def _rect_rect_distance(a: tuple[float, float, float, float],
                        b: tuple[float, float, float, float]) -> float:
    dx = max(a[0] - b[2], 0.0, b[0] - a[2])
    dy = max(a[1] - b[3], 0.0, b[1] - a[3])
    return math.hypot(dx, dy)


def _pair_distance(a: "_Element", b: "_Element") -> float:
    """Centreline-to-edge distance: subtract both radii to get edge-to-edge."""
    if a.kind == "pad" and b.kind == "pad":
        return _rect_rect_distance(a.rect, b.rect)
    if a.kind == "via" and b.kind == "via":
        return math.hypot(a.point[0] - b.point[0], a.point[1] - b.point[1])
    if a.kind == "pad" and b.kind == "track":
        return _rect_segment_distance(a.rect, b.seg)
    if a.kind == "track" and b.kind == "pad":
        return _rect_segment_distance(b.rect, a.seg)
    if a.kind == "track" and b.kind == "track":
        return _segment_segment_distance(a.seg, b.seg)
    if a.kind == "via":
        return _pair_distance(b, a)
    if b.kind == "via":
        if a.kind == "pad":
            return _rect_distance(b.point[0], b.point[1], a.rect)
        return _segment_distance(b.point[0], b.point[1], *a.seg)
    raise ValueError(f"unhandled pair {a.kind}/{b.kind}")


@dataclass(frozen=True)
class _Element:
    """Anything already on the board that another net has to keep away from."""

    net: int
    layers: tuple[int, ...]
    kind: str                                   # "pad" | "track" | "via"
    rect: tuple[float, float, float, float] | None = None
    seg: tuple[float, float, float, float] | None = None
    point: tuple[float, float] | None = None
    radius: float = 0.0


def _element_rect_distance(el: _Element,
                           rect: tuple[float, float, float, float]) -> float:
    """Centreline distance from one element to a rectangle (pads included)."""
    if el.kind == "track":
        return _rect_segment_distance(rect, el.seg)
    if el.kind == "via":
        return _rect_distance(el.point[0], el.point[1], rect)
    return _rect_rect_distance(el.rect, rect)


def _element_line_distance(el: _Element,
                           line: tuple[float, float, float, float]) -> float:
    """Centreline distance from one element to a straight line segment.

    Exact for the two kinds the rip-up pass scores -- a track and a via -- and
    a corner sample for a pad, which the pass never asks about.
    """
    if el.kind == "track":
        return _segment_segment_distance(el.seg, line)
    if el.kind == "via":
        return _segment_distance(el.point[0], el.point[1], *line)
    x0, y0, x1, y1 = el.rect
    corners = ((x0, y0, x0, y0), (x1, y0, x1, y0), (x1, y1, x1, y1), (x0, y1, x0, y1))
    return min(_rect_segment_distance(c, line) for c in corners)


class Router:
    """Clearance-respecting Manhattan router on a square grid."""

    def __init__(self, pads: list[Pad], width_mm: float, depth_mm: float,
                 holes: list[tuple[float, float]], *,
                 pitch: float = PITCH_MM,
                 keep_clear: KeepClear | None = None,
                 escape_mm: float = ESCAPE_MM,
                 rip_corridor: bool = False,
                 dir_penalty: float = 0.0,
                 t_junction: bool = False,
                 barrier_nets: frozenset[int] | None = None
                 ) -> None:
        self.pads = pads
        self.width_mm = width_mm
        self.depth_mm = depth_mm
        self.holes = holes
        self.pitch = pitch
        # Room kept around a pad whose net is not routed yet, so the pads that
        # come later cannot seal its last exit.  It is a parameter because on a
        # fine-pitch land the reserve is wider than the gap it is guarding: the
        # fast-OC module's inner SOT-23-6 pins sit 1.375 mm from the opposite
        # row, which fits a 0.25 mm track (0.775 mm) but not this on both sides.
        self.escape_mm = escape_mm
        # Whether the repair pass looks for blockers along the whole run of a
        # failed connection or only around its two pads.  Off by default
        # because it changes which nets get lifted, and the boards that are
        # already committed were routed with the narrow search.
        self.rip_corridor = rip_corridor
        # Extra cost, in grid steps, for moving across the grain of a layer.
        # Without it the two layers are interchangeable, so a net that runs
        # fifty millimetres east spreads itself over both and neither layer
        # keeps a lane open for the nets that have to run north.  Giving F.Cu
        # the horizontal grain and B.Cu the vertical one makes vias the only
        # way to turn a corner, which is what a hand-routed board looks like
        # and what lets a 415-connection board fit in two layers.  Zero keeps
        # the isotropic search the committed boards were routed with.
        self.dir_penalty = dir_penalty
        # Whether a pad may be joined by tapping the net's own copper instead of
        # running a fresh path back to a pad that is already connected.  Off by
        # default: without it every connection is an independent point-to-point
        # run, which on a 118-pad ground net lays 117 long parallel traces where
        # a hand router would lay short spurs off one spine.
        self.t_junction = t_junction
        # ``keep_clear[layer]`` is ``(outline, net, priority)`` triples: cells
        # inside the outline cost extra for every net but the one that ends up
        # owning the cell.  This is how a pour corridor stays a corridor -- a
        # track that crosses it splits the fill, and a split fill is deleted as
        # an island unless it touches a pad.  The priority matters because the
        # zones overlap: see ``_zone_cost``.
        self.keep_clear = keep_clear or {}
        # Nets whose pour corridors are walls rather than prices.  A pressure is
        # a preference: it wins when the detour is longer than the charge, which
        # is exactly the wrong answer for a band that has to stay continuous.
        # See ``_zone_barrier`` and ``route_net``.
        self.barrier_nets = barrier_nets or frozenset()
        self._zone_cache: dict[int, list[bytearray]] = {}
        self._barrier_cache: dict[int, list[list[int]] | None] = {}
        self._owners: list[dict[int, tuple[int, set[int]]]] | None = None
        self.nx = int(round(width_mm / pitch)) + 1
        self.ny = int(round(depth_mm / pitch)) + 1
        self.n = self.nx * self.ny
        self.elements: list[_Element] = [
            _Element(net=p.net, layers=p.layers, kind="pad", rect=p.rect)
            for p in pads]
        self.routes: dict[int, _NetRoute] = {}
        self._pad_count: dict[int, int] = {}
        for p in pads:
            if p.net >= 0:
                self._pad_count[p.net] = self._pad_count.get(p.net, 0) + 1

    @property
    def pending(self) -> set[int]:
        """Nets whose pads still need a connection, and are routable at all.

        Their pads get a wider keep-out so an earlier net cannot wall off the
        only way out -- a 0603 land at (57.16, 34.73) went from "nothing within
        1.25 mm" to zero free cells before this existed.

        This is derived, not a set that callers maintain: a net stays pending
        while it is unrouted *or still has failed connections*, so a rip-up pass
        sees the same protection the main pass did.  A one-pad net is never
        pending -- there is nothing to connect, and holding a keep-out around it
        forever would shrink the board for no reason.
        """
        return {net for net, count in self._pad_count.items()
                if count > 1 and (net not in self.routes or self.routes[net].failures)}

    # ------------------------------------------------------------ grid helpers
    def _index(self, i: int, j: int) -> int:
        return j * self.nx + i

    def _cell_xy(self, i: int, j: int) -> tuple[float, float]:
        return i * self.pitch, j * self.pitch

    def _cell_of(self, x: float, y: float) -> tuple[int, int]:
        return int(round(x / self.pitch)), int(round(y / self.pitch))

    def _stamp_rect(self, buf: bytearray, rect: tuple[float, float, float, float],
                    margin: float) -> None:
        x0, y0, x1, y1 = rect
        i0 = max(0, int(math.floor((x0 - margin) / self.pitch)))
        i1 = min(self.nx - 1, int(math.ceil((x1 + margin) / self.pitch)))
        j0 = max(0, int(math.floor((y0 - margin) / self.pitch)))
        j1 = min(self.ny - 1, int(math.ceil((y1 + margin) / self.pitch)))
        for j in range(j0, j1 + 1):
            py = j * self.pitch
            for i in range(i0, i1 + 1):
                if _rect_distance(i * self.pitch, py, rect) <= margin:
                    buf[self._index(i, j)] = 1

    def _stamp_segment(self, buf: bytearray, seg: tuple[float, float, float, float],
                       radius: float) -> None:
        x0, y0, x1, y1 = seg
        i0 = max(0, int(math.floor((min(x0, x1) - radius) / self.pitch)))
        i1 = min(self.nx - 1, int(math.ceil((max(x0, x1) + radius) / self.pitch)))
        j0 = max(0, int(math.floor((min(y0, y1) - radius) / self.pitch)))
        j1 = min(self.ny - 1, int(math.ceil((max(y0, y1) + radius) / self.pitch)))
        for j in range(j0, j1 + 1):
            py = j * self.pitch
            for i in range(i0, i1 + 1):
                if _segment_distance(i * self.pitch, py, x0, y0, x1, y1) <= radius:
                    buf[self._index(i, j)] = 1

    def _stamp_disc(self, buf: bytearray, cx: float, cy: float, radius: float) -> None:
        i0 = max(0, int(math.floor((cx - radius) / self.pitch)))
        i1 = min(self.nx - 1, int(math.ceil((cx + radius) / self.pitch)))
        j0 = max(0, int(math.floor((cy - radius) / self.pitch)))
        j1 = min(self.ny - 1, int(math.ceil((cy + radius) / self.pitch)))
        for j in range(j0, j1 + 1):
            py = j * self.pitch
            for i in range(i0, i1 + 1):
                if math.hypot(i * self.pitch - cx, py - cy) <= radius:
                    buf[self._index(i, j)] = 1

    # ------------------------------------------------------------ obstacles
    def _blocked(self, net: int, radius: float) -> list[bytearray]:
        """Two grids of cells this net's centreline may not enter.

        Every foreign element is inflated by the clearance plus *both* copper
        radii, so the guarantee is edge-to-edge, not centre-to-centre.  Callers
        build two of these -- one at the track radius, one at the via radius --
        because stamping every path cell as via-capable closes corridors the
        board really has (a 0603 land gave zero free cells the first time).
        A layer change is then gated on the wide grid instead.

        The margin carries an extra half pitch.  Clearance is stamped at cell
        centres only, and the distance to a convex element is 1-Lipschitz, so a
        segment passing between two sampled cells can dip up to ``pitch / 2``
        below the stamped value.  Without the extra margin the search accepts
        copper that KiCad then reports: a SEC_B/SR_SRC pair came out at 0.152 mm
        against 0.20 mm -- inside the grid's own tolerance, outside the rule.
        """
        buf = [bytearray(self.n), bytearray(self.n)]
        for el in self.elements:
            if el.net >= 0 and el.net == net:
                continue
            margin = CLEARANCE_MM + radius + el.radius
            if el.kind != "pad":
                margin += CLEARANCE_MARGIN_MM
            if el.kind == "pad" and el.net in self.pending:
                margin += self.escape_mm
            for layer in el.layers:
                if el.kind == "pad":
                    self._stamp_rect(buf[layer], el.rect, margin)
                elif el.kind == "track":
                    self._stamp_segment(buf[layer], el.seg, margin)
                else:
                    self._stamp_disc(buf[layer], el.point[0], el.point[1], margin)
        for hx, hy in self.holes:
            r = 1.6 + HOLE_CLEARANCE_MM + radius      # 1.6 = M3 mounting hole radius
            for layer in (0, 1):
                self._stamp_disc(buf[layer], hx, hy, r)
        return buf

    def _via_keepout(self) -> bytearray:
        """Cells where a new barrel would be too close to one already drilled.

        ``_blocked`` exempts the net's own copper, which is what lets a later
        pad join an existing route.  That exemption also let the search drop a
        via on top of one of its own vias: the board came out with two
        co-located drills and two pairs 0.25 mm apart, both DRC errors.  Two
        tracks of one net may share copper; two drills may not share a hole.
        """
        buf = bytearray(self.n)
        spacing = VIA_DRILL_MM + VIA_HOLE_SPACING_MM
        for el in self.elements:
            if el.kind == "via":
                self._stamp_disc(buf, el.point[0], el.point[1], spacing)
        return buf

    def _zone_cells(self, outline: list[tuple[float, float]]) -> Iterator[int]:
        """Grid indices whose centre falls inside ``outline``."""
        xs = [p[0] for p in outline]
        ys = [p[1] for p in outline]
        i0 = max(0, int(math.floor(min(xs) / self.pitch)))
        i1 = min(self.nx - 1, int(math.ceil(max(xs) / self.pitch)))
        j0 = max(0, int(math.floor(min(ys) / self.pitch)))
        j1 = min(self.ny - 1, int(math.ceil(max(ys) / self.pitch)))
        for j in range(j0, j1 + 1):
            y = j * self.pitch
            for i in range(i0, i1 + 1):
                if _point_in_polygon(outline, i * self.pitch, y):
                    yield self._index(i, j)

    def _zone_owners(self) -> list[dict[int, tuple[int, set[int]]]]:
        """Cell -> ``(priority, owners at that priority)``, per layer.

        KiCad fills the highest-priority zone covering a cell and carves the
        lower ones out of it, so a cell belongs to the top priority's owners and
        to nobody else.  Both the pressure and the barrier are defined on this
        map rather than on the raw outlines; computing it once keeps the two
        from disagreeing about who owns an overlap.
        """
        if self._owners is None:
            top: list[dict[int, tuple[int, set[int]]]] = [{}, {}]
            for layer, zones in self.keep_clear.items():
                for outline, owner, priority in zones:
                    for idx in self._zone_cells(outline):
                        held = top[layer].get(idx)
                        if held is None or priority > held[0]:
                            top[layer][idx] = (priority, {owner})
                        elif priority == held[0]:
                            held[1].add(owner)
            self._owners = top
        return self._owners

    def _zone_cost(self, net: int) -> list[bytearray]:
        """Per-cell extra cost for routing ``net`` through a pour corridor.

        Cells are charged, not blocked.  Blocking them would be the cleaner
        statement, but every signal that crosses a corridor needs *some* way
        across, and a hard wall would turn a routing detour into an unrouted
        net.  Pressure buys the same geometry without that failure mode: a
        12.5 mm crossing costs 100 steps, a detour around the corridor costs
        the detour's length, and the search takes whichever is shorter.

        A cell belongs to the highest-priority pour that covers it, because
        that is the one KiCad fills; the lower ones are carved out of the
        overlap.  A net that owns the top zone of a cell will get copper there,
        so charging it for the lower zone underneath would send it around
        copper it is about to own.  Measured on the SR board: the output plane
        paid the ground plane's pressure for the band it fills, bought a 130 mm
        detour instead of a 100 mm run through that band, and the fill lost the
        middle 88 % of its outline to island removal.

        The pressure alone does not settle the case it was added for.  Crossing
        the 5.5 mm output band is 44 cells, about 260 steps at
        ``ZONE_PRESSURE``, and a detour around a
        100 mm band costs more, so a foreign track still cut it.  That is what
        ``_zone_barrier`` is for; this cost stays as the ordering rule for
        everything else.
        """
        cached = self._zone_cache.get(net)
        if cached is not None:
            return cached
        cost = [bytearray(self.n), bytearray(self.n)]
        for layer, cells in enumerate(self._zone_owners()):
            for idx, (_, owners) in cells.items():
                if net not in owners:
                    cost[layer][idx] = ZONE_PRESSURE
        self._zone_cache[net] = cost
        return cost

    def _zone_barrier(self, net: int) -> list[list[int]] | None:
        """Cells ``net`` may not enter, or ``None`` if nothing is barred.

        Only the corridors of ``barrier_nets`` are barred, and only on their own
        layer, so a net that must get from one side to the other still has the
        other layer plus a via at each end.

        Why a wall and not a bigger price: a pour is a conductor only while its
        fill is continuous, and ``island_removal_mode 0`` deletes every piece
        that reaches none of the net's own copper -- one foreign track across a
        band removes everything it cut off.  Measured on the validation board,
        the ground net paid the pressure and the output band kept 11 % of its
        outline.  Raising the price to the point where the detour wins instead
        makes the search explore the whole board (unfinished after 15 minutes,
        against 3 at the shipped value), so the requirement is stated as a
        blocked cell and not as a large number.
        """
        if not self.barrier_nets:
            return None
        if net in self._barrier_cache:
            return self._barrier_cache[net]
        wall: list[list[int]] = [[], []]
        for layer, cells in enumerate(self._zone_owners()):
            for idx, (_, owners) in cells.items():
                if net in owners or not (owners & self.barrier_nets):
                    continue
                wall[layer].append(idx)
        barred: list[list[int]] | None = wall if any(wall) else None
        self._barrier_cache[net] = barred
        return barred

    def _inside_board(self, i: int, j: int, radius: float) -> bool:
        margin = EDGE_CLEARANCE_MM + radius
        x, y = self._cell_xy(i, j)
        return (margin <= x <= self.width_mm - margin
                and margin <= y <= self.depth_mm - margin)

    # ------------------------------------------------------------ search
    def _track_cells(self, layer: int, seg: tuple[float, float, float, float]
                     ) -> set[tuple[int, int]]:
        """Grid cells a straight run covers, as ``(layer, index)`` pairs."""
        x0, y0, x1, y1 = seg
        steps = max(1, int(math.ceil(math.hypot(x1 - x0, y1 - y0) / self.pitch)))
        cells: set[tuple[int, int]] = set()
        for k in range(steps + 1):
            t = k / steps
            i = int(round((x0 + (x1 - x0) * t) / self.pitch))
            j = int(round((y0 + (y1 - y0) * t) / self.pitch))
            if 0 <= i < self.nx and 0 <= j < self.ny:
                cells.add((layer, self._index(i, j)))
        return cells

    def _own_cells(self, net: int) -> set[tuple[int, int]]:
        """Every cell this net's committed copper already occupies."""
        cells: set[tuple[int, int]] = set()
        for el in self.elements:
            if el.net != net:
                continue
            if el.kind == "track":
                cells |= self._track_cells(el.layers[0], el.seg)
            elif el.kind == "via":
                i = int(round(el.point[0] / self.pitch))
                j = int(round(el.point[1] / self.pitch))
                if 0 <= i < self.nx and 0 <= j < self.ny:
                    cells |= {(layer, self._index(i, j)) for layer in el.layers}
        return cells

    def _near_cells(self, cells: set[tuple[int, int]], pad: Pad,
                    reach_mm: float = 6.0) -> set[tuple[int, int]]:
        """The part of a tree worth aiming at from ``pad``.

        The A* heuristic is the distance to the bounding box of the target, so
        handing it a hundred-millimetre tree turns the search into Dijkstra over
        the whole board.  Aiming at the nearest cell and its neighbourhood keeps
        the box small and still finds the spur a hand router would draw.
        """
        scored = []
        for layer, idx in cells:
            x, y = self._cell_xy(idx % self.nx, idx // self.nx)
            scored.append((abs(x - pad.x) + abs(y - pad.y), layer, idx))
        if not scored:
            return set()
        nearest = min(d for d, _, _ in scored)
        limit = nearest + reach_mm
        return {(layer, idx) for d, layer, idx in scored if d <= limit}

    def _pad_cells(self, pad: Pad, radius: float) -> set[tuple[int, int]]:
        """Cells a track may stop on and still touch ``pad``'s copper.

        A cell whose centre is inside the pad overlaps it whatever the end cap
        does, so those are tried first.  A pad narrower than one grid step has
        no such cell; there the set falls back to cells within half the track
        radius of the pad copper, which the cap still covers.  Half a *pitch*
        of slack -- what this used to use -- reaches cells the cap does not, so
        a route could legally finish 0.13-0.24 mm short of its pad and the
        board would report every net connected while kicad-cli saw it dangling.

        The distance is to the pad's shape, not its bounding box: on a circle
        the bbox corner is 0.21 mm from metal on a 1 mm pad.
        """
        x0, y0, x1, y1 = pad.rect
        for margin in (0.0, radius / 2.0):
            i0 = int(math.floor((x0 - margin) / self.pitch))
            i1 = int(math.ceil((x1 + margin) / self.pitch))
            j0 = int(math.floor((y0 - margin) / self.pitch))
            j1 = int(math.ceil((y1 + margin) / self.pitch))
            cells = {(layer, self._index(i, j))
                     for layer in pad.layers
                     for i in range(max(0, i0), min(self.nx - 1, i1) + 1)
                     for j in range(max(0, j0), min(self.ny - 1, j1) + 1)
                     if _pad_distance(pad, i * self.pitch, j * self.pitch) <= margin + 1e-9}
            if cells:
                return cells
        return set()

    def _search(self, blocked: list[bytearray], via_blocked: list[bytearray],
                via_keepout: bytearray, radius: float, source: set[tuple[int, int]],
                target: set[tuple[int, int]],
                zone: list[bytearray] | None = None) -> list[tuple[int, int]] | None:
        """A* from any source cell to any target cell, 4-neighbour + vias."""
        if not source or not target:
            return None
        ti = [t[1] % self.nx for t in target]
        tj = [t[1] // self.nx for t in target]
        bi, bj = (min(ti) + max(ti)) / 2.0, (min(tj) + max(tj)) / 2.0
        span_i = (max(ti) - min(ti)) / 2.0
        span_j = (max(tj) - min(tj)) / 2.0

        def heuristic(idx: int) -> float:
            i, j = idx % self.nx, idx // self.nx
            return max(0.0, abs(i - bi) - span_i) + max(0.0, abs(j - bj) - span_j)

        via_steps = int(round(VIA_COST_MM / self.pitch))
        start = list(source)
        best: dict[tuple[int, int], float] = {}
        came: dict[tuple[int, int], tuple[int, int] | None] = {}
        heap: list[tuple[float, int, int, int]] = []
        for layer, idx in start:
            node = (layer, idx)
            best[node] = 0.0
            came[node] = None
            heapq.heappush(heap, (heuristic(idx), 0, layer, idx))
        target_set = set(target)
        while heap:
            f, g, layer, idx = heapq.heappop(heap)
            node = (layer, idx)
            if g > best.get(node, math.inf):
                continue
            if node in target_set:
                path = []
                cur: tuple[int, int] | None = node
                while cur is not None:
                    path.append(cur)
                    cur = came[cur]
                return list(reversed(path))
            i, j = idx % self.nx, idx // self.nx
            grid = blocked[layer]
            # Same layer, four directions.
            for di, dj in _DIRECTIONS:
                ni, nj = i + di, j + dj
                if not (0 <= ni < self.nx and 0 <= nj < self.ny):
                    continue
                nidx = self._index(ni, nj)
                if grid[nidx] and (layer, nidx) not in source:
                    continue
                if not self._inside_board(ni, nj, radius) and (layer, nidx) not in source:
                    continue
                nnode = (layer, nidx)
                # Running across the grain of the layer costs extra; see
                # ``Router.__init__``.  The heuristic stays admissible because
                # every step still costs at least one.
                against = (dj != 0) if layer == 0 else (di != 0)
                ng = (g + 1 + (self.dir_penalty if against else 0.0)
                      + WALL_PRESSURE * _pressure(grid, self.nx, self.ny, ni, nj))
                if zone is not None:
                    ng += zone[layer][nidx]
                if ng < best.get(nnode, math.inf):
                    best[nnode] = ng
                    came[nnode] = node
                    heapq.heappush(heap, (ng + heuristic(nidx), ng, layer, nidx))
            # Layer change at the same cell: a via, which is wider than the
            # track and must therefore clear the whole via radius.
            other = 1 - layer
            nnode = (other, idx)
            # A via is a barrel through both layers, so both grids must be free
            # at that cell.  Pad cells are exempt: a via landing on its own pad
            # is via-in-pad, ordinary practice.  An existing drill is never
            # exempt, not even on the same net: two barrels cannot share a hole.
            via_ok = (not (via_blocked[layer][idx] or via_blocked[other][idx])
                      or nnode in source)
            if via_ok and not via_keepout[idx]:
                ng = g + via_steps
                if zone is not None:
                    # A barrel through a corridor cuts it exactly like a track.
                    ng += zone[layer][idx]
                if ng < best.get(nnode, math.inf):
                    best[nnode] = ng
                    came[nnode] = node
                    heapq.heappush(heap, (ng + heuristic(idx), ng, other, idx))
        return None

    # ------------------------------------------------------------ routing
    def _path_to_geometry(self, path: list[tuple[int, int]], net: int,
                          width: float) -> tuple[list[Segment], list[Via]]:
        """Merge the cell path into straight runs plus the vias at layer changes."""
        segments: list[Segment] = []
        vias: list[Via] = []
        run_start = path[0]
        prev = path[0]
        heading: tuple[int, int] | None = None
        for node in path[1:]:
            layer, idx = node
            if layer != prev[0]:
                # The run ends here and a barrel takes over.
                segments.extend(self._runs(run_start, prev, net, width))
                x, y = self._cell_xy(idx % self.nx, idx // self.nx)
                vias.append(Via(net=net, x=x, y=y))
                run_start = node
                heading = None
            else:
                step = (idx % self.nx - prev[1] % self.nx,
                        idx // self.nx - prev[1] // self.nx)
                if heading is not None and step != heading:
                    # A turn: close the run at the corner, not at the end of
                    # the previous step.  Comparing one step with the axes
                    # instead of one step with the last would make every step
                    # "collinear" and emit a diagonal that the search never
                    # cleared -- SN1 came out crossing a pad at 0.19 mm.
                    segments.extend(self._runs(run_start, prev, net, width))
                    run_start = prev
                heading = step
            prev = node
        segments.extend(self._runs(run_start, prev, net, width))
        return segments, vias

    def _runs(self, a: tuple[int, int], b: tuple[int, int], net: int,
              width: float) -> list[Segment]:
        if a == b:
            return []
        x0, y0 = self._cell_xy(a[1] % self.nx, a[1] // self.nx)
        x1, y1 = self._cell_xy(b[1] % self.nx, b[1] // self.nx)
        return [Segment(net=net, layer=a[0], width=width, x0=x0, y0=y0, x1=x1, y1=y1)]

    def _commit(self, segments: list[Segment], vias: list[Via]) -> None:
        for s in segments:
            self.elements.append(_Element(net=s.net, layers=(s.layer,), kind="track",
                                          seg=(s.x0, s.y0, s.x1, s.y1),
                                          radius=s.radius))
        for v in vias:
            self.elements.append(_Element(net=v.net, layers=(0, 1), kind="via",
                                          point=(v.x, v.y), radius=v.radius))

    def route_net(self, net: int, width: float) -> _NetRoute:
        """Connect every pad of one net, nearest-pad-first, and commit the copper."""
        route = _NetRoute()
        pads = [p for p in self.pads if p.net == net]
        if len(pads) < 2:
            self.routes[net] = route
            return route
        radius = width / 2.0
        connected = [pads[0]]
        remaining = pads[1:]
        # Copper this net already has on the board.  A connection that reaches
        # it is a junction, not a missed pad: the tree is one connected piece of
        # metal by construction, so touching it at any point is electrical.
        tree = self._own_cells(net) if self.t_junction else set()
        while remaining:
            best = None
            for a in connected:
                for b in remaining:
                    d = math.hypot(a.x - b.x, a.y - b.y)
                    if best is None or d < best[0]:
                        best = (d, a, b)
            _, dst_pad, src_pad = best
            blocked = self._blocked(net, radius)
            via_blocked = self._blocked(net, VIA_DIAMETER_MM / 2.0)
            source = self._pad_cells(src_pad, radius)
            target = self._pad_cells(dst_pad, radius)
            if tree:
                target |= self._near_cells(tree, dst_pad)
            wall = self._zone_barrier(net)
            route.attempted += 1
            path = None
            if wall is not None:
                path = self._search(_with_wall(blocked, wall),
                                    _with_wall(via_blocked, wall),
                                    self._via_keepout(), radius, source, target,
                                    self._zone_cost(net))
            if path is None:
                # A barred corridor is a requirement, not a guarantee: a pad
                # that sits inside one cannot be reached any other way, and an
                # unrouted pad is worse than a cut pour.  Record it so the
                # caller can see which connection it was.
                path = self._search(blocked, via_blocked, self._via_keepout(),
                                    radius, source, target, self._zone_cost(net))
                if path is not None and wall is not None:
                    route.crossings.append(
                        (f"{src_pad.ref}.{src_pad.number}", f"{dst_pad.ref}.{dst_pad.number}"))
            if path is None:
                route.failures.append(
                    (f"{src_pad.ref}.{src_pad.number}", f"{dst_pad.ref}.{dst_pad.number}"))
                remaining.remove(src_pad)
                continue
            segments, vias = self._path_to_geometry(path, net, width)
            self._commit(segments, vias)
            route.segments.extend(segments)
            route.vias.extend(vias)
            if self.t_junction:
                for s in segments:
                    tree |= self._track_cells(s.layer, (s.x0, s.y0, s.x1, s.y1))
                for v in vias:
                    i = int(round(v.x / self.pitch))
                    j = int(round(v.y / self.pitch))
                    if 0 <= i < self.nx and 0 <= j < self.ny:
                        tree |= {(layer, self._index(i, j)) for layer in (0, 1)}
            connected.append(src_pad)
            remaining.remove(src_pad)
        self.routes[net] = route
        return route

    def unroute(self, net: int) -> _NetRoute | None:
        """Lift one net's copper off the board and return what was lifted."""
        route = self.routes.pop(net, None)
        if route is not None:
            self.elements = [el for el in self.elements
                             if not (el.net == net and el.kind in ("track", "via"))]
        return route

    def _put(self, net: int, route: _NetRoute) -> None:
        self._commit(route.segments, route.vias)
        self.routes[net] = route

    # ------------------------------------------------------------ rip-up
    def _made(self) -> int:
        return sum(route.made for route in self.routes.values())

    def _rip_victims(self, net: int, *, radius: float = RIP_RADIUS_MM,
                     limit: int = RIP_MAX_VICTIMS,
                     corridor: bool = False) -> list[int]:
        """Foreign nets whose copper is nearest the pads ``net`` failed to reach.

        A failed connection is nearly always a corridor somebody else took
        first, so the candidates are the nets occupying the cells around the
        two endpoints -- not the whole board.  Pads are never candidates: they
        are where the parts are, and ripping one out is placement, not routing.

        ``corridor`` also scores copper against the straight line between the
        two endpoints.  Endpoint proximity answers "who is standing on the
        door", which is the whole story on a dense little board; on a board
        with hundred-millimetre nets the blocker is usually halfway along, out
        of reach of ``radius`` from either pad, so the pass finds no victim and
        the failure is silently permanent.  Tracks and vias are measured to the
        line exactly; pads are still never candidates.
        """
        by_name = {f"{p.ref}.{p.number}": p for p in self.pads}
        scored: dict[int, float] = {}
        for a, b in self.routes[net].failures:
            pads = [by_name[n] for n in (a, b) if n in by_name]
            line = ((pads[0].x, pads[0].y, pads[1].x, pads[1].y)
                    if corridor and len(pads) == 2 else None)
            for el in self.elements:
                if el.net < 0 or el.net == net or el.kind == "pad":
                    continue
                d = min((_element_rect_distance(el, pad.rect) for pad in pads),
                        default=math.inf)
                if line is not None:
                    d = min(d, _element_line_distance(el, line))
                if d <= radius and d < scored.get(el.net, math.inf):
                    scored[el.net] = d
        return [n for n, _ in sorted(scored.items(), key=lambda kv: (kv[1], kv[0]))[:limit]]

    def rip_up(self, order: list[int], widths: dict[int, float]) -> None:
        """Reroute failed nets after lifting the copper that stands in their way.

        Each attempt is kept only if the board gains connections, otherwise the
        lifted routes go back exactly as they were.  That makes the pass
        monotone: it can never end worse than it started, and it cannot
        oscillate between two arrangements.
        """
        for _ in range(RIP_UP_ROUNDS):
            failing = [n for n in order if n in self.routes and self.routes[n].failures]
            if not failing:
                return
            for net in failing:
                self._rip_one(net, widths, order)

    def _rip_one(self, net: int, widths: dict[int, float], order: list[int]) -> None:
        """Lift the nets in the way, reroute them in the main pass's priority.

        Selection and rerouting want opposite orderings.  ``_rip_victims``
        answers "whose copper is in the way" and sorts by distance, which is
        right for picking them.  Putting it back in that order is not: on the
        validation board it scheduled PGND -- the first net the main pass
        routes, because a wide power net needs the pick of the board -- behind
        five signal nets, and PGND lost one of its eleven connections.  The
        board stayed at 118 of 119 and the monotone check threw the whole
        repair away.  In ``order`` the same six nets reach 119.
        """
        victims = self._rip_victims(net, corridor=self.rip_corridor)
        if not victims:
            return
        rank = {n: k for k, n in enumerate(order)}
        victims.sort(key=lambda n: rank.get(n, len(rank)))
        before = self._made()
        saved = [(n, self.unroute(n)) for n in [net, *victims]]
        self.route_net(net, widths[net])
        for n in victims:
            self.route_net(n, widths[n])
        if self._made() > before:
            return
        for n, _ in saved:
            self.unroute(n)
        for n, route in saved:
            if route is not None:
                self._put(n, route)

    def result(self, order: list[int]) -> RouteResult:
        """The whole board as one aggregate, in the order the caller asked for."""
        out = RouteResult()
        for net in order:
            route = self.routes.get(net)
            if route is None:
                continue
            out.segments.extend(route.segments)
            out.vias.extend(route.vias)
            out.connections_attempted += route.attempted
            out.connections_made += route.made
            if route.failures:
                out.unrouted.append(str(net))
                out.failures.extend((str(net), a, b) for a, b in route.failures)
            out.barrier_crossings.extend((str(net), a, b) for a, b in route.crossings)
        out.segments = _merge(out.segments)
        return out


def route(pads: list[Pad], width_mm: float, depth_mm: float,
          holes: list[tuple[float, float]], *,
          widths: dict[int, float], order: list[int],
          keep_clear: KeepClear | None = None,
          escape_mm: float = ESCAPE_MM,
          rip_corridor: bool = False,
          dir_penalty: float = 0.0,
          t_junction: bool = False,
          barrier_nets: frozenset[int] | None = None
          ) -> RouteResult:
    """Route ``order`` (net indices) with the given widths, then repair failures.

    ``keep_clear`` discourages every net but the cell's owner from routing
    through a pour corridor; see ``Router._zone_cost``.  ``escape_mm`` is the
    room kept around a pad whose net is still unrouted; see ``Router.__init__``.
    ``rip_corridor`` widens the repair pass from the endpoints of a failed
    connection to its whole run; see ``Router._rip_victims``.  ``dir_penalty``
    gives each layer a grain, F.Cu horizontal and B.Cu vertical; see
    ``Router.__init__``.  ``t_junction`` lets a pad tap the net's own copper
    instead of running a fresh path to a connected pad; see
    ``Router.route_net``.  ``barrier_nets`` names the pours whose corridors are
    walls rather than prices -- copper may not enter them at all unless the
    connection has no other way, and those connections come back in
    ``RouteResult.barrier_crossings``; see ``Router._zone_barrier``.
    """
    router = Router(pads, width_mm, depth_mm, holes, keep_clear=keep_clear,
                    escape_mm=escape_mm, rip_corridor=rip_corridor,
                    dir_penalty=dir_penalty, t_junction=t_junction,
                    barrier_nets=barrier_nets)
    for net in order:
        router.route_net(net, widths[net])
    router.rip_up(order, widths)
    return router.result(order)


def _with_wall(grids: list[bytearray], wall: list[list[int]]) -> list[bytearray]:
    """The obstacle grids plus every barred cell, as a fresh copy."""
    out = [bytearray(g) for g in grids]
    for layer, cells in enumerate(wall):
        grid = out[layer]
        for idx in cells:
            grid[idx] = 1
    return out


def _merge(segments: list[Segment]) -> list[Segment]:
    """Drop zero-length segments (a run of one cell emits none)."""
    return [s for s in segments
            if abs(s.x0 - s.x1) >= 1e-9 or abs(s.y0 - s.y1) >= 1e-9]


# ---------------------------------------------------------------- verification
def _copper_items(pads: list[Pad], segments: list[Segment],
                  vias: list[Via]) -> list[_Element]:
    """Every piece of copper on the board as one element."""
    items = [_Element(net=p.net, layers=p.layers, kind="pad", rect=p.rect, radius=0.0)
             for p in pads]
    items += [_Element(net=s.net, layers=(s.layer,), kind="track",
                       seg=(s.x0, s.y0, s.x1, s.y1), radius=s.radius)
              for s in segments]
    items += [_Element(net=v.net, layers=(0, 1), kind="via", point=(v.x, v.y),
                       radius=v.radius) for v in vias]
    return items


def _bbox(el: _Element, margin: float) -> tuple[float, float, float, float]:
    r = el.radius + margin
    if el.kind == "pad":
        x0, y0, x1, y1 = el.rect
        return (x0 - margin, y0 - margin, x1 + margin, y1 + margin)
    if el.kind == "track":
        x0, y0, x1, y1 = el.seg
        return (min(x0, x1) - r, min(y0, y1) - r, max(x0, x1) + r, max(y0, y1) + r)
    return (el.point[0] - r, el.point[1] - r, el.point[0] + r, el.point[1] + r)


def _layers(el: _Element) -> tuple[int, ...]:
    return (0, 1) if el.kind == "via" else el.layers


def clearance_violations(pads: list[Pad], segments: list[Segment], vias: list[Via], *,
                         clearance: float = CLEARANCE_MM,
                         tolerance: float = PITCH_MM / 2.0) -> list[dict]:
    """Pairs of different-net copper closer than ``clearance``.

    This is the router's own invariant, checked on the copper that is actually
    emitted rather than on the grid it was searched on.  CI has no KiCad, and a
    ``unconnected_items == 0`` result says nothing about shorts; DRC in this
    repository can only be run by whoever has ``kicad-cli`` installed.

    ``tolerance`` is half a pitch because the search stamps clearance at grid
    points: the distance function is 1-Lipschitz, so a segment that passes
    between two sampled points can dip below the stamped value by at most
    ``pitch / 2``.  Reporting against the exact clearance would flag copper the
    search legitimately accepted; reporting against ``clearance / 2`` would flag
    nothing at all.
    """
    items = _copper_items(pads, segments, vias)
    boxes = [_bbox(el, clearance) for el in items]
    order = sorted(range(len(items)), key=lambda k: boxes[k][0])
    found: list[dict] = []
    for a_pos, a in enumerate(order):
        ax0, ay0, ax1, ay1 = boxes[a]
        for b in order[a_pos + 1:]:
            bx0, by0, bx1, by1 = boxes[b]
            if bx0 > ax1:
                break
            if by0 > ay1 or ay0 > by1:
                continue
            ea, eb = items[a], items[b]
            if ea.net == eb.net:
                continue
            if not set(_layers(ea)) & set(_layers(eb)):
                continue
            gap = _pair_distance(ea, eb) - ea.radius - eb.radius
            if gap < clearance - tolerance:
                found.append({"a": _describe(ea), "b": _describe(eb),
                              "gap_mm": round(gap, 4)})
    return found


def _describe(el: _Element) -> str:
    where = el.rect if el.rect is not None else el.seg if el.seg is not None else el.point
    return f"net {el.net} {el.kind} {tuple(round(v, 2) for v in where)}"

"""Routed copper for the A5 power-stage placement.

Why this module exists
----------------------
``hardware/dcx_mech/power_stage_placement.kicad_pcb`` is a netlist on a board:
70 footprints, 60 nets, 242 named pads and 134 ratsnest lines.  That is enough
to judge placement, and the roadmap says it is not enough to count as layout
work ("无网络机械板不再算A6推进").  This module turns the same placement into a
routed board -- every net with more than one pad gets copper -- and then
*measures* the copper instead of describing it.

What it deliberately does not do
--------------------------------
Tracks are not a 100 A conductor, and nothing here pretends otherwise.  The
report carries the series resistance of the actual routed path from each
secondary source to the output terminal, at 1/2/4 oz and 100 C, next to the
0.15 mOhm design basis.  That comparison is the point: it turns "the power
path still needs planes" from an opinion into arithmetic.

There are two track widths, and the split is part of that arithmetic.  The two
nets the basis is measured through keep the 0.8 mm reference width so the
comparison means something; every other net is a 0.25 mm connectivity
placeholder, because the status line already says ampacity is not met and a
wider placeholder only takes lanes away from its neighbours.

The second half of that arithmetic is the pour study.  A zone alone says
nothing, so the module pours both output nets solid over the whole board,
refills them with kicad-cli, rasterises the resulting copper and solves the
resistance mesh between source pads and the output terminal.  That is the
*upper bound* -- the most any copper on this board could do -- and it is still
several times the basis, which is why the busbar, not the plane, has to carry
the output current.  It is not a layout: the full-board pour bridges every SR
solder-mask aperture, and the report says so rather than hiding it.

The placement board is an input, never a target
-----------------------------------------------
``main_board_mechanical.write()`` owns ``power_stage_placement.kicad_pcb`` and
its tests compare it byte for byte.  This module reads it and writes a
*separate* file, so routing cannot quietly change what the placement report
claims.  If the placement is regenerated, the routed board goes stale -- and
``--check`` re-routes from the placement and compares bytes, which is exactly
the signal we want.

Usage:
    python tools/main_board_power_copper.py --json hardware/dcx_mech/routed_copper.json
    python tools/main_board_power_copper.py --check
"""

from __future__ import annotations

import argparse
import heapq
import json
import math
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import main_board_mechanical as a5  # noqa: E402
import make_sr_fault_board as sch  # noqa: E402
import output_path_budget as opb  # noqa: E402
import sr_board_router as router  # noqa: E402

OUT = a5.OUT
PLACEMENT = OUT / "power_stage_placement.kicad_pcb"
BOARD = OUT / "power_stage_routed.kicad_pcb"
PROJECT = OUT / "power_stage_routed.kicad_pro"
REPORT = OUT / "routed_copper.json"
DRC = OUT / "routed_drc.json"

# Two widths, and each one has a reason that is recorded rather than assumed.
#
# ``OUTPUT_NETS`` keep the 0.8 mm reference width because ``path_budget`` walks
# VOUT and PGND and because ``what_a_track_would_need`` answers in that width --
# "a track would have to be wider than the board" is a statement about 0.8 mm.
#
# Every other net on this board is a *connectivity placeholder*.  The board has
# said ``AMPACITY_NOT_MET`` since it was first routed, so a wider track bought no
# rating -- and it cost a lane every time it crossed one.  The twelve-volt bus is
# what that cost: pin 7 of each UCC24624 shares a 1.27 mm column with pins 5/6/8
# (0.67 mm of air between 0.6 mm pads), and an 0.8 mm track with 0.2 mm clearance
# needs 1.2 mm, so ``VCC12_S`` could not leave three of its four pins.
POWER_WIDTH_MM = 0.8
SIGNAL_WIDTH_MM = 0.25

STATUS = "ROUTED_DRAFT_CONNECTIVITY_ONLY_AMPACITY_NOT_MET"

# Nets whose series path the 0.15 mOhm output budget is measured against.
OUTPUT_NETS = ("PGND", "VOUT")


# ---------------------------------------------------------------- placement
def placement_text(path: Path | None = None) -> str:
    path = path or PLACEMENT
    if not path.is_file():
        raise SystemExit(f"{path} is missing -- run tools/main_board_mechanical.py first; "
                         "this module routes a placement, it does not place parts")
    return path.read_text(encoding="utf-8")


@dataclass(frozen=True)
class Block:
    """One ``(footprint ...)`` instance lifted out of the board file."""

    ref: str
    value: str
    x: float
    y: float
    text: str


def blocks(text: str) -> list[Block]:
    """Every placed footprint, in file order.

    Parentheses are matched, not regexed: a footprint block contains nested
    ``(at)``/``(size)``/``(property)`` groups and a regex that stopped at the
    first ``)`` would hand ``extract_pads`` half a block.
    """
    out: list[Block] = []
    i = 0
    while True:
        j = text.find("(footprint ", i)
        if j < 0:
            return out
        end = sch.block_end(text, j)
        block = text[j:end]
        i = end
        ref = re.search(r'\(property "Reference" "([^"]+)"', block)
        val = re.search(r'\(property "Value" "([^"]*)"', block)
        at = re.search(r"\(at (-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?)", block)
        if ref is None or at is None:
            continue
        out.append(Block(ref.group(1), val.group(1) if val else "",
                         float(at.group(1)), float(at.group(2)), block))


def net_table() -> dict[str, int]:
    """Net name -> index, numbered exactly as the placement board numbers them.

    The router works in integers and the board file in names; both sides read
    this one table, so a track can never land on the wrong net.
    """
    return {net: i for i, net in enumerate(sorted(a5.placed_nets()), start=1)}


def pads_of(text: str, ids: dict[str, int]) -> list[router.Pad]:
    """Every copper pad on the board, in board coordinates, with its net."""
    by_ref = {part.ref: part for part in a5.PARTS}
    out: list[router.Pad] = []
    for block in blocks(text):
        part = by_ref.get(block.ref)
        nets = a5.part_nets(part) if part is not None else {}

        def net_of(ref: str, number: str, table=nets) -> int:
            name = table.get(number)
            return ids.get(name, -1) if name else -1

        out.extend(router.extract_pads(block.text, block.ref, block.x, block.y, net_of))
    return out


# ---------------------------------------------------------------- routing
def width_of(net: str) -> float:
    """The only place the two widths meet a net name.

    Keeping this a function rather than a dict comprehension is deliberate:
    ``route_plan`` and ``report`` must agree, and when they were written out
    twice the report kept claiming one width for every net for a whole stage.
    """
    return POWER_WIDTH_MM if net in OUTPUT_NETS else SIGNAL_WIDTH_MM


def route_plan(pads: list[router.Pad], ids: dict[str, int],
               ) -> tuple[dict[int, float], list[int], list[str]]:
    """Which nets get copper, at what width, in what order.

    Ordered by pad count, descending.  The net with the most pads (PGND, dozens
    of them) owns the board's real corridors; letting the two-pad nets go first
    would let them take the only lanes wide enough for it.  Nets with one pad are
    not routable at all and are reported instead of silently dropped.
    """
    count: dict[int, int] = defaultdict(int)
    for pad in pads:
        if pad.net >= 0:
            count[pad.net] += 1
    routable = sorted((n for n, c in count.items() if c >= 2),
                      key=lambda n: (-count[n], n))
    single = sorted((n for n, c in count.items() if c < 2), key=lambda n: n)
    name = {i: n for n, i in ids.items()}
    widths = {n: width_of(name[n]) for n in routable}
    return widths, routable, [name[n] for n in single]


def route_board(text: str) -> tuple[router.RouteResult, dict[str, int], list[router.Pad], list[str]]:
    ids = net_table()
    pads = pads_of(text, ids)
    widths, order, single = route_plan(pads, ids)
    w, d = a5.board_rect()
    result = router.route(pads, w, d, [], widths=widths, order=order)
    return result, ids, pads, single


# ---------------------------------------------------------------- board file
def _guard(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(msg)


def board_file(placement: str, result: router.RouteResult, ids: dict[str, int]) -> str:
    """The placement board with copper appended, and nothing else changed.

    Two document-level strings are rewritten on purpose: the title block's
    comment still said "no routing", and the generator name would claim the
    placement tool wrote copper it never routed.  Both replacements are
    guarded -- if upstream rewords them this fails loudly instead of writing a
    board that misdescribes itself.
    """
    was = '(comment 1 "NETTED PLACEMENT - no routing; every ratsnest line is a missing track")'
    now = ('(comment 1 "ROUTED DRAFT - connectivity complete, ampacity NOT met; '
           'see routed_copper.json")')
    _guard(was in placement,
           "the placement board's comment line changed; update board_file() so the "
           "routed board cannot describe itself as unrouted")
    body = placement.replace(was, now, 1).replace(
        '(generator "main_board_mechanical")',
        '(generator "main_board_power_copper")', 1)
    end = body.rstrip().rfind(")")
    _guard(end > 0, "the placement board is not a parenthesised KiCad board file")
    out = [body[:end]]
    out.extend(copper_lines(result))
    out.append(")\n")
    return "".join(out)


def copper_lines(result: router.RouteResult) -> list[str]:
    """``(segment ...)`` and ``(via ...)`` records, in route order.

    UUIDs are positional, so the same placement always produces the same bytes
    -- the routed board is reproducible without KiCad, which is what lets
    ``--check`` compare it in CI.
    """
    layers = {0: "F.Cu", 1: "B.Cu"}
    out = []
    for k, s in enumerate(result.segments):
        out.append(f'\t(segment (start {s.x0:g} {s.y0:g}) (end {s.x1:g} {s.y1:g})'
                   f' (width {s.width:g}) (layer "{layers[s.layer]}")'
                   f' (net {s.net}) (uuid "{a5.uid("segment", str(k))}"))\n')
    for k, v in enumerate(result.vias):
        out.append(f'\t(via (at {v.x:g} {v.y:g}) (size {v.radius * 2:g})'
                   f' (drill {router.VIA_DRILL_MM:g}) (layers "F.Cu" "B.Cu")'
                   f' (net {v.net}) (uuid "{a5.uid("via", str(k))}"))\n')
    return out


def project_file() -> str:
    """The routed board's ``.kicad_pro``, from the placement's, renamed.

    ``kicad-cli`` pairs a board with the project of the same stem; without one
    it never loads ``fp-lib-table`` and every ``dcx:`` footprint is reported as
    an unknown library -- and an unresolved footprint has no courtyard, so DRC
    silently stops checking it.  ``missing_courtyard`` stays raised to error.
    """
    data = json.loads(a5.project_file())
    data["meta"]["filename"] = PROJECT.name
    return json.dumps(data, indent=2) + "\n"


# ---------------------------------------------------------------- measurement
def _nodes_of(result: router.RouteResult) -> dict[int, dict[tuple[int, float, float], list]]:
    """Adjacency per net over the copper that was actually emitted.

    Segments are axis-aligned and their endpoints are grid coordinates, so two
    segments that meet share an exactly equal key.  Vias join the two layers at
    a point.  Nothing here assumes the router used ``t_junction``: a path that
    starts and ends at pads is all this needs.
    """
    adj: dict[int, dict[tuple[int, float, float], list[tuple[tuple[int, float, float], float]]]] = \
        defaultdict(lambda: defaultdict(list))
    for s in result.segments:
        a = (s.layer, round(s.x0, 3), round(s.y0, 3))
        b = (s.layer, round(s.x1, 3), round(s.y1, 3))
        length = math.hypot(s.x1 - s.x0, s.y1 - s.y0)
        adj[s.net][a].append((b, length, s.width))
        adj[s.net][b].append((a, length, s.width))
    for v in result.vias:
        a = (0, round(v.x, 3), round(v.y, 3))
        b = (1, round(v.x, 3), round(v.y, 3))
        adj[v.net][a].append((b, 0.0, 0.0))
        adj[v.net][b].append((a, 0.0, 0.0))
    return dict(adj)


def _attach(pad: router.Pad, nodes) -> list[tuple[int, float, float]]:
    """Nodes whose track end-cap actually overlaps this pad's copper.

    The test is the router's own ``_pad_distance``: a track "lands" on a pad
    when the distance from its end cell to the metal is at most half a width.
    A looser radius would join a track that merely runs past the pad, and a
    path that is measured through copper it does not touch is shorter than the
    real one -- the direction of error that flatters the design.
    """
    # ``path_squares`` is only ever asked about an output net (the two-pad
    # reach of ``what_a_track_would_need`` and the per-group budget both walk
    # VOUT and PGND), so the power width is the width of every track this
    # graph can see.
    half = POWER_WIDTH_MM / 2.0
    return [n for n in nodes
            if n[0] in pad.layers
            and router._pad_distance(pad, n[1], n[2]) <= half + 1e-6]


def _pad_key(pad: router.Pad) -> tuple[str, str, str]:
    """One electrical node per *pin*, not per copper piece.

    Eight of the SR lands carry five pads named ``5`` (drain base plus four
    fingers) and four named ``1``.  KiCad treats same-numbered pads of one
    footprint as a single pin, and so must this graph: otherwise a path that
    enters the base and leaves a finger looks like a break.
    """
    return ("pad", pad.ref, pad.number)


def _with_pads(result: router.RouteResult, pads: list[router.Pad], net: int) -> dict:
    """Segment and via graph plus one zero-cost node per pad of ``net``.

    Tracks meet each other *inside a pad*, not at a shared grid point: two
    connections of the same net leave from different cells of the same land,
    so a graph built only from segment endpoints is cut into a dozen pieces
    (VOUT came out as eight components before this contraction).  The pad is
    the junction, so the pad is the node.
    """
    graph = {k: list(v) for k, v in _nodes_of(result).get(net, {}).items()}
    for pad in pads:
        if pad.net != net:
            continue
        key = _pad_key(pad)
        for node in _attach(pad, graph):
            graph.setdefault(key, []).append((node, 0.0, 0.0))
            graph[node].append((key, 0.0, 0.0))
    return graph


def path_squares(result: router.RouteResult, pads: list[router.Pad],
                 pad_a: router.Pad, pad_b: router.Pad) -> dict | None:
    """Shortest copper path between two pins: length and squares.

    Squares are summed per segment as ``length / width``, so a path that
    changes width reports the right number instead of the length over one
    width.  ``None`` means the two pins are not on connected copper -- a fact
    worth reporting rather than smoothing over.
    """
    graph = _with_pads(result, pads, pad_a.net)
    start, goal = _pad_key(pad_a), _pad_key(pad_b)
    if start not in graph or goal not in graph:
        return None
    best: dict = {start: 0.0}
    # The tie-breaker is a counter, not the node: node keys are a mix of
    # ``(layer, x, y)`` and ``("pad", ref, number)`` and comparing those on an
    # equal distance raises TypeError.
    heap = [(0.0, 0, start, 0.0)]
    seq = 1
    while heap:
        d, _, node, sq = heapq.heappop(heap)
        if node == goal:
            return {"length_mm": round(d, 3), "squares": round(sq, 4)}
        if d > best.get(node, math.inf) + 1e-9:
            continue
        for nxt, length, width in graph[node]:
            nd = d + length
            if nd < best.get(nxt, math.inf) - 1e-9:
                best[nxt] = nd
                heapq.heappush(heap, (nd, seq, nxt,
                                      sq + (length / width if width else 0.0)))
                seq += 1
    return None


def path_budget(result: router.RouteResult, pads: list[router.Pad]) -> dict:
    """What the routed copper actually costs, per output group, per copper weight.

    The budget is the same 0.15 mOhm the published 92.33 % efficiency uses
    (``output_path_budget``).  The number computed here is the *series* path
    through one branch of a routed tree: current really spreads over the other
    branches too, so this is an upper bound, the same way the plane study is.
    """
    by_ref = defaultdict(dict)
    for pad in pads:
        by_ref[pad.ref][pad.number] = pad
    out_pad, gnd_pad = by_ref["J_OUT"].get("1"), by_ref["J_OUT"].get("2")
    rows = []
    for group in range(1, 5):
        sec = by_ref[f"T{group}"].get("CTAP")
        src = by_ref[f"SR{group}A"].get("1")
        row = {"group": group}
        for label, a, b in (("vout", sec, out_pad), ("pgnd", src, gnd_pad)):
            if a is None or b is None:
                row[label] = None
                continue
            row[label] = path_squares(result, pads, a, b)
        rows.append(row)
    weights = {}
    for name, ounces in (("1oz", 1.0), ("2oz", 2.0), ("4oz", 4.0)):
        sheet = opb.sheet_ohm_square(ounces * opb.OZ_M)
        table = []
        for row in rows:
            entry = {"group": row["group"]}
            for key in ("vout", "pgnd"):
                path = row[key]
                entry[key] = (None if path is None else
                              {"squares": path["squares"],
                               "r_mohm": round(path["squares"] * sheet * 1e3, 3)})
            entry["r_mohm"] = (None if entry["vout"] is None or entry["pgnd"] is None
                               else round(entry["vout"]["r_mohm"] + entry["pgnd"]["r_mohm"], 3))
            table.append(entry)
        weights[name] = table
    worst = [w["r_mohm"] for w in weights["2oz"] if w["r_mohm"] is not None]
    return {
        "design_basis_mohm": round(opb.DESIGN_BASIS_OHM * 1e3, 3),
        "basis_source": "output_path_budget.DESIGN_BASIS_OHM (same basis as the "
                        "published 92.33 % efficiency)",
        "sheet_mohm_per_square": {k: round(opb.sheet_ohm_square(o * opb.OZ_M) * 1e3, 4)
                                  for k, o in (("1oz", 1.0), ("2oz", 2.0), ("4oz", 4.0))},
        "temperature_c": opb.T_C,
        "method": "tracks only: shortest copper path through the routed tree from each "
                  "secondary source to the output terminal, summed as length/width. "
                  "Upper bound -- real current spreads over the other branches",
        "by_weight": weights,
        "worst_group_mohm_at_2oz": max(worst) if worst else None,
        "meets_design_basis_at_2oz": bool(worst) and max(worst) <= opb.DESIGN_BASIS_OHM * 1e3,
        "what_a_track_would_need": _track_needed(rows, opb.sheet_ohm_square(2 * opb.OZ_M)),
    }


def _track_needed(rows: list[dict], sheet: float) -> dict | None:
    """The width a single track would need to hold the budget.

    ``R = sheet * L / W``, so ``W = sheet * L / R_budget``.  Reported because it
    is the shortest way to say why planes are not optional: on a 100 mm run
    the answer comes back wider than the board.
    """
    lengths = [r[k]["length_mm"] for r in rows for k in ("vout", "pgnd")
               if r[k] is not None]
    if not lengths:
        return None
    longest = max(lengths)
    return {"longest_path_mm": round(longest, 2),
            "required_width_mm": round(sheet * longest / opb.DESIGN_BASIS_OHM, 1),
            "board_width_mm": a5.board_rect()[0]}


# ---------------------------------------------------------------- report
def net_totals(result: router.RouteResult, ids: dict[str, int]) -> list[dict]:
    """Copper length and squares per net, from the segments that were emitted.

    ``squares`` is a *strip* count (``sum(length / width)``), not the resistance
    of a tree: a net with 44 branches is not 44 resistors in series.  The path
    that actually matters is measured in ``path_budget()``.
    """
    name = {i: n for n, i in ids.items()}
    length: dict[int, float] = defaultdict(float)
    squares: dict[int, float] = defaultdict(float)
    for s in result.segments:
        run = math.hypot(s.x1 - s.x0, s.y1 - s.y0)
        length[s.net] += run
        squares[s.net] += run / s.width
    return [{"net": name[n], "net_index": n,
             "length_mm": round(length[n], 2),
             "squares": round(squares[n], 3),
             "vias": sum(1 for v in result.vias if v.net == n)}
            for n in sorted(length, key=lambda n: -length[n])]


MAGNETIC_REFS = frozenset({"T1", "T2", "T3", "T4", "Lr", "CT"})


def provisional_interfaces() -> list[dict]:
    """Refs whose land pattern is an outline, not a terminal drawing.

    Read from the footprint's own ``descr`` rather than from the placement's
    ``evidence`` label: the ELP32 cores are labelled ``generated-json`` there
    while their footprint text still says "Terminal positions PROVISIONAL".
    The label would report the core as settled, and the copper would look like
    it lands on a verified terminal.
    """
    rows = []
    for part in a5.PARTS:
        name = part.footprint.split(":", 1)[-1]
        path = a5.OUT / "dcx.pretty" / f"{name}.kicad_mod"
        if not path.exists():
            continue
        if "PROVISIONAL" in path.read_text(encoding="utf-8"):
            rows.append({"ref": part.ref, "footprint": part.footprint,
                         "why": "footprint descr says PROVISIONAL"})
    return rows


def report(board_text: str, result: router.RouteResult, ids: dict[str, int],
           pads: list[router.Pad], single: list[str],
           pours: dict | None = None) -> dict:
    w, d = a5.board_rect()
    widths, _, _ = route_plan(pads, ids)
    name = {i: n for n, i in ids.items()}
    power_nets = sorted(name[n] for n, width in widths.items() if width == POWER_WIDTH_MM)
    signal_nets = sorted(name[n] for n, width in widths.items() if width == SIGNAL_WIDTH_MM)
    return {
        "status": STATUS,
        "flags": {"routed": not result.unrouted, "poured": False,
                  "fabrication_approved": False, "hardware_built": False},
        "board": {"file": _rel(BOARD), "placement_file": _rel(PLACEMENT),
                  "width_mm": w, "depth_mm": d, "copper_layers": 2,
                  "copper_weight": "UNSELECTED -- resistance is reported at 1/2/4 oz",
                  "board_sha256": _sha(board_text)},
        "route": {
            "nets_routed": len({s.net for s in result.segments}),
            "nets_with_one_pad": single,
            "connections_attempted": result.connections_attempted,
            "connections_made": result.connections_made,
            "unrouted_nets": result.unrouted,
            "failures": [{"net": n, "from": a, "to": b} for n, a, b in result.failures],
            "segments": len(result.segments), "vias": len(result.vias),
            "track_width_mm": {"power": POWER_WIDTH_MM, "signal": SIGNAL_WIDTH_MM},
            "power_nets": power_nets,
            "signal_nets": signal_nets,
            # Derived from ``single`` rather than typed: the list moved three times
            # under package C (gate taps became two-pad nets, then VD*/VG* did, then
            # the crowbar made REG* two-pad nets and put FAULT_IN on it) and a typed
            # explanation kept naming nets that no longer leave the board.
            "width_basis": f"{len(power_nets)} nets at {POWER_WIDTH_MM} mm "
                           f"({', '.join(power_nets)}) because they are the nets the "
                           "0.15 mOhm budget and what_a_track_would_need are measured "
                           f"through; the other {len(signal_nets)} routable nets are "
                           f"{SIGNAL_WIDTH_MM} mm connectivity placeholders -- the status "
                           "line already says the tracks cannot carry their currents, so "
                           "a wider track bought no rating and took a lane every time it "
                           "crossed one. The "
                           f"{len(single)} single-pad nets "
                           f"({', '.join(sorted(single))}) are ends that leave this "
                           "board -- the gate drivers, the CT rectifier, and the "
                           "crowbar's fault input, which comes from the D0 protection "
                           "board -- so no track is owed on them",
            "router": "tools/sr_board_router.py (deterministic grid router, "
                      "0.125 mm pitch, 0.20 mm clearance)",
        },
        "copper": net_totals(result, ids),
        "interfaces": {
            "provisional_land_patterns": provisional_interfaces(),
            "consequence": "the copper terminates on outline pads.  When the vendor "
                           "terminal drawing lands, the magnetic pads move and this "
                           "route must be redone; what is permanent here is the router "
                           "and the measured copper cost, not the track positions.",
        },
        "budget": path_budget(result, pads),
        "pours": pours if pours is not None else {
            "count": 0,
            "why": "kicad-cli was not available, so no zone could be refilled and "
                   "there is no fill to measure",
        },
    }


# ---------------------------------------------------------------- pours
# A track can never carry 100 A: budget.what_a_track_would_need is wider than
# the board.  So the question a pour stage has to answer is the *upper bound* --
# if each copper layer were poured solid over the whole board, what would the
# series path be?  That is a measurement of shape, and it is independent of
# copper weight, so one solve answers "does 1/2/4 oz work?" afterwards.
#
# It is deliberately NOT a layout.  A full-board VOUT pour puts VOUT copper
# under every SR source-strip solder-mask aperture, beside SEC*_A/B pads and
# tracks; kicad-cli reports exactly that as solder_mask_bridge.  The zone is an
# experiment that prices the copper, and the report says so.
POUR_CELL_MM = 0.25        # measurement mesh
POUR_COARSE_MM = 0.35      # second mesh, quotes the discretisation spread
SHEET_MOHM_PER_SQ = {"1oz": 0.6474, "2oz": 0.3237, "4oz": 0.1619}
POUR_PATHS = (
    {"net": "VOUT", "layer": "F.Cu", "refs": ("T1", "T2", "T3", "T4"),
     "sink_ref": "J_OUT", "sink_pin": "1",
     "what": "the four transformer centre taps to the output terminal"},
    {"net": "PGND", "layer": "B.Cu",
     "refs": ("SR1A", "SR1B", "SR2A", "SR2B", "SR3A", "SR3B", "SR4A", "SR4B"),
     "sink_ref": "J_OUT", "sink_pin": "2",
     "what": "the eight SR source pads to the return terminal"},
)


def zone_text(ids: dict[str, int]) -> str:
    """One full-board zone per output net, on opposite layers."""
    w, d = a5.board_rect()
    w, d = w - 0.5, d - 0.5
    out = ""
    for k, spec in enumerate(POUR_PATHS):
        uid = f"{k + 7:08x}-0000-5000-8000-00000000000{k}"
        out += (f'\n\t(zone (net {ids[spec["net"]]}) (net_name "{spec["net"]}") '
                f'(layer "{spec["layer"]}")\n'
                f'\t\t(priority 0) (uuid "{uid}")\n'
                f'\t\t(hatch edge 0.5)\n'
                f'\t\t(connect_pads yes (clearance 0.2))\n'
                f'\t\t(min_thickness 0.25)\n'
                f'\t\t(filled_areas_thickness no)\n'
                f'\t\t(fill yes (thermal_gap 0.5) (thermal_bridge_width 0.5) '
                f'(island_removal_mode 0))\n'
                f'\t\t(polygon (pts (xy 0.5 0.5) (xy {w:.3f} 0.5) '
                f'(xy {w:.3f} {d:.3f}) (xy 0.5 {d:.3f})))\n'
                f'\t)\n')
    return out


def _poured_board(cli: Path) -> tuple[str, dict]:
    """Write the poured variant, refill it, read it back, delete the scratch copy.

    The copy has to sit in ``OUT`` itself: ``fp-lib-table`` points at
    ``${KIPRJMOD}/dcx.pretty``, so a board in a subdirectory loses all 35
    footprints -- and an unresolvable footprint also switches the courtyard
    check off, which is how a "clean" DRC ends up having checked nothing.

    The scratch files are removed on the way out.  Leaving them behind would
    hand the next ``git status`` three untracked files that look like boards.
    """
    text = BOARD.read_text(encoding="utf-8")
    end = text.rstrip().rfind(")")
    if end < 0:
        raise SystemExit("the routed board has no closing parenthesis")
    board = OUT / "_pour_stage.kicad_pcb"
    project = OUT / "_pour_stage.kicad_pro"
    report = OUT / "_pour_stage_drc.json"
    try:
        board.write_text(text[:end] + zone_text(net_table()) + ")\n",
                         encoding="utf-8", newline="\n")
        project.write_text(project_file(), encoding="utf-8", newline="\n")
        drc = _drc(cli, board, report, save=True)
        return board.read_text(encoding="utf-8"), drc
    finally:
        for path in (board, project, report, OUT / "_pour_stage.kicad_prl"):
            path.unlink(missing_ok=True)


def fill_contours(text: str, layer: str) -> list[list[tuple[float, float]]]:
    """Closed contours of every ``(filled_polygon)`` on one layer.

    A repeated first point delimits one contour from the next.  On KiCad 10 that
    never fires -- holes are fractured into the outline itself, so each layer is
    one contour -- but a file that emits an outline plus separate hole subpaths
    is split correctly, and ``raster_fill``'s parity rule handles both.
    """
    out: list[list[tuple[float, float]]] = []
    i = 0
    pattern = re.compile(r'\(filled_polygon\s+\(layer "' + re.escape(layer) + r'"\)')
    while True:
        hit = pattern.search(text, i)
        if hit is None:
            return out
        k = text.find("(pts", hit.start())
        if k < 0:
            return out
        depth, e = 0, k
        while e < len(text):
            depth += {"(": 1, ")": -1}.get(text[e], 0)
            if depth == 0:
                break
            e += 1
        pts = [(float(x), float(y)) for x, y in
               re.findall(r"\(xy ([-\d.]+) ([-\d.]+)\)", text[k:e])]
        cur = [pts[0]]
        for p in pts[1:]:
            cur.append(p)
            if len(cur) > 2 and p == cur[0]:
                out.append(cur)
                cur = [p]
        if len(cur) > 2:
            out.append(cur)
        i = e


def raster_fill(contours: list[list[tuple[float, float]]], cell: float
                ) -> tuple[object, float, float]:
    """Cell-centre fill map, plus the grid's origin.

    KiCad 10 writes a layer's whole fill as one closed polyline: every clearance
    hole is fractured into the outline by a zero-width slit, so ``fill_contours``
    returns a single contour and one ``contains_points`` already excludes the
    holes.  That was checked against the board, not assumed -- every sample point
    inside the fill on F.Cu belonged to VOUT's own copper, and none of the other
    nets' track midpoints landed inside it.

    Parity is still the rule, because it is the one that stays correct if a
    future file writes holes as separate subpaths: matplotlib **unions**
    subpaths there (a point inside a hole comes back True), and an odd/even
    count is what repairs it.  Contours are evaluated inside their own bounding
    box, so a 1 mm hole costs 16 cells and not 300 000.
    """
    import numpy as np                                     # noqa: PLC0415
    from matplotlib.path import Path as MPath              # noqa: PLC0415

    xs = [p[0] for c in contours for p in c]
    ys = [p[1] for c in contours for p in c]
    x0, y0 = min(xs), min(ys)
    nx = int(math.ceil((max(xs) - x0) / cell))
    ny = int(math.ceil((max(ys) - y0) / cell))
    gx, gy = np.meshgrid(x0 + (np.arange(nx) + 0.5) * cell,
                         y0 + (np.arange(ny) + 0.5) * cell)
    pts = np.column_stack([gx.ravel(), gy.ravel()])
    depth = np.zeros(len(pts), np.int16)
    for c in contours:
        a = np.array(c, float)
        lo, hi = a.min(0), a.max(0)
        sel = ((pts[:, 0] >= lo[0]) & (pts[:, 0] <= hi[0])
               & (pts[:, 1] >= lo[1]) & (pts[:, 1] <= hi[1]))
        if not sel.any():
            continue
        codes = ([MPath.MOVETO] + [MPath.LINETO] * (len(c) - 2) + [MPath.CLOSEPOLY])
        depth[sel] += MPath(a, np.array(codes)).contains_points(pts[sel], radius=0)
    return ((depth % 2) == 1).reshape(ny, nx), x0, y0


def _electrode(pad: router.Pad, shape, x0: float, y0: float, cell: float):
    """Cells within one cell-width of the pad's copper.

    Pads are placed on the layer being solved even when the footprint puts them
    on the other one.  That is the optimistic side of an upper-bound study: a
    real connection would pay a via and a track, and those are not modelled.
    """
    import numpy as np                                     # noqa: PLC0415

    out = np.zeros_like(shape)
    ny, nx = shape.shape
    r = max(pad.w, pad.h) / 2 + 0.3
    for j in range(max(0, int((pad.y - r - y0) / cell)),
                   min(ny, int((pad.y + r - y0) / cell) + 1)):
        for i in range(max(0, int((pad.x - r - x0) / cell)),
                       min(nx, int((pad.x + r - x0) / cell) + 1)):
            cx, cy = x0 + (i + 0.5) * cell, y0 + (j + 0.5) * cell
            if router._pad_distance(pad, cx, cy) <= cell:
                out[j, i] = True
    return out


def mesh_squares(mask, source, sink, tol: float = 1e-8,  # noqa: PLR0913
                 maxit: int = 40000) -> dict:
    """Effective sheet resistance in squares between two electrode sets.

    Every in-mask cell is one square and every 4-neighbour edge one unit of
    conductance; sink held at 1 V, source at 0 V, Jacobi-preconditioned CG on
    the 5-point Laplacian.  Nothing leaves the mask (Neumann at the pour edge),
    which is what copper with no route off it does.  ``R = 1 / I_total``.

    Verified on fixtures before it was pointed at a board: a 20 x 200 strip
    gives 9.95 squares (10 expected) and a 40 x 40 plate 0.975 (1 expected).
    """
    import numpy as np                                     # noqa: PLC0415

    dirs = ((1, 0), (-1, 0), (0, 1), (0, -1))
    h, w = mask.shape
    m = mask.astype(float)
    pad = np.zeros((h + 2, w + 2), float)
    pad[1:-1, 1:-1] = m
    k = np.zeros_like(m)
    for dy, dx in dirs:
        k += pad[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]
    free = mask & ~source & ~sink
    fixed = np.where(sink, 1.0, 0.0)
    fp = np.zeros((h + 2, w + 2), float)
    fp[1:-1, 1:-1] = fixed
    b = np.zeros_like(k)
    for dy, dx in dirs:
        b += fp[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]
    kf = np.where(free, k, 1.0)
    bf = np.where(free, b, 0.0)

    def matvec(v):
        q = np.zeros((h + 2, w + 2), float)
        q[1:-1, 1:-1] = v
        out = kf * v
        for dy, dx in dirs:
            out -= q[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]
        out[~free] = 0.0
        return out

    x = np.zeros_like(k)
    r = bf - matvec(x)
    p = r.copy()
    rs = (r * r).sum()
    rs0 = rs
    it = 0
    for it in range(1, maxit):
        ap = matvec(p)
        alpha = rs / (p * ap).sum()
        x += alpha * p
        r -= alpha * ap
        rs_new = (r * r).sum()
        if rs_new < tol * tol * rs0:
            break
        p = r + (rs_new / rs) * p
        rs = rs_new
    v = np.where(sink, 1.0, np.where(source, 0.0, x))
    vp = np.zeros((h + 2, w + 2), float)
    vp[1:-1, 1:-1] = v
    pad_m = np.zeros((h + 2, w + 2), float)
    pad_m[1:-1, 1:-1] = m
    i_total = 0.0
    for dy, dx in dirs:
        # Only edges that stay in the copper carry current.  A sink cell sits on
        # the pour edge, and (1 - 0) across the edge would otherwise invent an
        # ampere per open side -- that alone turns a plate's 1 square into 0.02.
        linked = pad_m[1 + dy:1 + dy + h, 1 + dx:1 + dx + w] > 0.5
        i_total += np.where(sink & linked,
                            1.0 - vp[1 + dy:1 + dy + h, 1 + dx:1 + dx + w], 0.0).sum()
    # float(), not np.float64: round() keeps the numpy type, and a np.bool_ from
    # comparing it is not JSON-serialisable.
    return {"squares": float(1.0 / i_total) if i_total else None,
            "iterations": int(it), "converged": bool(it < maxit - 1)}


def pour_path(filled: str, pads: list[router.Pad], ids: dict[str, int],
              spec: dict, cell: float) -> dict:
    contours = fill_contours(filled, spec["layer"])
    if not contours:
        raise SystemExit(f"no filled polygon on {spec['layer']} -- the refill "
                         "produced nothing; check fp-lib-table and the zone text")
    shape, x0, y0 = raster_fill(contours, cell)
    netpads = [p for p in pads if p.net == ids[spec["net"]]]
    sink_pads = [p for p in netpads
                 if p.ref == spec["sink_ref"] and p.number == spec["sink_pin"]]
    source_pads = [p for p in netpads if p.ref in spec["refs"]]
    if not sink_pads or not source_pads:
        raise SystemExit(f"{spec['net']}: the pour stage found no terminals "
                         f"({len(source_pads)} sources, {len(sink_pads)} sinks)")
    source = shape & False
    sink = shape & False
    missing = []
    for p in source_pads + sink_pads:
        # The electrode is the pad's halo *clipped to the fill*.  Requiring
        # every electrode cell to be copper would fail by construction: a pad's
        # own copper is not part of the zone fill, and the zone reaches it
        # through thermal spokes.  Contact is the claim worth testing.
        e = _electrode(p, shape, x0, y0, cell) & shape
        if not e.any():
            missing.append(f"{p.ref}.{p.number}")
        if p in source_pads:
            source |= e
        else:
            sink |= e
    if not source.any() or not sink.any():
        raise SystemExit(f"{spec['net']}: the fill touches "
                         f"{'no source' if not source.any() else 'no sink'} pad -- "
                         "the pour is not connected to the terminal it is measured on")
    solved = mesh_squares(shape | source | sink, source, sink)
    if solved["squares"] is None:
        # Touching the fill is not the same as conducting through it: heat
        # spokes and clearance channels can leave a pad on an isolated sliver.
        raise SystemExit(f"{spec['net']}: no current flows between the terminals "
                         "through the fill -- every pad touches copper, but not "
                         "the same copper")
    return {
        "net": spec["net"], "layer": spec["layer"], "what": spec["what"],
        "sources": sorted({p.ref for p in source_pads}),
        "sink": f"{spec['sink_ref']}.{spec['sink_pin']}",
        "fill_fraction": round(float(shape.mean()), 3),
        "squares": round(solved["squares"], 4),
        "converged": solved["converged"],
        "every_terminal_lands_in_the_fill": not missing,
        "terminals_without_contact": missing,
    }


def pour_study(cli: Path) -> dict:
    filled, drc = _poured_board(cli)
    ids = net_table()
    pads = pads_of(BOARD.read_text(encoding="utf-8"), ids)
    paths = []
    for spec in POUR_PATHS:
        fine = pour_path(filled, pads, ids, spec, POUR_CELL_MM)
        coarse = pour_path(filled, pads, ids, spec, POUR_COARSE_MM)
        fine["squares_coarse"] = coarse["squares"]
        fine["spread_pct"] = round(
            abs(fine["squares"] - coarse["squares"]) / fine["squares"] * 100, 2)
        fine["mohm"] = {w: round(s * fine["squares"], 4)
                        for w, s in SHEET_MOHM_PER_SQ.items()}
        fine["every_terminal_lands_in_the_fill"] &= coarse["every_terminal_lands_in_the_fill"]
        paths.append(fine)
    series = {w: round(sum(p["mohm"][w] for p in paths), 4) for w in SHEET_MOHM_PER_SQ}
    kinds = drc_summary(drc)
    return {
        "count": len(paths),
        "method": "rasterise the refilled zone, one unit of conductance per cell "
                  "edge, sink at 1 V and sources at 0 V, R = 1/I_total (squares); "
                  "multiply by the sheet resistance afterwards",
        "cell_mm": POUR_CELL_MM, "second_cell_mm": POUR_COARSE_MM,
        "sheets_mohm_per_square": SHEET_MOHM_PER_SQ,
        "paths": paths,
        "series_mohm": series,
        "meets_the_0p15_mohm_basis": {w: v <= 0.15 for w, v in series.items()},
        "verdict": "even poured solid on both layers this board is "
                   f"{series['4oz'] / 0.15:.1f}x the 0.15 mOhm basis at 4 oz and "
                   f"{series['2oz'] / 0.15:.1f}x at 2 oz, so the plane is not the "
                   "output path -- the busbar is, and the pour only has to bridge "
                   "each group to the busbar land",
        "not_a_layout": "the full-board pour exposes VOUT copper under every SR "
                        "solder-mask aperture, which kicad-cli reports as "
                        "solder_mask_bridge.  This measures what copper area can "
                        "buy; it is not a design and its DRC is not a gate.",
        "drc": kinds,
    }


def _rel(path: Path) -> str:
    return str(path.relative_to(a5.ROOT)).replace("\\", "/")


def _sha(text: str) -> str:
    import hashlib   # noqa: PLC0415  (one use, keeps the import list plain)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _drc(cli: Path, board: Path, out: Path, save: bool = False) -> dict:
    """Run kicad-cli and refuse to read a report it did not write.

    ``kicad-cli`` exits 0 even when it reports violations, so the exit code
    cannot be the gate; a missing or stale report is.  Unlinking first is the
    same lesson the SR board learned: a ``check=False`` run that crashed used
    to leave yesterday's clean report to be read as today's result.

    ``save`` writes the refilled zones back into the board.  It is only ever
    used on the throwaway copy under ``POUR_DIR``: the committed board carries
    no zones, and refilling it in place would rewrite the whole file.
    """
    if out.exists():
        out.unlink()
    proc = subprocess.run([str(cli), "pcb", "drc", "--format", "json", "--severity-all",
                           "--refill-zones", *(["--save-board"] if save else []),
                           "-o", str(out), str(board)],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=False)
    if proc.returncode != 0 or not out.exists():
        raise SystemExit(f"kicad-cli pcb drc failed (exit {proc.returncode}): "
                         f"{proc.stderr.strip() or proc.stdout.strip()}")
    return json.loads(out.read_text(encoding="utf-8"))


def drc_summary(data: dict) -> dict:
    import make_sr_fault_board_pcb as srpcb   # noqa: PLC0415  (lazy: import cycle)
    kinds = srpcb.classify_violations(data.get("violations", []))
    return {
        "version": data.get("kicad_version"),
        "violations": len(data.get("violations", [])),
        "counts": {k: len(v) for k, v in kinds.items()},
        "unconnected_items": len(data.get("unconnected_items", [])),
        "schematic_parity": len(data.get("schematic_parity", [])),
        "types": sorted({v.get("type") for v in data.get("violations", [])}),
        "ignored_checks": data.get("ignored_checks", []),
    }


# ---------------------------------------------------------------- write / check
def write(check_drc: bool = True) -> dict:
    text = placement_text()
    result, ids, pads, single = route_board(text)
    board = board_file(text, result, ids)
    OUT.mkdir(parents=True, exist_ok=True)
    BOARD.write_text(board, encoding="utf-8", newline="\n")
    PROJECT.write_text(project_file(), encoding="utf-8", newline="\n")
    cli = a5.find_kicad_cli()
    pours = pour_study(cli) if check_drc and cli is not None else None
    data = report(board, result, ids, pads, single, pours)
    if check_drc and cli is not None:
        data["drc"] = drc_summary(_drc(cli, BOARD, DRC))
        data["drc_reproduced"] = True
    else:
        data["drc"] = {"report": "not run",
                       "why": "kicad-cli not found; routing and the copper budget "
                              "do not need it"}
        data["drc_reproduced"] = False
    _set_checks(data)
    REPORT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8", newline="\n")
    return data


def _set_checks(data: dict) -> None:
    """Invariants only.  The ampacity verdict is a physical result, not a gate.

    Putting "the power path meets 0.15 mOhm" into ``checks`` would be the exact
    mistake CLAUDE.md's ledger section warns about: it invites the next person
    to loosen the target until the test goes green.
    """
    route, drc = data["route"], data.get("drc", {})
    counts = drc.get("counts", {})
    pours = data.get("pours", {})
    paths = pours.get("paths", [])
    data["checks"] = {
        "every_routable_net_is_connected":
            route["connections_made"] == route["connections_attempted"],
        "no_unrouted_nets": route["unrouted_nets"] == [],
        "the_board_carries_copper": route["segments"] > 0,
        "drc_was_reproduced_here": data["drc_reproduced"],
        "drc_reports_no_unconnected_items": drc.get("unconnected_items") == 0,
        "drc_placement_clean": counts.get("placement") == 0,
        # Deleting the word PROVISIONAL from a footprint descr must not make the
        # board look like it lands on verified terminals; that is how the
        # magnetics would quietly stop being an open item.
        "every_magnetic_is_reported_as_a_provisional_interface":
            MAGNETIC_REFS <= {row["ref"] for row in
                              data["interfaces"]["provisional_land_patterns"]},
        "the_power_path_verdict_is_reported_as_a_result":
            "meets_design_basis_at_2oz" in data["budget"],
        # Structure only.  "The pour meets 0.15 mOhm" is a physical result and
        # stays in results -- it does not, and at 4 oz it is still 5x over.
        "the_pour_was_measured_here": pours.get("count") == len(POUR_PATHS),
        "every_poured_terminal_lands_in_the_fill":
            bool(paths) and all(p["every_terminal_lands_in_the_fill"] for p in paths),
        # Two meshes is the cheapest honest error bar: a single cell size cannot
        # tell a converged number from a grid artefact.
        "the_pour_mesh_agrees_at_two_cell_sizes":
            bool(paths) and all(p["spread_pct"] <= 2.0 for p in paths),
        "the_pour_verdict_is_reported_as_a_result":
            "meets_the_0p15_mohm_basis" in pours,
    }
    data["results"] = {
        "power_path_meets_the_0p15_mohm_basis": data["budget"]["meets_design_basis_at_2oz"],
        "worst_group_mohm_at_2oz": data["budget"]["worst_group_mohm_at_2oz"],
        "pour_series_mohm": pours.get("series_mohm"),
        "pour_meets_the_0p15_mohm_basis_at_2oz":
            pours.get("meets_the_0p15_mohm_basis", {}).get("2oz"),
    }


def check() -> None:
    """Both generated files still say what re-routing says today.

    Two independent staleness signals, because they fail differently: the board
    bytes catch a placement change that was never re-routed (or a hand-edit of
    the copper), while the report's ``board_sha256`` catches a board that was
    regenerated without the numbers being re-derived.  Without the second, a
    hand-edited budget in the JSON would survive every ``--check``.
    """
    text = placement_text()
    result, ids, pads, single = route_board(text)
    board = board_file(text, result, ids)
    # Autocrlf rewrites the working copy on checkout while the generator always
    # writes LF; normalise before comparing, the same way the A5 placement test
    # and current_manifest.sha256() do.
    committed = (BOARD.read_bytes().decode("utf-8").replace("\r\n", "\n")
                 if BOARD.exists() else "")
    same = committed == board
    print(f"routed board: {len(result.segments)} segments, {len(result.vias)} vias, "
          f"{result.connections_made}/{result.connections_attempted} connections, "
          f"{len(single)} single-pad nets")
    print(f"committed board {'matches' if same else 'DIFFERS FROM'} this placement")
    if not same:
        raise SystemExit("power_stage_routed.kicad_pcb is stale -- "
                         "run tools/main_board_power_copper.py --json")
    if not REPORT.exists():
        raise SystemExit("routed_copper.json is missing -- run with --json")
    data = json.loads(REPORT.read_text(encoding="utf-8"))
    budget = data["budget"]
    if data["board"].get("board_sha256") != _sha(board):
        raise SystemExit("routed_copper.json was not derived from the committed board -- "
                         "run tools/main_board_power_copper.py --json")
    fresh = path_budget(result, pads)
    if fresh["worst_group_mohm_at_2oz"] != budget["worst_group_mohm_at_2oz"]:
        raise SystemExit(f"routed_copper.json reports {budget['worst_group_mohm_at_2oz']} mOhm "
                         f"but the routed copper gives {fresh['worst_group_mohm_at_2oz']} mOhm -- "
                         "run tools/main_board_power_copper.py --json")
    print(f"worst output path at 2 oz: {budget['worst_group_mohm_at_2oz']} mOhm against a "
          f"{budget['design_basis_mohm']} mOhm basis "
          f"({'meets' if budget['meets_design_basis_at_2oz'] else 'NOT met'})")
    cli = a5.find_kicad_cli()
    if cli is None:
        print("kicad-cli not found: the pour study was not reproduced "
              "(refilling a zone needs it; the route does not)")
        return
    print("re-pouring and solving the copper mesh, this takes about 2 min ...")
    _compare_pours(data.get("pours", {}), pour_study(cli))


def _compare_pours(printed: dict, fresh: dict) -> None:
    """The committed pour numbers are re-derived here, not trusted.

    They are a measurement of the same copper the board bytes were just checked
    against, so a hand-edited series resistance would otherwise survive every
    ``--check`` -- the same hole the budget comparison closes.
    """
    old, new = printed.get("series_mohm") or {}, fresh["series_mohm"]
    if not old:
        # Written by --no-drc, or by a machine without kicad-cli.  It is not
        # wrong, it is incomplete, and the person reading --check needs to know
        # which: nothing was measured, so nothing can be compared.
        raise SystemExit("routed_copper.json has no pour study (it was written "
                         "without kicad-cli or with --no-drc) -- run "
                         "tools/main_board_power_copper.py --json here")
    for weight, value in new.items():
        if weight not in old or abs(old[weight] - value) > 1e-6 * max(value, 1e-9):
            raise SystemExit(
                f"routed_copper.json reports {old.get(weight)} mOhm of poured path at "
                f"{weight}, but re-pouring and solving gives {value} mOhm -- "
                "run tools/main_board_power_copper.py --json")
    for a, b in zip(printed.get("paths", []), fresh["paths"]):
        if abs((a.get("squares") or 0) - b["squares"]) > 1e-6 * b["squares"]:
            raise SystemExit(
                f"{a.get('net')} pour: report says {a.get('squares')} squares, "
                f"the refilled copper solves to {b['squares']}")
    print("poured series path: " + ", ".join(f"{v} mOhm at {k}"
                                              for k, v in new.items())
          + f" against a 0.15 mOhm basis "
            f"({'meets' if fresh['meets_the_0p15_mohm_basis']['4oz'] else 'NOT met even at 4 oz'})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", type=Path, help="write the routed board and this report")
    parser.add_argument("--check", action="store_true",
                        help="re-route from the placement and compare bytes")
    parser.add_argument("--no-drc", action="store_true",
                        help="skip kicad-cli (routing and the budget do not need it)")
    args = parser.parse_args(argv)
    if args.check:
        check()
        return 0
    if args.json:
        data = write(check_drc=not args.no_drc)
        route = data["route"]
        print(f"routed {route['nets_routed']} nets, "
              f"{route['connections_made']}/{route['connections_attempted']} connections, "
              f"{route['segments']} segments, {route['vias']} vias")
        print(f"worst output path at 2 oz: {data['budget']['worst_group_mohm_at_2oz']} mOhm "
              f"against {data['budget']['design_basis_mohm']} mOhm")
        print(data["status"])
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

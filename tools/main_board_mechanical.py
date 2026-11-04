"""A5: 1:1 mechanical placement of the main power stage, now carrying nets.

What this is
------------
A single table of parts with real outlines, laid out on a KiCad board that
opens in the editor and renders in 3D.  Two questions live here:

* **does it all physically fit, and where does the height problem land** -- the
  outlines, the clearances and the A6 section;
* **where does the current actually have to go** -- every pad now carries the
  net `pin_footprint_review.csv` assigns it, so the editor draws the real
  ratsnest and per-net straight-line lengths can be compared across the four
  identical groups (ELE-04).

The nets are *read*, not invented: ``hardware/dcx_main/pin_footprint_review.csv``
is the table that already arbitrates the logical netlist against a footprint.
Where that table has no row for a placed part, the pad stays netless and the
report says which one and why -- the fifteen bulk capacitors are the clear case,
because the schematic models the whole bank as a single lumped ``Cout``.

What it is not
--------------
Not a routed board, not a DRC-clean design, not a manufacturing output.  Nets
make the connectivity visible; they do not route it, and every ratsnest line is
still a missing track.  `kicad-cli pcb drc` is still run, but only for the
things a placement can be wrong about: courtyards that touch, pads that collide,
and footprints from a library the project cannot see (a footprint KiCad cannot
resolve is a black box, so its courtyard is not checked either -- the same trap
already documented for the schematic side in ``make_control_board.py``).

Where each number comes from
----------------------------
Every outline carries an evidence class, and the report prints it:

``generated-json``  read from a tool's JSON in this repo (ELP32 core, Cout
                    height, busbar section).
``digitised-datasheet``  a land pattern measured off the datasheet's board-pads
                    figure (the SR FET).  Better than a borrowed library part,
                    still not vendor CAD and not checked against IPC-7351.
``kicad-library``   the stock footprint's own dimensions.  No part uses this
                    class any more; the machinery is kept because the vendored
                    library and its PROVENANCE guard are still exercised.
``datasheet``       a package size the BOM marks VERIFIED.  Body only: the
                    part's pads on this board are still placeholders, which is
                    why the report lists it under ``land_pattern_provisional``.
``PROVISIONAL``     nobody has selected the part.  CT, Cr, J_IN and the
                    control area are placeholders with a stated size, and the
                    report lists them so a reader cannot mistake the drawing
                    for a BOM.

The height finding
------------------
Five ELP32 cores (T1-T4 and Lr -- Lr is on the *same* core, per
``lr_design.json``) are 9.8 mm worst case.  ``magnetics_design.json`` reports
the flat stack at 9.94 mm: it clears 10 mm by 60 um, which is smaller than the
glue, the label and the core's own flatness.  Add the 0.5 mm clamp and the same
stack is 10.44 mm, over.  So the Z answer is not "it fits" -- it is "it fits
flat only by coincidence, and the moment the cores are retained it does not fit
at all".

Usage:
    python tools/main_board_mechanical.py
    python tools/main_board_mechanical.py --check    # + kicad-cli DRC, fails on errors
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "hardware" / "dcx_mech"
DESIGN = ROOT / "design" / "v3"
# Official footprints this board borrows are vendored; see
# hardware/stock_footprints/PROVENANCE.md.  Nothing here may name a user
# directory: the generator has to reproduce the committed board on any machine
# and on a CI runner that has no KiCad at all (Issue #11).
STOCK = ROOT / "hardware" / "stock_footprints"
NS = uuid.UUID("a5b6c7d8-1e2f-4a3b-9c4d-5e6f7a8b9c0d")

HEIGHT_LIMIT_MM = 10.0
XFMR_FP = "dcx:ELP32_XFMR"
LR_FP = "dcx:ELP32_LR"
CORE_FOOTPRINTS = (XFMR_FP, LR_FP)
EDGE_MARGIN_MM = 5.0
BOARD_T = 1.6
REVIEW = ROOT / "hardware" / "dcx_main" / "pin_footprint_review.csv"


def uid(*parts: str) -> str:
    return str(uuid.uuid5(NS, "/".join(parts)))


def _load(rel: str) -> dict:
    return json.loads((DESIGN / rel).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- netlist
# The arbitration table: one row per (ref, logical pin, footprint pad, net).  It
# already exists for the schematic side, so the board reads it instead of
# re-deriving connectivity from the deck -- two derivations would eventually
# disagree and there would be no way to say which one the board believed.
BANK_PREFIX = "Cout"

# Row 3's two FETs per transformer start here; SR{i}A sits at x0 and SR{i}B at
# x0 + SR_PAIR_MM, so each group's centre is x0 + SR_PAIR_MM / 2.  The busbar
# reads the same tuple: it used to sit at x = 100, which was centre-ish for an
# 80 mm bar but put group 1 41 mm outside it and group 3/4 underneath.  Placing
# it on the centre of the row it serves is what makes the two outer groups pay
# the same, and it costs no copper.
SR_X0 = (14.0, 52.0, 90.0, 128.0)
SR_PAIR_MM = 10.0
SR_ROW_Y = 82.0


def review_rows() -> list[dict]:
    with REVIEW.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def pad_nets() -> dict[str, dict[str, str]]:
    """``ref -> pad -> net`` for every pin the review table has mapped.

    An empty net cell means the table mapped the pad but not to a net (U2.2);
    it is dropped rather than turned into a net called ``""``, and the report's
    ``pad_without_a_net`` list keeps it visible.
    """
    out: dict[str, dict[str, str]] = {}
    for row in review_rows():
        if row["net"].strip():
            out.setdefault(row["ref"], {})[row["pad"]] = row["net"].strip()
    return out


def bank_nets() -> dict[str, str]:
    """The bulk bank's pad->net, taken from the *lumped* ``Cout`` symbol.

    ``cout_bank.json`` asks for fifteen physical capacitors while the schematic
    models all of them as one ``Cout``.  Fifteen refs therefore have no row of
    their own; borrowing the lumped symbol's two nets is the only reading that
    does not invent connectivity, and the report says so.
    """
    return pad_nets()["Cout"]


def part_nets(part: "Part") -> dict[str, str]:
    """The nets for one placed part: its own rows, or the bank's, or none.

    Filtered to the pads this footprint actually carries.  Without that filter a
    padless outline would still be counted as a connection -- the control area
    ``U2`` stands for a whole section, and its eleven netlist pins would appear
    on the board as if they had somewhere to land."""
    table = pad_nets()
    if part.ref in table:
        got = table[part.ref]
    elif part.ref.startswith(BANK_PREFIX):
        got = bank_nets()
    else:
        return {}
    local = _pad_positions(part.footprint)
    return {pad: net for pad, net in got.items() if pad in local}


def placed_nets() -> dict[str, list[str]]:
    """``net -> refs`` across the whole board, for the report and the ratsnest."""
    out: dict[str, list[str]] = {}
    for part in PARTS:
        for pad, net in part_nets(part).items():
            out.setdefault(net, []).append(f"{part.ref}.{pad}")
    return {net: sorted(members) for net, members in sorted(out.items())}


# ---------------------------------------------------------------- part table
@dataclass(frozen=True)
class Part:
    ref: str
    value: str
    w_mm: float          # x extent
    d_mm: float          # y extent
    h_mm_worst: float    # z, worst case (not nominal)
    x: float             # centre
    y: float
    evidence: str
    footprint: str = ""   # "lib:name"; empty means generate one
    rot: float = 0.0
    note: str = ""


def _core() -> dict:
    return _load("magnetics/magnetics_design.json")["core"]


def _cout() -> dict:
    return _load("bom/cout_bank.json")["banks"][0]


def _bar() -> dict:
    return _load("bom/connector_budget.json")["output"]["bar"]


def _sr_row_centre() -> float:
    """Mean centre of the four SR groups.

    Derived from ``SR_X0`` rather than written as 76.0 so that moving a group
    moves the busbar with it -- the two are one decision, and a literal here
    would silently reintroduce the offset this function exists to remove.
    """
    return sum(x0 + SR_PAIR_MM / 2.0 for x0 in SR_X0) / len(SR_X0)


def parts() -> tuple[Part, ...]:
    """The placement table.  Order is the reading order of the board, top to
    bottom, and every coordinate is the part *centre* in mm from the top-left."""
    core = _core()
    cout = _cout()
    bar = _bar()
    mag_w = core["outer_length_m"] * 1e3
    mag_d = core["core_depth_m"] * 1e3
    mag_h = core["height_max_m"] * 1e3
    COUT_FP = "dcx:Placeholder_Cout"
    tds = "dcx:BSC010N04LS6"

    out: list[Part] = []
    # Row 1 -- the four transformers, one per 3:1:1 set, evenly spaced so the
    # four secondary loops are identical.  Symmetry is a current-sharing
    # argument, not decoration.
    for i, x in enumerate((20.0, 58.0, 96.0, 134.0), start=1):
        out.append(Part(f"T{i}", "3:1:1 ELP32", mag_w, mag_d, mag_h, x, 20.0,
                        "generated-json", XFMR_FP))
    # Row 2 -- primary side, left to right in power-flow order.
    out.append(Part("Lr", "1.0 uH", mag_w, mag_d, mag_h, 20.0, 52.0,
                    "generated-json", LR_FP,
                    note="same ELP32 core as T1-T4, so it shares the pocket"))
    # Q5A package table (datasheet p9): D1 max 5.00, E max 6.10, A max 1.10.
    # Using the maximums, not the 5x6x1 nominal the BOM calls it -- that is the
    # same nominal/maximum trap the magnetics height stack already avoids.
    for ref, x in (("QH", 48.0), ("QL", 57.0)):
        out.append(Part(ref, "CSD19531Q5A", 5.00, 6.10, 1.10, x, 50.0, "datasheet",
                        "dcx:Placeholder_SON_5x6",
                        note="Q5A dims D1/E/A max from datasheet p9; land pattern still "
                             "provisional (the recommended-pad figure is not in the text)"))
    out.append(Part("Cr", "0.62 uF", 18.0, 6.0, 6.0, 72.0, 52.0, "PROVISIONAL",
                    "dcx:Placeholder_18x6", note="no part selected; 18x6x6 film assumed"))
    out.append(Part("CT", "100:1", 20.0, 15.0, 8.0, 92.0, 52.0, "PROVISIONAL",
                    "dcx:Placeholder_20x15",
                    note="no part selected; 20x15x8 assumed, and 8 mm is a ceiling, "
                         "not a guess -- a taller CT does not fit the 10 mm stack"))
    out.append(Part("J_IN", "48 V input", 10.0, 10.0, 10.0, 112.0, 52.0, "PROVISIONAL",
                    "dcx:Placeholder_10x10",
                    note="2-pin 5.08 mm terminal implied by the BOM; body assumed"))
    out.append(Part("U2", "control area", 12.0, 12.0, 3.0, 132.0, 52.0, "PROVISIONAL",
                    "dcx:Placeholder_12x12",
                    note="UCC25600 + UCC27282 + passives grouped; no layout done"))
    # Row 3 -- the eight SR FETs, two per transformer, directly under their own
    # secondary.  Each pair spans one transformer's width so the secondary loop
    # stays local.
    for i, x0 in enumerate(SR_X0, start=1):
        out.append(Part(f"SR{i}A", "BSC010N04LS6", 7.36, 5.64, 1.0, x0, SR_ROW_Y,
                        "digitised-datasheet", tds,
                        note="land pattern digitised from the BSC010N04LS6 datasheet "
                             "Fig. 2 (design/v3/pcb/bsc010n04ls6_land.json); drain 5-8 "
                             "on a common base.  Not vendor CAD, not IPC-7351 checked"))
        out.append(Part(f"SR{i}B", "BSC010N04LS6", 7.36, 5.64, 1.0, x0 + SR_PAIR_MM,
                        SR_ROW_Y, "digitised-datasheet", tds,
                        note=f"same land pattern as SR{i}A"))
    # Row 4 -- the output bank, one row between the SRs and the busbar.  The
    # refs are Cout1..Cout15, *not* C100..: the schematic already spends
    # C101-C112 on the twelve IC decoupling capacitors, so reusing those names
    # here would attach a 470 uF bulk part to a 0603 position the moment anyone
    # cross-referenced the board against the BOM.
    for i in range(cout["n"]):
        out.append(Part(f"{BANK_PREFIX}{i + 1}", "470 uF 2.5 V", 7.3, 4.3,
                        cout["height_mm"], 14.0 + 8.2 * i, 98.0, "generated-json",
                        COUT_FP,
                        note="height from cout_bank.json; case size assumed; "
                             "the schematic models this whole bank as one lumped Cout"))
    # Row 5 -- the output busbar, last so the 100 A leaves at the board edge.
    # Centred on the SR row it collects from: `output_path_budget.py` measures
    # each group's sideways run to the nearest bar edge, so the bar's x is a
    # design parameter, not a leftover.  At x = 100 group 1 had to travel 41 mm
    # (3.67 squares, 1.19 mohm) while groups 3 and 4 sat underneath it.
    out.append(Part("J_OUT", "20x2 mm bar", bar["length_mm"], bar["width_mm"],
                    bar["thickness_mm"], _sr_row_centre(), 116.0, "generated-json",
                    "dcx:Busbar_20x2",
                    note="contact resistance UNVERIFIED; four-wire at first article"))
    return tuple(out)


PARTS = parts()


# ---------------------------------------------------------------- geometry
def bbox(part: Part) -> tuple[float, float, float, float]:
    """(x0, y0, x1, y1) of the part's own outline.  Only 0 deg and 90 deg
    rotations occur in this table, so the extent swap is explicit rather than a
    general transform -- if a rotation appears that is not one of those two the
    result would be silently wrong, so it raises."""
    w, d = part.w_mm, part.d_mm
    turns = round(part.rot / 90.0) % 4
    if abs(part.rot - turns * 90.0) > 1e-9:
        raise ValueError(f"{part.ref}: rotation {part.rot} is not a multiple of 90")
    if turns % 2:
        w, d = d, w
    return (part.x - w / 2, part.y - d / 2, part.x + w / 2, part.y + d / 2)


def overlaps(prts: tuple[Part, ...] | list[Part]) -> list[tuple[str, str, float]]:
    """Every pair whose outlines share positive area.  Touching exactly is not
    an overlap -- two parts may legitimately butt together."""
    found = []
    for i, a in enumerate(prts):
        ax0, ay0, ax1, ay1 = bbox(a)
        for b in prts[i + 1:]:
            bx0, by0, bx1, by1 = bbox(b)
            dx = min(ax1, bx1) - max(ax0, bx0)
            dy = min(ay1, by1) - max(ay0, by0)
            if dx > 1e-9 and dy > 1e-9:
                found.append((a.ref, b.ref, dx * dy))
    return found


def min_gap_mm(prts: tuple[Part, ...] | list[Part] = PARTS) -> tuple[float, str, str]:
    """Smallest edge-to-edge distance in either axis, and the pair that owns it.
    Reported because 'nothing overlaps' is satisfied by 1 um of clearance too."""
    best, who = float("inf"), ("", "")
    for i, a in enumerate(prts):
        ax0, ay0, ax1, ay1 = bbox(a)
        for b in prts[i + 1:]:
            bx0, by0, bx1, by1 = bbox(b)
            gx = max(bx0 - ax1, ax0 - bx1)
            gy = max(by0 - ay1, ay0 - by1)
            gap = max(gx, gy)
            if gap < best:
                best, who = gap, (a.ref, b.ref)
    return best, who[0], who[1]


def board_rect(prts: tuple[Part, ...] | list[Part] = PARTS) -> tuple[float, float]:
    """Board size in mm, rounded up to 0.5 mm so the Edge.Cuts is a round number."""
    x1 = max(bbox(p)[2] for p in prts)
    y1 = max(bbox(p)[3] for p in prts)
    return _ceil_half(x1 + EDGE_MARGIN_MM), _ceil_half(y1 + EDGE_MARGIN_MM)


def _ceil_half(v: float) -> float:
    return round(-(-v // 0.5) * 0.5, 3)


# ---------------------------------------------------------------- report
def _bsc_source() -> str:
    """The SR FET land pattern, built by the module that digitised it.

    Imported lazily because ``make_sr_fault_board_pcb`` imports *this* module
    for ``find_kicad_cli()``; a top-level import would close the cycle.  The
    footprint is generated from ``design/v3/pcb/bsc010n04ls6_land.json``, whose
    own ``checks`` must all pass or that builder exits -- so this board cannot
    silently inherit a land pattern the measurement has already rejected.
    """
    import make_sr_fault_board_pcb as srpcb
    return srpcb.bsc_source()


def _footprint_text(lib_id: str) -> str:
    name = lib_id.split(":", 1)[1]
    libs = footprint_library()
    return libs.get(f"{name}.kicad_mod") or _stock_footprint(lib_id)


def _pad_blocks(lib_id: str) -> list[str]:
    """Every numbered pad block's name, in file order, duplicates kept.

    Distinct from ``_pad_positions``: the vendored TDSON-8 numbers its five
    drain pads all ``"5"``, so the *name* count is 5 while the *copper* count is
    9.  A report that counted names would understate how much copper a net
    actually lands on, and ``_inject_pad_nets`` -- which walks blocks -- would
    agree with the wrong number.
    """
    return [m.group(1) for m in
            re.finditer(r'\(pad "([^"]*)"', _footprint_text(lib_id)) if m.group(1)]


def _pad_positions(lib_id: str) -> dict[str, tuple[float, float]]:
    """Pad name -> (x, y) in the footprint's own frame, read back out of the
    footprint text.  Reading it back rather than restating the table means the
    distances below cannot drift from the pads the board actually carries."""
    text = _footprint_text(lib_id)
    out: dict[str, tuple[float, float]] = {}
    for match in re.finditer(r'\(pad "([^"]*)"[^(]*\(at (-?[\d.]+) (-?[\d.]+)', text):
        name, px, py = match.group(1), float(match.group(2)), float(match.group(3))
        if name:
            out.setdefault(name, (px, py))
    return out


def _mst_mm(points: list[tuple[float, float]]) -> float:
    """Straight-line minimum spanning tree length over pad centres.

    A lower bound on the copper, not a route: it ignores obstacle detours, layer
    changes and the fact that a 100 A path is a plane.  Useful for comparing the
    four identical groups against each other, which is why it is here.
    """
    if len(points) < 2:
        return 0.0
    left, total = list(points[1:]), 0.0
    tree = [points[0]]
    while left:
        best = None
        for a in tree:
            for b in left:
                dist = ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
                if best is None or dist < best[0]:
                    best = (dist, b)
        total += best[0]
        tree.append(best[1])
        left.remove(best[1])
    return total


def _padless_reason(part: "Part", pad: str) -> str:
    """Why a netlisted pin has no pad here -- the two causes are not the same.

    A repeated pad name is a gap in the vendored land pattern that a
    part-specific footprint would close; a padless outline is a placeholder
    that was never meant to carry pins.  Folding them into one list would let
    a real land-pattern defect look like a deliberate placeholder.
    """
    blocks = _pad_blocks(part.footprint)
    if not blocks:
        return ("the outline stands for a whole functional block and carries no "
                "pads at all, so no pin of it has a position yet")
    dup = sorted({n for n in blocks if blocks.count(n) > 1})
    if dup:
        return (f"the vendored footprint names pad {', '.join(dup)} more than once, "
                f"so the other pins of that group have no pad of their own")
    return "the footprint has no pad with this name"


def nets_report() -> dict:
    """What the connectivity actually is, and what it does not reach.

    Three lists matter as much as the net count: the parts the review table has
    no row for, the manifest pins with no physical pad, and the pads it mapped
    without naming a net.  Each is a place a reader could otherwise assume the
    ratsnest was complete.
    """
    nets = placed_nets()
    table = pad_nets()
    placed = {p.ref for p in PARTS}
    groups: dict[str, list[tuple[float, float]]] = {}
    landed = 0
    for part in PARTS:
        local = _pad_positions(part.footprint)
        for pad, net in part_nets(part).items():
            if pad not in local:
                continue
            x, y = local[pad]
            groups.setdefault(net, []).append((part.x + x, part.y + y))
            landed += 1
    rows = [
        {"net": net, "pads": len(points),
         "refs": sorted({m.split(".")[0] for m in nets[net]}),
         "straight_line_mst_mm": round(_mst_mm(points), 3)}
        for net, points in groups.items()
    ]
    rows.sort(key=lambda r: (-r["straight_line_mst_mm"], r["net"]))
    # Two different questions, so two different loops.  ``physical`` counts the
    # copper the nets actually land on, which includes the bank parts that have
    # no row of their own.  ``padless`` has to read the *table*, not
    # ``part_nets``: the latter filters unknown pads out, and those are exactly
    # the ones worth reporting.
    physical = sum(1 for part in PARTS
                   for name in _pad_blocks(part.footprint)
                   if name in part_nets(part))
    padless: dict[str, list[str]] = {}
    for part in PARTS:
        local = _pad_positions(part.footprint)
        for pad in table.get(part.ref, {}):
            if pad not in local:
                padless.setdefault(_padless_reason(part, pad), []).append(
                    f"{part.ref}.{pad}")
    return {
        "status": "NETTED_PLACEMENT_NOT_ROUTED",
        "source": "hardware/dcx_main/pin_footprint_review.csv",
        "net_count": len(nets),
        "pads_landed": landed,
        "physical_pads_netted": physical,
        "pads_landed_note": "pad names with a net; physical pads are higher where a "
                            "footprint splits one pin across several lands (the SR FET "
                            "drain: a common base plus four fingers, two of which share "
                            "the name 5).  KiCad merges same-numbered pads, and also "
                            "same-net lands whose copper overlaps, so the ratsnest is "
                            "shorter than pads_landed - net_count",
        "nets": rows,
        "single_pad_nets": [n["net"] for n in rows if n["pads"] == 1],
        "single_pad_nets_note": "a net with one pad here draws no ratsnest line and "
                                "owes no track: its other members (gate resistors, the "
                                "CT secondary rectifiers) are off this board. Listed so "
                                "they are not read as routed",
        "lumped_from_one_netlist_element": {
            f"{BANK_PREFIX}1..{BANK_PREFIX}{_cout()['n']}":
                "the schematic models the whole bank as one lumped Cout; these "
                "fifteen borrow its two nets and the BOM must expand it into "
                "fifteen lines"},
        "not_in_the_netlist_at_all": ["U2"],
        "not_in_the_netlist_reason": "one outline stands for the whole control "
                                     "section; it has no pads and carries no net",
        "netlist_pins_without_a_physical_pad": padless,
        "netlist_pins_without_a_physical_pad_note": "grouped by why, because the two "
                                                   "causes are different defects: a "
                                                   "repeated pad name is a land-pattern "
                                                   "gap, a padless outline is a "
                                                   "placeholder",
        "pad_without_a_net": [{"ref": r["ref"], "pad": r["pad"], "note": r["note"]}
                              for r in review_rows()
                              if r["ref"] in placed and not r["net"].strip()],
        "not_placed_here_netlist_refs": sorted(set(table) - placed),
        "not_placed_here_reason": "power-stage placement only; control, drive and "
                                  "decoupling parts have no position on this board",
        "length_note": "straight-line spanning tree over pad centres, a lower "
                       "bound on copper and not a route",
    }


def report() -> dict:
    height = _load("magnetics/magnetics_design.json")["height"]
    flat = height["flat_no_pocket"]
    clamp = height["with_0.5mm_clamp"]
    magnetics = sorted(p.ref for p in PARTS if p.footprint in CORE_FOOTPRINTS)
    gap, ga, gb = min_gap_mm()
    w, d = board_rect()
    return {
        "status": "netted placement - connectivity drawn, nothing routed",
        "board": {"width_mm": w, "depth_mm": d, "thickness_mm": BOARD_T},
        "parts": [
            {"ref": p.ref, "value": p.value, "evidence": p.evidence,
             "w_mm": round(p.w_mm, 3), "d_mm": round(p.d_mm, 3),
             "h_mm_worst": round(p.h_mm_worst, 3),
             "x_mm": round(p.x, 3), "y_mm": round(p.y, 3), "rot_deg": p.rot,
             "note": p.note}
            for p in PARTS
        ],
        "height": {
            "limit_mm": HEIGHT_LIMIT_MM,
            "parts_max_height_mm": round(max(p.h_mm_worst for p in PARTS), 3),
            "flat_board_worst_case_mm": round(flat["worst_case_m"] * 1e3, 3),
            "flat_board_margin_mm": round(HEIGHT_LIMIT_MM - flat["worst_case_m"] * 1e3, 3),
            "clamp_case_worst_case_mm": round(clamp["worst_case_m"] * 1e3, 3),
            "clamp_case_margin_mm": round(HEIGHT_LIMIT_MM - clamp["worst_case_m"] * 1e3, 3),
            "pocket_required_refs": magnetics,
            "at_limit_refs": sorted(p.ref for p in PARTS
                                    if HEIGHT_LIMIT_MM - p.h_mm_worst < 0.5),
            "note": "flat 9.94 mm clears 10 mm by 60 um, which is smaller than glue, "
                    "label and core flatness; with a 0.5 mm clamp the same stack is "
                    "10.44 mm and over, so the cores need pockets",
        },
        "clearance": {"min_gap_mm": round(gap, 3), "between": [ga, gb]},
        "overlaps": [{"a": a, "b": b, "area_mm2": round(area, 3)}
                     for a, b, area in overlaps(PARTS)],
        "section": mechanical_section(),
        "pocket": pocket_requirements(),
        "provisional": sorted(p.ref for p in PARTS if p.evidence == "PROVISIONAL"),
        "land_pattern_provisional": sorted(
            # Class, not prose: ``datasheet`` means body dimensions only, so the
            # pads are placeholders.  ``digitised-datasheet`` is the class that
            # carries a measured land pattern and must not appear here -- the
            # old substring test caught the SR FETs the moment their note
            # started describing the new pad geometry.
            p.ref for p in PARTS if p.evidence == "datasheet"),
        "nets": nets_report(),
        # Named explicitly so a consumer never has to guess the reference
        # scheme.  ``cout_bank_path.py`` used to select the bank by ``C1xx``;
        # renaming the units to ``Cout1..`` then silently emptied its input and
        # it failed with "a bank row needs at least two units" rather than
        # saying which part it could not find.
        "cout_bank_refs": [p.ref for p in PARTS if p.ref.startswith(BANK_PREFIX)],
        "toolchain": toolchain(),
    }


def toolchain() -> dict:
    """What the board was built from, so a rebuild can be reproduced elsewhere.

    Deliberately **machine-independent**: it names the vendored footprint and
    its hash, and says where the KiCad version is recorded.  Putting the local
    ``kicad-cli --version`` here would make ``placement_report.json`` differ
    between a developer's machine and CI, which is the very failure Issue #11
    is about.  The version that actually ran the DRC lives in ``drc.json``
    (``kicad_version``), next to the run it belongs to.
    """
    generated = {f"dcx:{Path(name).stem}" for name in footprint_library()}
    files = sorted({p.footprint for p in PARTS if p.footprint not in generated})
    return {
        "generator": "tools/main_board_mechanical.py",
        "kicad_needed_for": "DRC and drawings only; the board file needs no KiCad",
        "kicad_version_source": "hardware/dcx_mech/drc.json:kicad_version",
        "stock_footprints": [
            {"lib_id": lib_id,
             "sha256": sha256(stock_footprint_path(lib_id).read_bytes()
                              .replace(b"\r\n", b"\n")).hexdigest()}
            for lib_id in files
        ],
    }


# ---------------------------------------------------------------- footprints
def _pad(number: str, x: float, y: float, dx: float, dy: float, shape: str = "rect") -> str:
    return (
        f'    (pad "{number}" thru_hole {shape}\n'
        f'      (at {x:g} {y:g})\n'
        f'      (size {dx:g} {dy:g})\n'
        f'      (drill {min(dx, dy) / 2:g})\n'
        f'      (layers "*.Cu" "*.Mask")\n'
        f'      (uuid "{uid("pad", number, str(x), str(y))}")\n'
        f'    )\n'
    )


def _outline_footprint(name: str, w: float, d: float, descr: str,
                       pads: list[tuple[str, float, float]],
                       pad_mm: float = 2.0) -> str:
    """A rectangular through-hole footprint: fab outline, courtyard at +0.25 mm,
    and one pad per terminal the caller names.

    The pad *names* matter now that the board carries nets: they are the same
    strings ``pin_footprint_review.csv`` uses, so a net lands on a pad by
    identity rather than by position in a list.  Deliberately minimal -- there
    is no copper land pattern here because the part is not selected."""
    cy, cx = d / 2 + 0.25, w / 2 + 0.25
    s = (f'(footprint "{name}"\n'
         f'\t(version 20260206)\n'
         f'\t(generator "main_board_mechanical")\n'
         f'\t(layer "F.Cu")\n'
         f'\t(descr "{descr}")\n'
         f'\t(attr through_hole)\n'
         f'\t(property "Reference" "REF**" (at 0 {-cy - 1.2:g} 0) (layer "F.SilkS")\n'
         f'\t\t(uuid "{uid("prop", name, "ref")}"))\n'
         f'\t(property "Value" "{name}" (at 0 {cy + 1:g} 0) (layer "F.Fab")\n'
         f'\t\t(uuid "{uid("prop", name, "val")}"))\n')
    for layer, half_w, half_d in (("F.Fab", w / 2, d / 2), ("F.CrtYd", cx, cy)):
        s += (f'\t(fp_rect (start {-half_w:g} {-half_d:g}) (end {half_w:g} {half_d:g})\n'
              f'\t\t(stroke (width {0.05 if layer == "F.CrtYd" else 0.1:g}) (type solid))\n'
              f'\t\t(fill none) (layer "{layer}") (uuid "{uid("rect", name, layer)}"))\n')
    for pad_name, px, py in pads:
        s += _pad(pad_name, px, py, pad_mm, pad_mm)
    return s + ")\n"


def footprint_library() -> dict[str, str]:
    """The project-local footprints, keyed by file name in ``dcx.pretty/``."""
    core = _core()
    bar = _bar()
    w = core["outer_length_m"] * 1e3
    d = core["core_depth_m"] * 1e3
    cout = _cout()
    files = {
        # Terminals at +/- 10 mm are a place to draw the winding exit, not a
        # measured bobbin.  Stated in the descr so the board file says it too.
        # Two footprints on one core outline: the transformer exposes the five
        # logical terminals the netlist names, the inductor only its two.  A
        # single five-pad footprint would leave three pads dangling on Lr.
        "ELP32_XFMR.kicad_mod": _outline_footprint(
            "ELP32_XFMR", w, d,
            "TDK ELP32 (B66287) 3:1:1 planar, 31.75x25.4x9.5 mm. "
            "Terminal positions PROVISIONAL: the winding exit is not drawn yet.",
            [("PRI_A", -10.0, -4.0), ("PRI_B", -10.0, 4.0), ("CTAP", 10.0, 0.0),
             ("SEC_A", 10.0, -5.0), ("SEC_B", 10.0, 5.0)]),
        "ELP32_LR.kicad_mod": _outline_footprint(
            "ELP32_LR", w, d,
            "TDK ELP32 (B66287), same core as T1-T4, two terminals. "
            "Pad names are the review table's pad column (1, 2), not the "
            "schematic's logical N1/N2, so a net lands by identity. "
            "Terminal positions PROVISIONAL.",
            [("1", -10.0, 0.0), ("2", 10.0, 0.0)]),
        "Busbar_20x2.kicad_mod": _outline_footprint(
            "Busbar_20x2", bar["length_mm"], bar["width_mm"],
            "Output copper bar 80x20x2 mm. Contact resistance UNVERIFIED.",
            [("1", -35.0, 0.0), ("2", 35.0, 0.0)]),
        "Placeholder_18x6.kicad_mod": _outline_footprint(
            "Placeholder_18x6", 18, 6, "PROVISIONAL - Cr film capacitor, no part selected",
            [("1", -7.0, 0.0), ("2", 7.0, 0.0)]),
        "Placeholder_20x15.kicad_mod": _outline_footprint(
            "Placeholder_20x15", 20, 15,
            "PROVISIONAL - over-current CT, no part selected. Four logical "
            "terminals per the netlist; the physical part is not chosen and no "
            "pinout is verified.",
            [("PRI_A", -8.0, -3.0), ("PRI_B", -8.0, 3.0),
             ("SEC_A", 8.0, -3.0), ("SEC_B", 8.0, 3.0)]),
        "Placeholder_10x10.kicad_mod": _outline_footprint(
            "Placeholder_10x10", 10, 10, "PROVISIONAL - 48 V input terminal, no part selected",
            [("1", -2.54, 0.0), ("2", 2.54, 0.0)]),
        "Placeholder_12x12.kicad_mod": _outline_footprint(
            "Placeholder_12x12", 12, 12,
            "PROVISIONAL - control area, no layout done. Deliberately padless: "
            "this outline stands for the whole control section, so any pad it "
            "carried would be a pin of a part that has no position yet.",
            []),
        # Nine pads because the netlist gives QH/QL nine pins (1-3 source,
        # 4 gate, 5-9 drain).  0.6 mm pads on a 1 mm pitch are a drawing, not a
        # land pattern -- the recommended layout is a figure in the datasheet.
        "Placeholder_SON_5x6.kicad_mod": _outline_footprint(
            "Placeholder_SON_5x6", 5.00, 6.10,
            "PROVISIONAL land pattern - CSD19531Q5A (VSONP DQJ): body 5.00x6.10 from "
            "datasheet p9, but the recommended board pads are a figure, not text, and "
            "are not reproduced here",
            [("1", -1.6, -1.0), ("2", -1.6, 0.0), ("3", -1.6, 1.0),
             ("4", -1.6, 2.0), ("5", 1.2, -2.0), ("6", 1.2, -1.0),
             ("7", 1.2, 0.0), ("8", 1.2, 1.0), ("9", 1.2, 2.0)],
            pad_mm=0.6),
        "Placeholder_Cout.kicad_mod": _outline_footprint(
            "Placeholder_Cout", 7.3, 4.3,
            "Bulk output capacitor: max height 2.1 mm from YAGEO OEM; the "
            "7.3x4.3 outline fixed by OEM; PCB land pads are PROVISIONAL",
            [("1", -2.0, 0.0), ("2", 2.0, 0.0)]),
        # The one real land pattern on this board.  The vendored TDSON-8 named
        # all five drain lands "5", so the schematic's drain pins 6-8 had no
        # pad; the datasheet figure has four drain fingers on a common base.
        "BSC010N04LS6.kicad_mod": _bsc_source(),
    }
    return files


FP_TABLE = '(fp_lib_table\n  (version 7)\n  (lib (name "dcx")(type "KiCad")' \
           '(uri "${KIPRJMOD}/dcx.pretty")(options "")(descr "generated placement footprints"))\n)\n'


def project_file() -> str:
    """Same trap as the schematic side: without a ``.kicad_pro`` next to the
    board, ``kicad-cli`` never loads ``fp-lib-table``, so every ``dcx:``
    footprint is reported as an unknown library -- and an unresolved footprint
    has no courtyard, so DRC silently stops checking it.

    ``tracks``/``net_settings`` are empty on purpose: this file has no nets.

    ``missing_courtyard`` is raised from its default *warning* to **error**.
    That is the check this study actually relies on -- a footprint without a
    courtyard is exempt from every clearance question -- and Issue #11 asks for
    the DRC result never to be quoted as "clean" while that check is ignored."""
    return json.dumps({
        "board": {"design_settings": {
            "rule_severities": {"missing_courtyard": "error"},
        }},
        "boards": [], "cvpcb": {}, "erc": {},
        "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
        "meta": {"filename": "power_stage_placement.kicad_pro", "version": 1},
        "net_settings": {}, "pcbnew": {"page_layout_descr_file": ""},
        "schematic": {"legacy_lib_dir": "", "legacy_lib_list": []},
        "sheets": [], "text_variables": {},
    }, indent=2) + "\n"


# ---------------------------------------------------------------- board file
def _inject_pad_nets(text: str, nets: dict[str, str], ids: dict[str, int]) -> str:
    """Add ``(net N "NAME")`` to every pad whose name the review table knows.

    Found by paren depth rather than by regex: a pad block contains nested
    parentheses (``size``, ``layers``, ``drill``) and a regex that stopped at
    the first ``)`` would cut the block in half.  The net goes where KiCad puts
    it -- after ``layers``, before ``uuid``.
    """
    out: list[str] = []
    i = 0
    marker = '(pad "'
    while True:
        j = text.find(marker, i)
        if j < 0:
            out.append(text[i:])
            return "".join(out)
        out.append(text[i:j])
        k = text.find('"', j + len(marker))
        name = text[j + len(marker):k]
        depth, end = 0, j
        while end < len(text):
            if text[end] == "(":
                depth += 1
            elif text[end] == ")":
                depth -= 1
                if depth == 0:
                    break
            end += 1
        block = text[j:end + 1]
        net = nets.get(name)
        if net:
            pos = block.rfind("(uuid ")
            if pos > 0:
                line = block.rfind("\n", 0, pos) + 1
                indent = block[line:pos]
                block = (block[:line] + indent + f'(net {ids[net]} "{net}")\n'
                         + block[line:])
        out.append(block)
        i = end + 1


def _embed(mod_text: str, lib_id: str, ref: str, value: str, x: float, y: float,
           rot: float, nets: dict[str, str] | None = None,
           ids: dict[str, int] | None = None) -> str:
    """Turn a ``.kicad_mod`` body into a placed footprint instance.

    A ``.kicad_pcb`` carries the geometry inline, so the library file is copied
    in rather than referenced.  Five things change: the library id, the
    placement, the reference, every uuid (two instances sharing a uuid make
    KiCad pick one at random when the file is opened), and -- when the netlist
    has a row for this pad -- the net."""
    text = mod_text
    for pat in (r"\(version [^)]*\)\s*", r'\(generator "[^"]*"\)\s*',
                r'\(generator_version "[^"]*"\)\s*'):
        text = re.sub(pat, "", text, count=1)
    text = re.sub(r'\(footprint "[^"]+"', f'(footprint "{lib_id}"', text, count=1)
    text = text.replace(
        '(layer "F.Cu")',
        f'(layer "F.Cu")\n\t(uuid "{uid("fp", ref)}")\n\t(at {x:g} {y:g} {rot:g})',
        1)
    text = text.replace('(property "Reference" "REF**"', f'(property "Reference" "{ref}"', 1)
    text = re.sub(r'\(property "Value" "[^"]*"', f'(property "Value" "{value}"', text, count=1)
    text = re.sub(r'\(uuid "([^"]+)"\)', lambda m: f'(uuid "{uid(ref, m.group(1))}")', text)
    if nets:
        text = _inject_pad_nets(text, nets, ids or {})
    return "\t" + text.strip() + "\n"


def board_file(libs: dict[str, str]) -> str:
    w, d = board_rect()
    mods = {f"dcx:{Path(name).stem}": text for name, text in libs.items()}
    nets = placed_nets()
    ids = {net: i for i, net in enumerate(sorted(nets), start=1)}
    out = [
        "(kicad_pcb\n\t(version 20260206)\n\t(generator \"main_board_mechanical\")\n"
        "\t(generator_version \"10.0\")\n\t(general (thickness 1.6))\n"
        "\t(paper \"A3\")\n\t(title_block\n"
        "\t\t(title \"DCX 48V-2V 100A - A5 1:1 power-stage placement\")\n"
        "\t\t(comment 1 \"NETTED PLACEMENT - no routing; every ratsnest line is a missing track\")\n"
        "\t\t(comment 2 \"PROVISIONAL outlines: CT, Cr, J_IN, U2 area, Cout case size\")\n"
        "\t)\n"
        "\t(layers\n"
        '\t\t(0 "F.Cu" signal)\n\t\t(31 "B.Cu" signal)\n'
        # Paste and mask are declared, not only referenced by pads: kicad-cli
        # plots only the layers this table lists and drops the rest without a
        # message, so a board that omits them yields a package with no mask.
        '\t\t(34 "B.Paste" user)\n\t\t(35 "F.Paste" user)\n'
        '\t\t(36 "B.SilkS" user "B.Silkscreen")\n\t\t(37 "F.SilkS" user "F.Silkscreen")\n'
        '\t\t(38 "B.Mask" user)\n\t\t(39 "F.Mask" user)\n'
        '\t\t(44 "Edge.Cuts" user)\n\t\t(46 "B.CrtYd" user "B.Courtyard")\n'
        '\t\t(47 "F.CrtYd" user "F.Courtyard")\n'
        '\t\t(48 "B.Fab" user)\n\t\t(49 "F.Fab" user)\n\t)\n'
        "\t(setup (pad_to_mask_clearance 0))\n"
    ]
    for net in sorted(nets):
        out.append(f'\t(net {ids[net]} "{net}")\n')
    # Edge.Cuts as four straight segments -- a rectangle drawn with gr_rect is
    # legal but some viewers only close the outline from segments.
    for name, (x0, y0, x1, y1) in {
        "top": (0, 0, w, 0), "right": (w, 0, w, d),
        "bottom": (w, d, 0, d), "left": (0, d, 0, 0),
    }.items():
        out.append(f'\t(gr_line (start {x0:g} {y0:g}) (end {x1:g} {y1:g})'
                   f' (stroke (width 0.1) (type solid)) (layer "Edge.Cuts")'
                   f' (uuid "{uid("edge", name)}"))\n')
    for part in PARTS:
        lib_id = part.footprint
        text = mods.get(lib_id) or _stock_footprint(lib_id)
        out.append("\t" + _embed(text, lib_id, part.ref, part.value,
                                 part.x, part.y, part.rot,
                                 part_nets(part), ids).strip() + "\n")
    out.append(")\n")
    return "".join(out)


def stock_footprint_path(lib_id: str) -> Path:
    """Where the vendored copy of a stock footprint lives."""
    lib, name = lib_id.split(":", 1)
    return STOCK / f"{lib}.pretty" / f"{name}.kicad_mod"


# ---------------------------------------------------------------- A6 section
POCKET_MM = 0.5          # design choice, not yet cleared with a fabricator
CLAMP_MM = 0.5           # 压块, an assumption: the cores cannot float
GLUE_MM, GLUE_MAX_MM = 0.05, 0.08      # assumed: no adhesive data sheet here
LABEL_MM, LABEL_MAX_MM = 0.05, 0.06    # assumed: optional, a label may be skipped


def mechanical_section() -> dict:
    """The Z stack-up with an explicit datum and tolerance chain (Issue #12).

    Issue #12's first blocking question is what "10 mm" even measures.  The
    repo has three answers in it and they are not the same number, so this
    table states the datum first and then lists every contributor above and
    below it, with the class of evidence behind its thickness.

    Below the datum the pocket is *not* free: 0.5 mm out of a 1.6 mm board
    leaves 1.1 mm of FR-4 under the five cores for insulation and support;
    the SR return current requires a separate continuous copper/via/busbar path.

    Above the stack there is nothing in this repository at all -- no TIM, no
    cold plate, no fastener heads.  That is reported as UNKNOWN rather than
    omitted, because omitting it is how a 10 mm claim gets made without anyone
    deciding what the 10 mm covers.
    """
    data = _load("magnetics/magnetics_design.json")
    core, height = data["core"], data["height"]
    up = [
        {"item": "ELP32 磁芯对（B66287 半对 ×2）",
         "nominal_mm": round(core["height_nominal_m"] * 1e3, 3),
         "worst_mm": round(core["height_max_m"] * 1e3, 3), "evidence": "datasheet",
         "note": "9.5 标称 / 9.8 最大，已含研磨气隙"},
        {"item": "胶层", "nominal_mm": GLUE_MM, "worst_mm": GLUE_MAX_MM,
         "evidence": "ASSUMED", "note": "本仓库没有胶的规格书，最大值是假设"},
        {"item": "标签", "nominal_mm": LABEL_MM, "worst_mm": LABEL_MAX_MM,
         "evidence": "ASSUMED", "note": "可选；不做标签直接省掉 0.06 mm 的极端值"},
        {"item": "压块", "nominal_mm": CLAMP_MM, "worst_mm": CLAMP_MM,
         "evidence": "DESIGN", "note": "五只裸磁芯不能悬空；压块形式与厚度都还没定"},
    ]
    down = [
        {"item": "沉槽", "nominal_mm": -POCKET_MM, "worst_mm": -POCKET_MM,
         "evidence": "DESIGN", "note": "尚未与 PCB 厂确认 0.5 mm 沉槽工艺"},
        {"item": "沉槽下剩余介质", "nominal_mm": BOARD_T - POCKET_MM,
         "worst_mm": BOARD_T - POCKET_MM, "evidence": "DESIGN",
         "note": f"{BOARD_T} mm 板厚减沉槽；FR-4 仅提供结构与绝缘；SR 回流必须走连续铜层、过孔或铜排"},
    ]
    glue = next(x for x in up if x["item"] == "胶层")
    label = next(x for x in up if x["item"] == "标签")
    core_row = up[0]
    # Recompute from the rows and *check* against magnetics_design.json rather
    # than trusting one of the two: two independent sums that must agree is a
    # free consistency test, and a silent divergence here is exactly how the
    # document and the JSON drift apart.
    flat_rows = core_row["worst_mm"] + glue["worst_mm"] + label["worst_mm"]
    flat_json = height["flat_no_pocket"]["worst_case_m"] * 1e3
    if abs(flat_rows - flat_json) > 1e-6:
        raise SystemExit(
            f"height stack disagrees with magnetics_design.json: table {flat_rows} mm "
            f"vs JSON {flat_json} mm -- update GLUE_MAX_MM/LABEL_MAX_MM and rerun "
            f"python tools/magnetics_design.py")
    with_clamp = flat_rows + CLAMP_MM
    pocketed = with_clamp - POCKET_MM
    pocketed_plain = flat_rows - POCKET_MM
    return {
        "datum": "PCB 顶面 Z = 0；向上为正。所有尺寸都相对这个面，"
                 "不含 TIM、冷板与紧固件",
        "upward": up,
        "downward": down,
        "undefined_above_the_stack": [
            "TIM / 导热垫厚度与压缩量",
            "冷板或散热器离板面高度",
            "紧固件头部 / 螺纹嵌件凸出",
            "板弯与压块变形（装配态，不是零件公差）",
        ],
        "definitions": {
            "A_flat_no_pocket_no_clamp_mm": round(flat_rows, 3),
            "B_pocket_0p5_no_clamp_mm": round(pocketed_plain, 3),
            "C_pocket_0p5_with_clamp_mm": round(pocketed, 3),
            "D_with_tim_and_cold_plate_mm": None,
        },
        "definitions_note": "A/B/C 都是**模块相对 PCB 顶面**的数，可直接与 10 mm 比；"
                            "D 需要结构专业给出 TIM 与冷板数据后才有意义，现在必须留空",
        "finding": "0.5 mm 沉槽只是把 0.5 mm 压块买回来：C = A = 9.94 mm，余量仍是 +0.06 mm。"
                   "沉槽不是额外余量，是让压块方案回到原点。要真余量，只能减胶/去标签，"
                   "或把压块做进磁芯窗口而不是叠在上面",
        "gate": "未签核：没有 TIM/冷板/紧固件定义，也没有制造商对 0.5 mm 沉槽的确认，"
                "因此不得宣称 ≤10 mm 机电签核通过（Issue #12 关闭条件）",
        "clamp_case_margin_mm": round(HEIGHT_LIMIT_MM - with_clamp, 3),
        "pocket_case_margin_mm": round(HEIGHT_LIMIT_MM - pocketed, 3),
    }


def pocket_requirements() -> dict:
    """What 0.5 mm deep, five times, does to the board (Issue #12 item 2).

    A pocket is not a free vertical offset.  It is a routed cavity that removes
    20 % of the board's copper area, leaves 1.1 mm of dielectric under the
    heaviest parts on the assembly, and -- because it is on one side only --
    makes the stack asymmetric, which is what makes a board bow.

    The one thing that *can* be checked today is whether the cavities take
    copper away from the 100 A output plane.  They do not: the five cores sit
    at y <= 65 mm and the SR-to-busbar channel is y = 82..116 mm.  Recording a
    checked non-issue is worth as much as a finding, because the next person
    moving a transformer has no other way to know it was considered.
    """
    data = _load("magnetics/magnetics_design.json")
    core = data["core"]
    cores = [p for p in PARTS if p.footprint in CORE_FOOTPRINTS]
    w = core["outer_length_m"] * 1e3
    d = core["core_depth_m"] * 1e3
    per_core = w * d
    total = per_core * len(cores)
    bw, bd = board_rect()
    board_area = bw * bd
    channel = (82.0, 116.0)                 # SR row to J_OUT, the output plane
    core_top = max(part.y + part.d_mm / 2 for part in cores)
    core_bottom = min(part.y - part.d_mm / 2 for part in cores)
    return {
        "cores": len(cores),
        "pocket_per_core_mm2": round(per_core, 1),
        "pocket_total_mm2": round(total, 1),
        "board_area_mm2": round(board_area, 1),
        "fraction_of_board_pct": round(100.0 * total / board_area, 1),
        "depth_mm": POCKET_MM,
        "remaining_dielectric_mm": round(BOARD_T - POCKET_MM, 2),
        "depth_tolerance_mm": 0.1,          # typical routed-cavity tolerance
        "remaining_dielectric_range_mm": [round(BOARD_T - POCKET_MM - 0.1, 2),
                                          round(BOARD_T - POCKET_MM + 0.1, 2)],
        "core_footprint_y_mm": [round(core_bottom, 1), round(core_top, 1)],
        "output_channel_y_mm": list(channel),
        "pocket_overlaps_output_plane": core_top > channel[0],
        "checked_non_issues": [
            "沉槽不占用 100 A 输出平面（磁芯 y ≤ "
            f"{core_top:.0f} mm，通道 y = {channel[0]:.0f}..{channel[1]:.0f} mm）",
        ],
        "undefined": [
            "叠层：沉槽只削顶层还是进到内层？内层铺铜是否也需要让开？",
            "磁芯与 PCB 铜的绝缘等级（N97 是 MnZn 铁氧体，不能直接压在裸铜上）",
            "绕组的引出方式与沉槽边缘的爬电距离",
            "压块的受力点与反作用：压磁芯的力最终落在 1.1 mm 的介质上",
            "板弯：单面开槽使叠层不对称，板弯直接进高度预算",
        ],
        "manufacturability": {
            "ask_the_fabricator": [
                "1.6 mm FR4 上 0.5 mm 深、31.75 × 25.4 mm 的腔体能否做，公差多少",
                "腔体底部的铜（如有）是否保留，最小介质层厚是多少",
                "单面五处腔体对板弯的典型值",
            ],
            "status": "未询问",
        },
        "gate": "沉槽深度与位置在制造商书面确认前不得冻结；"
                "本表只说明它要什么，不说明它做得到",
    }


def _stock_footprint(lib_id: str) -> str:
    path = stock_footprint_path(lib_id)
    if not path.exists():
        raise SystemExit(
            f"{lib_id} is neither generated by this tool nor vendored at {path}.\n"
            f"If the board really needs a new stock footprint, copy it out of a "
            f"KiCad install into {STOCK} and record the version, the sha256 and "
            f"the licence in {STOCK / 'PROVENANCE.md'} -- do not point the "
            f"generator at somebody's home directory.")
    return path.read_text(encoding="utf-8")


def find_kicad_cli() -> Path | None:
    """Locate ``kicad-cli`` without naming a user or a version.

    Order: ``KICAD_CLI`` env var, then PATH, then the per-user and machine-wide
    install roots that KiCad's own installers use on Windows, newest first.
    Returning ``None`` is a normal outcome -- the board file itself needs no
    KiCad, only the DRC and the drawings do.
    """
    env = os.environ.get("KICAD_CLI")
    if env and Path(env).exists():
        return Path(env)
    on_path = shutil.which("kicad-cli")
    if on_path:
        return Path(on_path)
    roots = [os.environ.get("LOCALAPPDATA"), os.environ.get("PROGRAMFILES"),
             os.environ.get("PROGRAMFILES(X86)")]
    candidates: list[Path] = []
    for root in filter(None, roots):
        for pattern in ("Programs/KiCad/*/bin/kicad-cli.exe", "KiCad/*/bin/kicad-cli.exe"):
            candidates += sorted(Path(root).glob(pattern), reverse=True)
    return candidates[0] if candidates else None


def find_kicad_share() -> Path | None:
    """The installed KiCad data directory, if there is one.

    Only used to *cross-check* the vendored footprints; generation never reads
    from it.
    """
    env = os.environ.get("KICAD_SHARE")
    if env and Path(env).exists():
        return Path(env)
    cli = find_kicad_cli()
    if cli is not None:
        share = cli.parent.parent / "share" / "kicad"
        if share.exists():
            return share
    return None


# ---------------------------------------------------------------- write
def write(out_dir: Path | None = None) -> dict:
    out_dir = Path(out_dir or OUT)
    libs = footprint_library()
    pretty = out_dir / "dcx.pretty"
    pretty.mkdir(parents=True, exist_ok=True)
    for name, text in libs.items():
        (pretty / name).write_text(text, encoding="utf-8", newline="\n")
    (out_dir / "fp-lib-table").write_text(FP_TABLE, encoding="utf-8", newline="\n")
    (out_dir / "power_stage_placement.kicad_pro").write_text(
        project_file(), encoding="utf-8", newline="\n")
    (out_dir / "power_stage_placement.kicad_pcb").write_text(
        board_file(libs), encoding="utf-8", newline="\n")
    data = report()
    (out_dir / "placement_report.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return data


def draw(out_dir: Path | None = None) -> list[Path]:
    """The two reviewer-facing pictures.

    The SVG is exported at ``--scale 1`` with the page cropped to the board, so
    its ``width`` attribute is the real board size in mm and it can be printed
    at 1:1 to lay parts on paper.  The 3D view shows what the stack actually
    looks like -- note that the generated footprints carry no 3D model, so the
    magnetics appear as pads only; that is a limit of this drawing, not of the
    parts.
    """
    out_dir = Path(out_dir or OUT)
    out_dir.mkdir(parents=True, exist_ok=True)
    board = out_dir / "power_stage_placement.kicad_pcb"
    cli = find_kicad_cli()
    if cli is None:
        return []
    svg = out_dir / "placement_1to1.svg"
    png = out_dir / "placement_top.png"
    subprocess.run([str(cli), "pcb", "export", "svg", "--mode-single", "--scale", "1",
                    "--page-size-mode", "2", "-l", "F.Fab,Edge.Cuts,F.CrtYd,F.SilkS",
                    "-o", str(svg), str(board)], check=False, capture_output=True)
    subprocess.run([str(cli), "pcb", "render", "--side", "top", "-w", "1400",
                    "-h", "1200", "--background", "opaque", "-o", str(png), str(board)],
                   check=False, capture_output=True)
    return [svg, png]


def _drc(path: Path | None = None) -> dict:
    path = path or OUT / "drc.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def violations(path: Path | None = None) -> list[dict]:
    return _drc(path).get("violations", [])


def unconnected(path: Path | None = None) -> list[dict]:
    """Ratsnest lines still missing a track.

    ``kicad-cli`` puts these in a **second** top-level array, not in
    ``violations``, so reading only the first one reports "nothing
    unconnected" on a board where nothing is routed at all.  This board is
    unrouted on purpose, so the count is reported as debt -- it is the number
    of connections the layout still owes, not a defect of the placement.
    """
    return _drc(path).get("unconnected_items", [])


def check() -> None:
    data = write()
    board = OUT / "power_stage_placement.kicad_pcb"
    print(f"board {data['board']['width_mm']} x {data['board']['depth_mm']} mm, "
          f"{len(data['parts'])} parts, min gap {data['clearance']['min_gap_mm']} mm "
          f"({data['clearance']['between'][0]}/{data['clearance']['between'][1]})")
    print(f"height: flat {data['height']['flat_board_worst_case_mm']} mm "
          f"(margin {data['height']['flat_board_margin_mm']:+} mm), "
          f"clamp {data['height']['clamp_case_worst_case_mm']} mm "
          f"(margin {data['height']['clamp_case_margin_mm']:+} mm)")
    print(f"provisional outlines: {', '.join(data['provisional'])}")
    cli = find_kicad_cli()
    if cli is None:
        print("kicad-cli not found (KICAD_CLI, PATH, or a standard install) -- "
              "DRC and drawings NOT reproduced; the committed board was still regenerated")
        return
    print("kicad-cli:", subprocess.run([str(cli), "--version"], capture_output=True,
                                       text=True, check=False).stdout.strip())
    draw()
    subprocess.run([str(cli), "pcb", "drc", "--format", "json", "--severity-all",
                    "-o", str(OUT / "drc.json"), str(board)], check=False, capture_output=True)
    vs = violations()
    errors = [v for v in vs if v["severity"] == "error"]
    unknown = [v for v in vs if v["type"] == "lib_footprint_issues"]
    # ``missing_courtyard`` is a warning by default, so a board whose footprints
    # carry no courtyard passes a severities-as-shipped run while checking
    # nothing about placement.  ``project_file()`` raises it to error; count it
    # here so a silent regression shows up in the printed line too.
    bare = [v for v in vs if v["type"] == "missing_courtyard"]
    nets = data["nets"]
    ratsnest = unconnected()
    print(f"DRC: {len(vs)} violations, {len(errors)} errors, {len(unknown)} unknown-footprint, "
          f"{len(bare)} footprints without a courtyard")
    print(f"nets: {nets['net_count']} nets on {nets['pads_landed']} netlist pads; "
          f"ratsnest: {len(ratsnest)} unconnected pairs still owing a track")
    # An empty ratsnest on a board that carries nets would mean the injections
    # did not reach the pads -- the exact inversion the SR board hit when it
    # read ``violations`` and found "0 unconnected" on an unrouted layout.
    if nets["net_count"] and not ratsnest:
        raise SystemExit("the board declares nets but kicad-cli reports nothing unconnected "
                         "-- either every net was routed, or the (net ...) children never "
                         "reached the pads")
    for v in (errors + unknown + bare)[:5]:
        print(f"  {v['severity']} {v['type']}: {v['description']}")
    if errors or unknown or bare:
        raise SystemExit("DRC is not clean -- a placement study may leave pads unconnected, "
                         "but a courtyard collision, a footprint without a courtyard, or an "
                         "unresolved library is a real defect")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="regenerate and run kicad-cli DRC")
    args = ap.parse_args()
    if args.check:
        check()
    else:
        data = write()
        print(f"wrote {OUT} ({len(data['parts'])} parts, "
              f"{data['board']['width_mm']} x {data['board']['depth_mm']} mm)")


if __name__ == "__main__":
    main()

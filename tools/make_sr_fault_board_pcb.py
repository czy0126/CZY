"""Layout pass 3 of the single-pair SR validation board: routed and poured.

What this is
------------
A *native* KiCad board for the same part table the schematic generator
(`tools/make_sr_fault_board.py`) already produces: every part placed once, every
pad carrying its schematic net, a real outline and mounting holes, every
multi-pad net routed on two layers, and DRC run over the result.

What it is not
--------------
**Not released.**  The five power nets in ``POURS`` carry a zone outline and
the fills have been measured (``fill.json``, written by ``--check`` from a
copy kicad-cli refilled): between 75 % and 98 % of each outline survives, as a
single patch per corridor.  Two different mechanisms buy that, and the second
one exists because the first was measurably not enough:

* ``Router._zone_cost`` charges every other net for crossing a corridor, so
  routing prefers to go around or via to the other layer;
* the VOUT band is declared a *barrier* (``Pour.barrier``), so on its own layer
  its cells are a wall, not a price.  A price only wins when the detour costs
  more than the charge, and crossing the 5.5 mm band is 44 cells -- about 260
  steps at ``ZONE_PRESSURE 6`` -- cheaper than any detour along a 100 mm
  corridor.  Measured with the pressure alone, a single PGND track crossed the
  band and the fill kept 11.3 % of it.

The barrier is not absolute: a pad inside a corridor cannot be reached any
other way, so a connection that must cross is made and recorded in
``routing.barrier_crossings`` rather than left unrouted.  Before either
mechanism existed the same board kept 2.5 %-65 %: a signal crossing the outline
cuts the fill in two, and ``island_removal_mode 0`` deletes the half that
reaches no pad, so the pour looked present and carried nothing.  What the
corridors still are not is a *quoted* conductor on their own: the fill is a
build product and is not in the board file, so the current is quoted against
the routed escape (``power_path.escape_rating``) in two separate bases -- an
adiabatic I2t for one fault pulse, an IPC-2221 chart for a continuous current
-- and the via barrel binds the pulse number at either copper weight.  The
power path, the remaining work and the three false flags (`routed` here means
"every net connected", never "released") are all in
``sr_fault_validation_pcb.json``.  ``--fab`` exports gerbers, drill and
position into ``fab/`` with a manifest that binds every file to the board hash
and repeats the rating as a stated limit; it is a package, not an approval, and
the two approval flags stay false.

Why placement is worth doing before routing
-------------------------------------------
The SR board exists to measure how a real UCC24624 lets go of the gate, so the
placement fixes two things the schematic cannot:

* the high-current loop ``SEC_x -> Q -> SR_SRC -> Rsh1 -> PGND`` is kept short
  and in one direction, with ``Rsh1`` between the two sources and the return;
* ``VSS`` is a Kelvin tap off ``SR_SRC`` through R1, kept away from the power
  return -- the board is only useful if that separation survives layout.

The evidence classes, the honest flags and the leftover work are all in
``sr_fault_validation_pcb.json``; nothing here claims a released or
fabrication-approved board.

Usage:
    python tools/make_sr_fault_board_pcb.py --write
    python tools/make_sr_fault_board_pcb.py --check    # + DRC, fills, fab/
    python tools/make_sr_fault_board_pcb.py --fab      # --check, fail if no package
"""

from __future__ import annotations

import argparse
import collections
import csv
import functools
import hashlib
import json
import math
import re
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

import make_sr_fault_board as sch
import sr_board_router as router
from main_board_mechanical import find_kicad_cli

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "pcb" / "sr_fault_validation"
STOCK = ROOT / "hardware" / "stock_footprints"
BOARD = "sr_fault_validation.kicad_pcb"
REPORT = "sr_fault_validation_pcb.json"
FAB = OUT / "fab"
FAB_MANIFEST = FAB / "manifest.json"
FAB_COPPER_WEIGHT_OZ = 1        # the package's requirement; 1 oz is the standard process
FAB_GERBER_LAYERS = ("F.Cu,B.Cu,F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,"
                     "F.Mask,B.Mask,Edge.Cuts")
# What kicad-cli names each plot.  Checking by suffix rather than by counting
# files is what turns "one layer vanished" into a named failure: the first
# package silently shipped five plots for nine requested layers.
FAB_GERBER_SUFFIX = {
    "F.Cu": ".gtl", "B.Cu": ".gbl",
    "F.Paste": ".gtp", "B.Paste": ".gbp",
    "F.Silkscreen": ".gto", "B.Silkscreen": ".gbo",
    "F.Mask": ".gts", "B.Mask": ".gbs",
    "Edge.Cuts": ".gm1",
}
MANUFACTURING_PACKAGE_EXPORTED = "EXPORTED_WITH_STATED_CURRENT_LIMIT"
NS = uuid.UUID("c7e2a4f1-5b3d-4a8e-9f60-2d1c8b7a4e53")

BOARD_W_MM = 132.0
BOARD_D_MM = 92.0
THICKNESS_MM = 1.6
GAP_MM = 1.25          # courtyard-to-courtyard; see the breakout note below
GRID_MM = 0.5
HOLE_COURTYARD_R_MM = 3.7
HOLE_LIB_ID = "dcx:MountingHole_3.2mm_M3"
BSC_LIB_ID = "dcx:BSC010N04LS6"
# The land pattern is a measurement of the datasheet, not a literal in this
# file: tools/bsc010n04ls6_land.py digitises Figure 2 and refuses to write
# unless every printed callout matches its model to within 10 um.
BSC_LAND_JSON = ROOT / "design" / "v3" / "pcb" / "bsc010n04ls6_land.json"

# Track widths.  0.25 mm is a signal track; 0.8 mm is the widest that still
# fits between a fine-pitch land and its neighbours on a two-layer board with
# 0.2 mm clearance.  Neither is a current rating: at 1 oz the power loop needs
# pours, not tracks, for the board's 10 A ceiling -- see the report's
# ``power_path`` note.  Widths are per net class, not per net, so a reviewer can
# check them against the schematic without reading the router.
ROUTE_SIGNAL_MM = 0.25
ROUTE_POWER_MM = 0.8

# Per-instance reference-text offsets, in millimetres, added to the offset the
# footprint already carries.  Silk only: the text is drawn by the footprint, so
# a clash with a neighbour can only be fixed by moving that instance's text.
# "Rg1"/"Rg2" have a descender in "g" that reaches their own silkscreen line;
# TP13/TP17 sit 3.5 mm from their pair while 1 mm text is wider than that, so
# they move to the other side of the probe row.  Both were the last four DRC
# warnings, and neither changes copper, nets or the netlist.
REFERENCE_TEXT_SHIFT_MM = {
    "Rg1": (0.0, -0.8),
    "Rg2": (0.0, -0.8),
    "TP13": (0.0, 2.9),
    "TP17": (0.0, 2.9),
}
# VSS is deliberately not here: on this board it is the UCC24624's source
# reference, three pads (U1.5, R1.1, TP11.1) joined through a 0R Kelvin tap.
# It carries the gate-drive return, not the SR current -- the return is PGND,
# and the SR source is SR_SRC.  Routing it at power width would be a statement
# about current that the schematic does not make, and it cannot escape between
# UCC24624 lands anyway: 0.8 mm plus 0.2 mm clearance needs 1.0 mm, the pitch
# leaves 0.67 mm.
POWER_NETS = frozenset({"SEC_A", "SEC_B", "SR_SRC", "PGND", "VOUT"})

STATUS = "LAYOUT_PASS_3_ROUTED_AND_POURED_NOT_RELEASED"

# Why 1.25 mm and not the 0.75 mm the placement study used.  Two facts, one
# geometric and one measured:
#
# A part's own pads are an obstacle for every *other* net, so a land cannot be
# escaped through the gap to its neighbour.  The SOIC-8 land here is 1.95 x
# 0.6 mm on a 1.27 mm pitch, which leaves 0.67 mm of copper-free space between
# neighbouring lands.  A 0.25 mm track with 0.2 mm clearance needs 0.65 mm, and
# the 0.02 mm that remain are a sixth of the router's 0.125 mm grid step, so an
# escape between two lands is not representable at all; 0.8 mm needs 1.2 mm and
# cannot fit by any margin.  Every U1 pin therefore has to leave the package,
# and how much room that needs depends on how close its neighbours sit.
#
# Measured, with the same router and the same order: at 0.75 mm the board stops
# at 117/119 (VG1 at U1.1 and VC2_D at R48/Q43 both fail to escape, after 383 s
# of rip-up churn); at 1.25 mm it reaches 119/119 in 65 s.  This is a routing
# requirement, not a preference, and it is recorded as a measurement rather than
# derived because the escape corridor is decided by the neighbours that land
# there, not by the package outline alone.

# The board is one part table and one report.  Placement intent is expressed as
# blocks, not as a flat coordinate list: a block is a region of the board that a
# reviewer can check against the schematic page.
BLOCKS: dict[str, tuple[float, float, float, float]] = {
    "bias": (10.0, 4.0, 86.0, 30.0),        # bench bias in, VDD domain, controller
    "sense": (90.0, 4.0, 128.0, 30.0),      # VD sense links and FORCE jumpers
    "power": (10.0, 34.0, 100.0, 78.0),     # secondary in, SR pair, shunt, output
    "fault": (104.0, 34.0, 128.0, 78.0),    # fault input, crowbar, optional clamps
    "probe": (8.0, 80.0, 124.0, 88.0),      # the twenty test points, one row
}

# Parts whose position *is* the design: terminals on edges, the SR pair between
# the secondary terminal and the shunt, the shunt before the return.
#
# Every part is at 0 deg.  kicad-cli 10.0.6 reports ANY rotated footprint as
# ``lib_footprint_mismatch`` -- a library footprint copied byte for byte and
# given nothing but ``(at x y 90)`` is flagged, so this is a tool property, not
# an embedding bug.  Rotating a part to dodge it would trade a real layout for a
# suppressed warning, so the placement keeps every part upright and the guard in
# ``placement()`` enforces it.
FIXED: dict[str, tuple[float, float, float]] = {
    "J1": (17.5, 12.0, 0.0),
    "J3": (18.0, 46.0, 0.0),
    "J2": (121.0, 46.0, 0.0),
    "Q1": (48.0, 38.0, 0.0),
    "Q2": (48.0, 62.0, 0.0),
    "Rsh1": (66.0, 50.0, 0.0),
    "R1": (74.0, 50.0, 0.0),
    "J4": (124.0, 70.0, 0.0),
}

BLOCK_ORDER: dict[str, list[str]] = {
    "bias": ["F1", "D1", "D2", "C1", "C2", "C3", "C4", "C5", "JP1", "U1"],
    "sense": ["R2", "R3", "R5", "R6", "JP2", "JP3"],
    "power": ["Rg1", "Rgs1", "CGL1", "Rg2", "Rgs2", "CGL2",
              "Rsn1", "Csn1", "Rsn2", "Csn2", "C6", "C7"],
    "fault": ["R40", "D40", "R41", "C40", "Q40", "R42", "R43", "Q41", "R44",
              "R45", "Q42", "R47", "R46", "Q43", "R48"],
    "probe": [f"TP{i}" for i in range(1, 21)],
}

# Parts that must stay next to each other, because they form one loop rather
# than two nodes.  A snubber is the loop the two parts and their leads make, so
# the resistor and its capacitor are placed by proximity to each other instead
# of by the row-major fill that packs the rest of the block.  Each cluster is
# packed as one unit, largest part first.
CLUSTERS: tuple[tuple[str, ...], ...] = (
    ("Csn1", "Rsn1"),
    ("Csn2", "Rsn2"),
)

MOUNTING_HOLES = ((6.0, 6.0), (126.0, 6.0), (6.0, 86.0), (126.0, 86.0))


@dataclass(frozen=True)
class Pour:
    """One copper region, as an outline only.

    The fill is not part of this record.  It is computed by
    ``kicad-cli pcb drc --refill-zones`` at check time, so the committed file
    describes the *design* and not one KiCad version's fill algorithm.
    """

    net: str
    layer: str
    priority: int
    outline: tuple[tuple[float, float], ...]
    why: str
    # Blocked for every other net rather than merely charged; see
    # ``router.Router._zone_barrier``.  Only the band needs it: it is the one
    # pour with no pad of its own inside the outline (``fill.json`` reports
    # 0/0), so its survival depends on whatever tracks happen to run in it,
    # and a single foreign crossing costs the whole middle of the band.
    barrier: bool = False


# Why pours at all.  At 1 oz copper and a 10 degC rise the IPC-2221 chart puts
# 10 A at about 7 mm of track, and half of it (the two secondary halves) at
# about 3.7 mm.  The router's widest legal track is 0.8 mm, so no track width
# this board can represent is a 10 A conductor.
#
# Adding the pours was necessary and, on its own, not sufficient.  Drawn after
# a routing that crossed them, every crossing track slit an outline and
# ``island_removal_mode 0`` deleted the parts that reached no pad: measured,
# 2.5 %-65 % of each outline survived (fill.json) and the two secondary
# corridors did not even contain the lands they serve.  The fix is routing, not
# more copper: ``keep_clear()`` hands the outlines to the router as pressure and
# ``barrier_nets()`` hands the output band to it as a wall, and the fills went
# to 75 %-98 % as one patch each.  Ampacity itself is still unquoted: see
# ``power_path`` and ``remaining_work``.
#
# Shapes and layers, read off the placement:
#
# * PGND is the return plane, so it takes B.Cu over the whole power region.
#   Its pads run from y 4.7 (bias) to y 72.5 (J4), but the current that matters
#   leaves Rsh1.2 (69.0, 50) and J2.2 (126, 46); the plane is over the power
#   block, and the bias-side pads are joined by tracks.
# * VOUT is the long run from the centre tap J3.2 (23, 46) to the output
#   terminal J2.1 (121, 46).  It goes to B.Cu as a band with priority above
#   PGND, so the plane yields around it; on F.Cu it would cut the SR_SRC
#   cross in half.  The band's body sits at y 40-45.5 and only its lower edge
#   meets the two terminal lands: a band centred on y 46 would be slit in two
#   by the PGND pin J3.4 at x 33, leaving two 1.4 mm strips where the current
#   path should be 6 mm.
# * SEC_A runs up from J3.1 (18, 46) and SEC_B down from J3.3 (28, 46) as two
#   corridors that stop at x 43, one millimetre short of the SR columns.  They
#   stop there because they have to: Q1's source and gate lands end at
#   x 45.73 and its drain land starts at x 46.87, a 1.14 mm gap, so SEC_A and
#   SR_SRC interleave with nothing between them -- a pour over one carves the
#   other and there is no width left to carve.  The last few millimetres to the
#   drain lands stay a track, and the pour carries the corridor.
#
#   The first attempt at SEC_B was (24, 51)-(43, 66), placed by eye above the
#   J3 row's y 46 and left of the SR column.  It contained no SEC_B pad at
#   all -- J3.3 is at y 46 and the Q2 drain land starts at x 46.87 -- so the
#   whole fill was orphaned copper: DRC reported 7 ``isolated_copper``
#   warnings, all on that one zone.  The outlines now overlap the terminal
#   lands they are named for (SEC_A up to y 45.5, SEC_B from y 46, against
#   J3.1/J3.3 spanning y 44.6-47.4).  Note that fill.json counts a pad as "in"
#   a pour only when its centre is inside the outline: SEC_A therefore reports
#   no pad at all even though the fill overlaps the J3.1 land, and SEC_B
#   reports just J3.3, whose centre sits exactly on the outline edge.  The
#   connectivity verdict is the refilled DRC's, not this count.
# * SR_SRC is a cross: the Q1/Q2 source column (x 44-48, y 33-66) joined to
#   the shunt Rsh1.1 (63, 50) by the y 46-54 arm.  Its left edge is x 44,
#   one millimetre clear of the corridors' x 43, and it stays inside the
#   power block in y so it never reaches the fault block.
#
# Priorities are only load-bearing where two zones would overlap on one layer:
# VOUT over PGND on B.Cu.  Everything else is disjoint by construction.
POURS: tuple[Pour, ...] = (
    Pour("PGND", "B.Cu", 0,
         ((12.0, 32.0), (128.0, 32.0), (128.0, 78.0), (12.0, 78.0)),
         "return plane; carries the SR and shunt current back to J3.4/J2.2"),
    Pour("VOUT", "B.Cu", 2,
         ((20.0, 40.0), (122.0, 40.0), (122.0, 45.5), (20.0, 45.5)),
         "centre tap to output terminal along the J3/J2 row; its lower edge "
         "meets the pads and its body passes above the J3.4 return pin",
         barrier=True),
    Pour("SEC_A", "F.Cu", 1,
         ((15.0, 33.0), (43.0, 33.0), (43.0, 45.5), (15.0, 45.5)),
         "corridor from J3.1 up to the Q1 drain; stops 1 mm short of SR_SRC, "
         "which the drain lands interleave"),
    Pour("SEC_B", "F.Cu", 1,
         ((25.0, 46.0), (43.0, 46.0), (43.0, 66.0), (25.0, 66.0)),
         "corridor from J3.3 down to the Q2 drain; starts at the J3 row so it "
         "actually contains its pad"),
    Pour("SR_SRC", "F.Cu", 1,
         ((44.0, 33.0), (48.0, 33.0), (48.0, 46.0), (67.0, 46.0),
          (67.0, 54.0), (48.0, 54.0), (48.0, 66.0), (44.0, 66.0)),
         "both source columns to the shunt; the cross keeps it off SEC_A/B"),
)


def uid(*parts: str) -> str:
    return str(uuid.uuid5(NS, "/".join(parts)))


def _natural(ref: str) -> tuple:
    """Sort R2 < R10, and TP1 < TP2 < TP10, instead of lexicographic order."""
    return tuple(int(p) if p.isdigit() else p for p in re.split(r"(\d+)", ref))


# ---------------------------------------------------------------- part table
@dataclass(frozen=True)
class Placed:
    ref: str
    value: str
    footprint: str
    block: str
    x: float
    y: float
    rot: float
    bounds: tuple[float, float, float, float]      # local courtyard, unrotated

    @property
    def rect(self) -> tuple[float, float, float, float]:
        x0, y0, x1, y1 = self.bounds
        return (self.x + x0, self.y + y0, self.x + x1, self.y + y1)

    @property
    def w_mm(self) -> float:
        return self.bounds[2] - self.bounds[0]

    @property
    def d_mm(self) -> float:
        return self.bounds[3] - self.bounds[1]


def pad_numbers(lib_id: str) -> list[str]:
    """Numbered pads of a footprint, duplicates kept (order as drawn)."""
    return [m.group(1) for m in re.finditer(r'\(pad "([^"]*)"', _source(lib_id))
            if m.group(1)]


def pad_pin_mapping(table: dict) -> dict:
    """Symbol pins that have no pad of their own, per part.

    A vendored generic footprint can carry the right nets and still leave a
    symbol pin without a land -- the ``Infineon_PG-TDSON-8`` numbers all five
    drain lands "5", so pins 6-8 of the real BSC010N04LS6 pinout had none.  This
    field makes that gap visible rather than rounding it to "mapping complete";
    it is empty only while every part's footprint really covers all its pins.
    """
    out: dict[str, list[str]] = {}
    for ref, part in sorted(table.items(), key=lambda kv: _natural(kv[0])):
        pads = set(pad_numbers(part.footprint))
        missing = sorted(set(part.nets) - pads, key=_natural)
        if missing:
            out[ref] = missing
    return out


def stock_path(lib_id: str) -> Path:
    lib, name = lib_id.split(":", 1)
    return STOCK / f"{lib}.pretty" / f"{name}.kicad_mod"


def stock_text(lib_id: str) -> str:
    path = stock_path(lib_id)
    if not path.is_file():
        raise SystemExit(
            f"{lib_id} is not vendored at {path}.  Copy it out of a KiCad install "
            f"into {STOCK} and record version, sha256 and licence in PROVENANCE.md; "
            f"never point the generator at somebody's home directory.")
    return path.read_text(encoding="utf-8")


def courtyard_bounds(text: str) -> tuple[float, float, float, float]:
    """Local courtyard box ``(x0, y0, x1, y1)`` of a footprint, or a hard error.

    The box is NOT necessarily centred on the origin -- the MX126 terminal block
    runs from -3.5 to +8 in x -- so callers must translate the whole box, never
    a width around the origin.  A footprint without a courtyard is exempt from
    every clearance question, so a missing one is an error, not a default.
    """
    xs: list[float] = []
    ys: list[float] = []
    num = r"(-?\d+(?:\.\d+)?)"
    for m in re.finditer(r"\(fp_(rect|line|circle|poly)\b", text):
        block = text[m.start():sch.block_end(text, m.start())]
        if '(layer "F.CrtYd")' not in block:
            continue
        kind = m.group(1)
        if kind in ("rect", "line"):
            for key in ("start", "end"):
                pair = re.search(rf"\({key} {num} {num}\)", block)
                if pair is None:
                    raise SystemExit(f"an fp_{kind} courtyard has no {key} point")
                xs.append(float(pair.group(1)))
                ys.append(float(pair.group(2)))
        elif kind == "circle":
            center = re.search(rf"\(center {num} {num}\)", block)
            edge = re.search(rf"\(end {num} {num}\)", block)
            if center is None or edge is None:
                raise SystemExit("an fp_circle courtyard has no center/end point")
            cx, cy = float(center.group(1)), float(center.group(2))
            r = ((float(edge.group(1)) - cx) ** 2 + (float(edge.group(2)) - cy) ** 2) ** 0.5
            xs += [cx - r, cx + r]
            ys += [cy - r, cy + r]
        else:
            pts = re.search(r"\(pts\b", block)
            if pts is None:
                raise SystemExit("an fp_poly courtyard has no pts block")
            body = block[pts.start():sch.block_end(block, pts.start())]
            pairs = [(float(a), float(b)) for a, b in
                     re.findall(rf"\(xy {num} {num}\)", body)]
            if not pairs:
                raise SystemExit("an fp_poly courtyard has no vertices")
            xs += [x for x, _ in pairs]
            ys += [y for _, y in pairs]
    if not xs:
        raise SystemExit("a footprint has no F.CrtYd drawing; DRC would exempt it "
                         "from every clearance check")
    return min(xs), min(ys), max(xs), max(ys)


def mounting_hole_source(hide_reference: bool = False) -> str:
    """The M3 hole as a library footprint, so the board can reference it by name.

    Keeping it in a real ``dcx.pretty`` is what lets KiCad's DRC resolve the
    footprint; an inline definition is reported as an unknown library.

    ``hide_reference`` matches what the official KiCad mounting holes do.  The
    label sits 4.9 mm above the hole, so on a board whose holes are 5 mm from
    the edge it lands outside the outline and DRC reports
    ``silk_edge_clearance``.  It stays visible by default because the SR board
    has the room and its committed board must not change.
    """
    r = HOLE_COURTYARD_R_MM
    hide = "\t\t(hide yes)\n" if hide_reference else ""
    return (
        f'(footprint "MountingHole_3.2mm_M3"\n'
        f'\t(version 20260206)\n\t(generator "make_sr_fault_board_pcb")\n'
        f'\t(generator_version "10.0")\n\t(layer "F.Cu")\n'
        f'\t(descr "M3 mounting hole, 3.2 mm drill, no copper")\n'
        f'\t(attr exclude_from_pos_files exclude_from_bom)\n'
        f'\t(property "Reference" "REF**"\n'
        f'\t\t(at 0 -{r + 1.2:g} 0)\n\t\t(layer "F.SilkS")\n'
        f'{hide}'
        f'\t\t(uuid "{uid("h", "ref")}")\n'
        f'\t\t(effects (font (size 1 1) (thickness 0.15)))\n\t)\n'
        f'\t(property "Value" "MountingHole_3.2mm_M3"\n'
        f'\t\t(at 0 {r + 1:g} 0)\n\t\t(layer "F.Fab")\n'
        f'\t\t(uuid "{uid("h", "val")}")\n'
        f'\t\t(effects (font (size 1 1) (thickness 0.15)))\n\t)\n'
        f'\t(fp_circle (center 0 0) (end {r:g} 0) (stroke (width 0.05) (type solid))'
        f' (fill none) (layer "F.CrtYd") (uuid "{uid("h", "crt")}"))\n'
        f'\t(fp_circle (center 0 0) (end 3.2 0) (stroke (width 0.1) (type solid))'
        f' (fill none) (layer "F.Fab") (uuid "{uid("h", "fab")}"))\n'
        f'\t(pad "" np_thru_hole circle (at 0 0) (size 3.2 3.2) (drill 3.2)'
        f' (layers "*.Cu" "*.Mask") (uuid "{uid("h", "pad")}"))\n'
        f'\t(embedded_fonts no)\n)\n'
    )


def bsc_land() -> dict:
    """The digitised BSC010N04LS6 land pattern, checked before it is trusted.

    Reading the committed JSON rather than transcribing numbers into this
    module is what keeps a re-digitisation and its consumer from drifting
    apart, and it keeps the provenance (page, fitted scale, residuals) attached
    to the copper that came out of it.
    """
    if not BSC_LAND_JSON.is_file():
        raise SystemExit(f"{BSC_LAND_JSON} is missing: run "
                         f"tools/bsc010n04ls6_land.py --write")
    with BSC_LAND_JSON.open(encoding="utf-8") as fh:
        data = json.load(fh)
    failed = sorted(k for k, ok in data["checks"].items() if not ok)
    if failed:
        raise SystemExit(f"{BSC_LAND_JSON} fails its own checks: {failed}")
    return data


def bsc_source() -> str:
    """BSC010N04LS6 lands as a library footprint without a gap in the pin map.

    The vendored ``Infineon_PG-TDSON-8`` numbers all five drain lands "5", while
    the schematic models the real pinout, whose drain is pins 5-8: three symbol
    pins therefore had no pad.  Here the datasheet's four drain fingers are pads
    5/6/7/8 on a common base, each overlapping the base by 0.125 mm so KiCad sees
    one continuous land, and the source bar repeats 1/2/3 the same way.

    Copper, mask and stencil are three separate layers of the drawing, so they
    are three separate kinds of pad: copper pads carry only ``F.Cu``, mask pads
    only ``F.Mask``, stencil openings only ``F.Paste``.  Letting a copper pad
    imply its own mask opening would replace the drawn 0.05 mm expansion with
    the land outline, and imply a stencil equal to the land.

    Silkscreen, the F.Fab body outline and the 3D model are carried over from
    the vendored footprint unchanged -- they are not on the board-pads figure,
    and the model belongs to the same body rather than to these lands.
    """
    land = bsc_land()
    worst_um = max(land["results"]["residuals_mm"].values()) * 1000
    out = [
        '(footprint "BSC010N04LS6"\n'
        '\t(version 20260206)\n\t(generator "make_sr_fault_board_pcb")\n'
        '\t(generator_version "10.0")\n\t(layer "F.Cu")\n'
        f'\t(descr "Infineon PG-TDSON-8-FL, 6.15x5.15 mm.  Lands digitised from the '
        f'BSC010N04LS6 datasheet Fig. 2 (scale {land["scale"]["mm_per_pt"]:.6f} mm/pt, '
        f'max residual {worst_um:.1f} um, source sha256 {land["source"]["sha256"]}).  '
        f'Drain 5-8 on a common base, source 1-3 on a common bar.")\n'
        '\t(attr smd)\n'
        '\t(duplicate_pad_numbers_are_jumpers no)\n'
        '\t(property "Reference" "REF**"\n'
        '\t\t(at 0 -3.9 0)\n\t\t(layer "F.SilkS")\n'
        f'\t\t(uuid "{uid("bsc", "ref")}")\n'
        '\t\t(effects (font (size 1 1) (thickness 0.15)))\n\t)\n'
        '\t(property "Value" "BSC010N04LS6"\n'
        '\t\t(at 0 3.9 0)\n\t\t(layer "F.Fab")\n'
        f'\t\t(uuid "{uid("bsc", "val")}")\n'
        '\t\t(effects (font (size 1 1) (thickness 0.15)))\n\t)\n'
    ]
    # Silkscreen: body edges and the pin-1 wedge, untouched from the vendored
    # footprint because the board-pads figure does not draw them.
    for i, (start, end) in enumerate((
            ((3.005, -2.685), (-2.995, -2.685)),
            ((3.005, 2.64), (-2.995, 2.64)))):
        out.append(f'\t(fp_line\n\t\t(start {start[0]:g} {start[1]:g})\n'
                   f'\t\t(end {end[0]:g} {end[1]:g})\n'
                   '\t\t(stroke (width 0.12) (type solid))\n'
                   f'\t\t(layer "F.SilkS")\n\t\t(uuid "{uid("bsc", "silk", str(i))}")\n\t)\n')
    out.append('\t(fp_poly\n\t\t(pts (xy -3.681827 -1.91) (xy -4.011827 -1.67) '
               '(xy -4.011827 -2.15) (xy -3.681827 -1.91))\n'
               '\t\t(stroke (width 0.12) (type solid))\n\t\t(fill yes)\n'
               f'\t\t(layer "F.SilkS")\n\t\t(uuid "{uid("bsc", "pin1")}")\n\t)\n')
    # F.Fab: the body with its chamfered pin-1 corner, also carried over.
    for i, (start, end) in enumerate((
            ((-3.035, -1.57), (-3.04, 2.56)),
            ((-2.045, -2.575), (-3.045, -1.575)),
            ((-2.04, -2.58), (3.11, -2.58)),
            ((3.11, -2.58), (3.11, 2.57)),
            ((3.11, 2.57), (-3.04, 2.57)))):
        out.append(f'\t(fp_line\n\t\t(start {start[0]:g} {start[1]:g})\n'
                   f'\t\t(end {end[0]:g} {end[1]:g})\n'
                   f'\t\t(stroke (width 0.1) (type solid))\n'
                   f'\t\t(layer "F.Fab")\n\t\t(uuid "{uid("bsc", "fab", str(i))}")\n\t)\n')
    out.append('\t(fp_text user "${REFERENCE}"\n\t\t(at -1.9 0.05 90)\n'
               '\t\t(layer "F.Fab")\n'
               f'\t\t(uuid "{uid("bsc", "fabref")}")\n'
               '\t\t(effects (font (size 1 1) (thickness 0.15)))\n\t)\n')
    # Courtyard: the digitised box, closed.  A courtyard that is not closed is
    # the same as no courtyard, and DRC would then exempt the part.
    x0, y0, x1, y1 = land["courtyard"]
    for i, (start, end) in enumerate((
            ((x0, y0), (x1, y0)), ((x0, y0), (x0, y1)),
            ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)))):
        out.append(f'\t(fp_line\n\t\t(start {start[0]:g} {start[1]:g})\n'
                   f'\t\t(end {end[0]:g} {end[1]:g})\n'
                   f'\t\t(stroke (width 0.05) (type solid))\n'
                   f'\t\t(layer "F.CrtYd")\n\t\t(uuid "{uid("bsc", "crt", str(i))}")\n\t)\n')
    # Pads, straight out of the measurement: number, layers and rectangle.
    for i, pad in enumerate(land["pads"]):
        px0, py0, px1, py1 = pad["rect"]
        layers = " ".join(f'"{name}"' for name in pad["layers"])
        out.append(f'\t(pad "{pad["number"]}" smd rect\n'
                   f'\t\t(at {(px0 + px1) / 2:.4f} {(py0 + py1) / 2:.4f})\n'
                   f'\t\t(size {px1 - px0:.4f} {py1 - py0:.4f})\n'
                   f'\t\t(layers {layers})\n'
                   f'\t\t(uuid "{uid("bsc", "pad", str(i))}")\n\t)\n')
    out.append('\t(model "${KICAD10_3DMODEL_DIR}/Package_SON.3dshapes/'
               'Infineon_PG-TDSON-8_6.15x5.15mm.step"\n'
               '\t\t(offset (xyz 0 0 0))\n\t\t(scale (xyz 1 1 1))\n'
               '\t\t(rotate (xyz 0 0 0))\n\t)\n'
               '\t(embedded_fonts no)\n)\n')
    return "".join(out)


def _source(lib_id: str) -> str:
    if lib_id == HOLE_LIB_ID:
        return mounting_hole_source()
    if lib_id == BSC_LIB_ID:
        return bsc_source()
    return stock_text(lib_id)


def bounds(lib_id: str) -> tuple[float, float, float, float]:
    """Local courtyard box of a footprint, relative to its own origin.

    The box is carried whole rather than as a width/depth pair because KiCad
    does not promise that a courtyard is centred on the origin: the MX126
    terminal block runs from -3.5 to +8 mm in x.  A width-only model silently
    shifts such a part by (x0 + x1)/2 -- 2.25 mm for that terminal block, which
    is wider than the gap it was supposed to keep.
    """
    return courtyard_bounds(_source(lib_id))


# ---------------------------------------------------------------- placement
def _overlaps(a: tuple[float, float, float, float], b: tuple[float, float, float, float],
              gap: float = 0.0) -> bool:
    return not (a[2] + gap <= b[0] or b[2] + gap <= a[0]
                or a[3] + gap <= b[1] or b[3] + gap <= a[1])


def _rect(x: float, y: float, w: float, d: float) -> tuple[float, float, float, float]:
    return (x - w / 2, y - d / 2, x + w / 2, y + d / 2)


def _first_fit(block: tuple[float, float, float, float],
               box: tuple[float, float, float, float],
               obstacles: list[tuple[float, float, float, float]]) -> tuple[float, float]:
    """Row-major scan of a block for the first origin whose courtyard clears everything.

    The scan variable is the footprint *origin*, and the test rectangle is
    ``origin + local box``.  Scanning the origin as if the box were centred on
    it is the mistake this signature exists to prevent.
    """
    bx0, by0, bx1, by1 = block
    lx0, ly0, lx1, ly1 = box
    y = by0 - ly0
    while y + ly1 <= by1 + 1e-9:
        x = bx0 - lx0
        while x + lx1 <= bx1 + 1e-9:
            if not any(_overlaps((x + lx0, y + ly0, x + lx1, y + ly1), o, GAP_MM)
                       for o in obstacles):
                return x, y
            x += GRID_MM
        y += GRID_MM
    raise SystemExit(f"block {block} is too small for a "
                     f"{lx1 - lx0:.2f} x {ly1 - ly0:.2f} mm courtyard whose origin "
                     f"is the point ({lx0:.2f}, {ly0:.2f}) inside it")


def _first_fit_near(anchor: tuple[float, float, float, float],
                    box: tuple[float, float, float, float],
                    obstacles: list[tuple[float, float, float, float]],
                    reach: float = 6.0) -> tuple[float, float]:
    """The nearest free origin whose courtyard clears everything, near ``anchor``.

    Parts in one loop have to land next to each other.  A snubber capacitor
    twenty-eight millimetres from its resistor is not a snubber: the loop it
    is meant to damp is the one the lead length adds.  Row-major first-fit
    cannot express that -- it fills the row it is on -- so clustered parts are
    placed by proximity instead, and the cluster is the unit that gets packed.
    """
    lx0, ly0, lx1, ly1 = box
    ax = (anchor[0] + anchor[2]) / 2.0
    ay = (anchor[1] + anchor[3]) / 2.0
    best: tuple[float, float, float] | None = None
    y = ay - reach - ly1
    while y + ly1 <= ay + reach:
        x = ax - reach - lx1
        while x + lx1 <= ax + reach:
            if not any(_overlaps((x + lx0, y + ly0, x + lx1, y + ly1), o, GAP_MM)
                       for o in obstacles):
                d = math.hypot((x + lx0 + x + lx1) / 2.0 - ax,
                               (y + ly0 + y + ly1) / 2.0 - ay)
                if best is None or d < best[0]:
                    best = (d, x, y)
            x += GRID_MM
        y += GRID_MM
    if best is None:
        raise SystemExit(f"no room within {reach:g} mm of {anchor} for a "
                         f"{lx1 - lx0:.2f} x {ly1 - ly0:.2f} mm courtyard")
    return best[1], best[2]


def _units(block: str, refs: list[str]) -> list[list[str]]:
    """``refs`` grouped into placement units: each declared cluster, then singletons."""
    grouped: set[str] = set()
    units: list[list[str]] = []
    for cluster in CLUSTERS:
        inside = [r for r in cluster if r in refs]
        if not inside:
            continue
        if len(inside) != len(cluster):
            raise SystemExit(f"cluster {cluster} is split across blocks")
        units.append(inside)
        grouped.update(inside)
    units.extend([r] for r in refs if r not in grouped)
    return units


def _assignment(table: list) -> dict[str, str]:
    """ref -> block, and a guard that every part lands in exactly one block."""
    seen: dict[str, str] = {}
    for block, refs in BLOCK_ORDER.items():
        for ref in refs:
            if ref in seen:
                raise SystemExit(f"{ref} appears in two blocks: {seen[ref]} and {block}")
            seen[ref] = block
    shared = [ref for ref in seen if ref in FIXED]
    if shared:
        raise SystemExit(f"{shared} are both packed and fixed")
    table_refs = {p.ref for p in table}
    absent = sorted(table_refs - set(seen) - set(FIXED))
    if absent:
        raise SystemExit(f"these parts have a footprint but no block: {absent}")
    extra = sorted(set(seen) - table_refs)
    if extra:
        raise SystemExit(f"these block entries have no part: {extra}")
    return seen


def _hole_rects() -> list[tuple[float, float, float, float]]:
    size = 2 * HOLE_COURTYARD_R_MM
    return [_rect(x, y, size, size) for x, y in MOUNTING_HOLES]


def placement() -> list[Placed]:
    """Deterministic packing: fixed parts first, then largest-first per block."""
    table = [p for p in sch.parts() if p.footprint]
    by_ref = {p.ref: p for p in table}
    missing = sorted(set(FIXED) - set(by_ref))
    if missing:
        raise SystemExit(f"fixed refs not in the part table: {missing}")
    for ref, (_, _, rot) in FIXED.items():
        if rot % 360 != 0:
            raise SystemExit(
                f"{ref} is placed at {rot:g} deg.  kicad-cli 10.0.6 reports any "
                f"rotated footprint as lib_footprint_mismatch, and this generator "
                f"refuses to rotate a part just to keep a warning quiet.  Either "
                f"place it upright or fix the DRC finding itself.")
    block_of = _assignment(table)

    placed: list[Placed] = []
    obstacles = _hole_rects()
    for ref in sorted(FIXED, key=_natural):
        x, y, rot = FIXED[ref]
        part = by_ref[ref]
        box = bounds(part.footprint)
        item = Placed(ref, part.value, part.footprint, "fixed", x, y, rot, box)
        placed.append(item)
        obstacles.append(item.rect)

    def area(ref: str) -> float:
        x0, y0, x1, y1 = bounds(by_ref[ref].footprint)
        return (x1 - x0) * (y1 - y0)

    for block, refs in BLOCK_ORDER.items():
        units = sorted(_units(block, refs),
                       key=lambda u: (-sum(area(r) for r in u), min(_natural(r) for r in u)))
        for unit in units:
            anchor: tuple[float, float, float, float] | None = None
            for ref in sorted(unit, key=lambda r: (-area(r), _natural(r))):
                part = by_ref[ref]
                box = bounds(part.footprint)
                if anchor is None:
                    x, y = _first_fit(BLOCKS[block], box, obstacles)
                else:
                    x, y = _first_fit_near(anchor, box, obstacles)
                item = Placed(ref, part.value, part.footprint, block, x, y, 0.0, box)
                placed.append(item)
                obstacles.append(item.rect)
                anchor = item.rect

    refs = [p.ref for p in placed]
    if len(refs) != len(set(refs)):
        raise SystemExit("a part was placed twice")
    if set(refs) != set(by_ref):
        raise SystemExit(f"unplaced: {sorted(set(by_ref) - set(refs))}")
    if set(block_of) - set(refs):
        raise SystemExit("block assignment and placement disagree")
    return sorted(placed, key=lambda p: _natural(p.ref))


# ---------------------------------------------------------------- board file
def net_table(parts: list) -> list[str]:
    names = sorted({n for p in parts for n in p.nets.values() if n != sch.NC})
    return [""] + names


def inject_nets(text: str, nets: dict[str, int], names: list[str]) -> str:
    """Give each numbered pad of one footprint its schematic net.

    Library footprints carry no ``(net ...)``; a board that keeps them netless is
    a drawing, not a layout.  Pads with an empty number (mask/paste only) stay
    netless on purpose.
    """
    out: list[str] = []
    i = 0
    while True:
        j = text.find("(pad ", i)
        if j < 0:
            out.append(text[i:])
            break
        out.append(text[i:j])
        end = sch.block_end(text, j)
        block = text[j:end]
        match = re.match(r'\(pad "([^"]*)"', block)
        number = match.group(1)
        if number in nets:
            idx = nets[number]
            nl = block.find("\n")
            cut = nl + 1 if nl >= 0 else match.end()
            block = block[:cut] + f'\n\t\t(net {idx} "{names[idx]}")\n' + block[cut:]
        out.append(block)
        i = end
    return "".join(out)


def _embed(text: str, lib_id: str, ref: str, value: str, nets: dict[str, int],
           names: list[str], x: float, y: float, rot: float,
           dnp: bool = False) -> str:
    """Copy a footprint into the board, placed and netted.

    Same four substitutions as the A5 placement generator (library id,
    placement, reference, every uuid), plus the pad nets.  Two instances sharing
    a uuid make KiCad pick one at random, so every uuid is derived from the ref.

    ``dnp`` writes the footprint's ``dnp`` attribute.  It is what
    ``kicad-cli pcb export pos --exclude-dnp`` reads; a part the part table
    calls "do not populate" but the board file does not mark is placed anyway,
    and the position CSV is the file a machine follows.
    """
    text = re.sub(r"\(version [^)]*\)\s*", "", text, count=1)
    text = re.sub(r'\(generator "[^"]*"\)\s*', "", text, count=1)
    text = re.sub(r'\(generator_version "[^"]*"\)\s*', "", text, count=1)
    text = re.sub(r'\(footprint "[^"]+"', f'(footprint "{lib_id}"', text, count=1)
    text = inject_nets(text, nets, names)
    text = text.replace(
        '(layer "F.Cu")',
        f'(layer "F.Cu")\n\t(uuid "{uid("fp", ref)}")\n\t(at {x:g} {y:g} {rot:g})',
        1)
    text = text.replace('(property "Reference" "REF**"', f'(property "Reference" "{ref}"', 1)
    shift = REFERENCE_TEXT_SHIFT_MM.get(ref)
    if shift:
        text = re.sub(
            r'(\(property "Reference" "' + re.escape(ref) +
            r'"\s*\(at )(-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?)',
            lambda m: (f"{m.group(1)}{float(m.group(2)) + shift[0]:g} "
                       f"{float(m.group(3)) + shift[1]:g}"),
            text, count=1)
    text = re.sub(r'\(property "Value" "[^"]*"', f'(property "Value" "{value}"', text, count=1)
    text = re.sub(r'\(uuid "([^"]+)"\)', lambda m: f'(uuid "{uid(ref, m.group(1))}")', text)
    if dnp:
        # The attribute list is the only place KiCad looks: ``(attr smd dnp)``.
        text = re.sub(r"\(attr ([^)\n]*)\)", r"(attr \1 dnp)", text, count=1)
    return "\t" + text.strip() + "\n"


# ---------------------------------------------------------------- routing
def _table() -> dict:
    return {p.ref: p for p in sch.parts() if p.footprint}


def pads_of(placed: list[Placed]) -> list[router.Pad]:
    """Every copper pad, carrying the same net index the board file will give it."""
    table = _table()
    index = {name: i for i, name in enumerate(net_table(list(table.values())))}
    pads: list[router.Pad] = []
    for p in placed:
        nets = {num: index[name] for num, name in table[p.ref].nets.items()
                if name != sch.NC}
        pads.extend(router.extract_pads(
            _source(p.footprint), p.ref, p.x, p.y,
            lambda ref, number, m=nets: m.get(number, -1)))
    return pads


def route_plan(pads: list[router.Pad], names: list[str]) -> tuple[dict[int, float], list[int]]:
    """Per-net widths and the order nets are routed in.

    Power first, then the nets with the most pads.  The order is a design
    choice and a load-bearing one: a net routed late can only be blocked by
    what came before, so the nets with no alternative path take the shortest
    routes available.
    """
    groups: dict[int, list[router.Pad]] = {}
    for pad in pads:
        if pad.net >= 0:
            groups.setdefault(pad.net, []).append(pad)
    widths = {net: ROUTE_POWER_MM if names[net] in POWER_NETS else ROUTE_SIGNAL_MM
              for net in groups}
    order = sorted((net for net, g in groups.items() if len(g) > 1),
                   key=lambda net: (names[net] not in POWER_NETS, -len(groups[net]),
                                    names[net]))
    return widths, order


def keep_clear(names: list[str]) -> dict[int, list[tuple[list[tuple[float, float]], int, int]]]:
    """The pour corridors, as route pressure: every other net pays to cross one.

    Measured before this existed, the fills kept 2.5 %-65.2 % of their outlines
    even though 67 %-87 % of the outline area was clear of foreign copper.  The
    difference is island removal: ``island_removal_mode 0`` deletes any fill that
    reaches no pad of its net, and a single 0.25 mm signal crossing a corridor
    is enough to cut off the rest of it.  Routing the signals around, or onto the
    other layer, is what turns the corridor back into a conductor.

    The priority travels with the outline: the VOUT band and the PGND plane
    overlap on B.Cu, and only the higher-priority zone fills there.
    """
    index = {name: i for i, name in enumerate(names)}
    out: dict[int, list[tuple[list[tuple[float, float]], int, int]]] = {0: [], 1: []}
    for pour in POURS:
        layer = 0 if pour.layer == "F.Cu" else 1
        out[layer].append((list(pour.outline), index[pour.net], pour.priority))
    return out


def barrier_nets(names: list[str]) -> frozenset[int]:
    """Pour nets whose corridor copper may not cross; see ``Pour.barrier``."""
    index = {name: i for i, name in enumerate(names)}
    return frozenset(index[p.net] for p in POURS if p.barrier)


@functools.lru_cache(maxsize=4)
def _route_cached(placed: tuple[Placed, ...]) -> router.RouteResult:
    """Routing takes about a minute; ``write()`` and ``report()`` both need it."""
    pads = pads_of(list(placed))
    names = net_table(list(_table().values()))
    widths, order = route_plan(pads, names)
    return router.route(pads, BOARD_W_MM, BOARD_D_MM, list(MOUNTING_HOLES),
                        widths=widths, order=order,
                        keep_clear=keep_clear(names),
                        barrier_nets=barrier_nets(names))


def route(placed: list[Placed] | None = None) -> router.RouteResult:
    return _route_cached(tuple(placed or placement()))


_LAYER_NAME = {0: "F.Cu", 1: "B.Cu"}


def copper_lines(result: router.RouteResult) -> list[str]:
    """The ``(segment ...)`` and ``(via ...)`` records, in route order.

    UUIDs are positional, like every other uuid in this file: they are derived
    from the record's index in a deterministic route, so regenerating from the
    same placement produces the same board byte for byte.
    """
    out = []
    for k, s in enumerate(result.segments):
        out.append(f'\t(segment (start {s.x0:g} {s.y0:g}) (end {s.x1:g} {s.y1:g})'
                   f' (width {s.width:g}) (layer "{_LAYER_NAME[s.layer]}")'
                   f' (net {s.net}) (uuid "{uid("segment", str(k))}"))\n')
    for k, v in enumerate(result.vias):
        out.append(f'\t(via (at {v.x:g} {v.y:g}) (size {v.radius * 2:g})'
                   f' (drill {router.VIA_DRILL_MM:g}) (layers "F.Cu" "B.Cu")'
                   f' (net {v.net}) (uuid "{uid("via", str(k))}"))\n')
    return out


def zone_lines(names: list[str]) -> list[str]:
    """The ``(zone ...)`` records, one per pour, outlines only.

    Two options are not defaults and are stated on purpose:

    * ``connect_pads yes`` is a solid connection, not a thermal relief.  A
      thermal relief needs spokes narrower than the pad, and on the 1 mm test
      points the first experiment produced a ``starved_thermal`` -- a pad the
      fill could not reach at all.  This board is not reflowed by hand at
      hobby temperatures; solid is the connection the current path wants.
    * ``island_removal_mode 0`` prunes fills that touch no pad of their net.
      That is the behaviour KiCad defaults to today, and writing it down keeps
      the fill reproducible: the pours here are large enough to be slit by the
      signal vias and tracks that cross them, so "how much of the outline
      survives" is a real question and not a formatting detail.
    """
    index = {name: i for i, name in enumerate(names)}
    out = []
    for pour in POURS:
        pts = " ".join(f"(xy {x:g} {y:g})" for x, y in pour.outline)
        out.append(
            f'\t(zone (net {index[pour.net]}) (net_name "{pour.net}")'
            f' (layer "{pour.layer}")\n'
            f'\t\t(priority {pour.priority}) (uuid "{uid("zone", pour.net)}")\n'
            '\t\t(hatch edge 0.5)\n'
            '\t\t(connect_pads yes (clearance 0.2))\n'
            '\t\t(min_thickness 0.25)\n'
            '\t\t(filled_areas_thickness no)\n'
            '\t\t(fill yes (thermal_gap 0.5) (thermal_bridge_width 0.5)'
            ' (island_removal_mode 0))\n'
            f'\t\t(polygon (pts {pts}))\n'
            '\t)\n')
    return out


def board_file(placed: list[Placed] | None = None,
               result: router.RouteResult | None = None) -> str:
    placed = placed or placement()
    result = result if result is not None else route(placed)
    table = {p.ref: p for p in sch.parts() if p.footprint}
    names = net_table(list(table.values()))
    index = {name: i for i, name in enumerate(names)}
    w, d = BOARD_W_MM, BOARD_D_MM
    out = [
        "(kicad_pcb\n\t(version 20260206)\n\t(generator \"make_sr_fault_board_pcb\")\n"
        "\t(generator_version \"10.0\")\n"
        f"\t(general (thickness {THICKNESS_MM:g}))\n"
        "\t(paper \"A4\")\n\t(title_block\n"
        "\t\t(title \"DCX 48V-2V - single-pair UCC24624 SR fault-shutdown validation board\")\n"
        "\t\t(comment 1 \"LAYOUT PASS 3 - routed tracks plus power pours (outlines; fill at DRC)\")\n"
        "\t\t(comment 2 \"not a manufacturing package; hardware not built\")\n"
        "\t)\n"
        "\t(layers\n"
        '\t\t(0 "F.Cu" signal)\n\t\t(31 "B.Cu" signal)\n'
        # Paste and mask have to be declared, not just referenced by pads:
        # kicad-cli plots only layers the board's own table lists, and it drops
        # the rest silently (no message, no non-zero exit).  Without these four
        # lines the package came out with five layers while the manifest said
        # nine -- a mask-less board looks perfectly plottable.
        '\t\t(34 "B.Paste" user)\n\t\t(35 "F.Paste" user)\n'
        '\t\t(36 "B.SilkS" user "B.Silkscreen")\n\t\t(37 "F.SilkS" user "F.Silkscreen")\n'
        '\t\t(38 "B.Mask" user)\n\t\t(39 "F.Mask" user)\n'
        '\t\t(44 "Edge.Cuts" user)\n\t\t(46 "B.CrtYd" user "B.Courtyard")\n'
        '\t\t(47 "F.CrtYd" user "F.Courtyard")\n'
        '\t\t(48 "B.Fab" user)\n\t\t(49 "F.Fab" user)\n\t)\n'
        "\t(setup (pad_to_mask_clearance 0))\n"
    ]
    for i, name in enumerate(names):
        out.append(f'\t(net {i} "{name}")\n')
    for name, (x0, y0, x1, y1) in {
        "top": (0, 0, w, 0), "right": (w, 0, w, d),
        "bottom": (w, d, 0, d), "left": (0, d, 0, 0),
    }.items():
        out.append(f'\t(gr_line (start {x0:g} {y0:g}) (end {x1:g} {y1:g})'
                   f' (stroke (width 0.1) (type solid)) (layer "Edge.Cuts")'
                   f' (uuid "{uid("edge", name)}"))\n')
    for i, (x, y) in enumerate(MOUNTING_HOLES, start=1):
        out.append(_embed(mounting_hole_source(), HOLE_LIB_ID, f"H{i}", "MountingHole_3.2mm_M3",
                          {}, names, x, y, 0.0))
    for p in placed:
        part = table[p.ref]
        nets = {num: index[name] for num, name in part.nets.items() if name != sch.NC}
        out.append(_embed(_source(p.footprint), p.footprint, p.ref, p.value,
                          nets, names, p.x, p.y, p.rot, dnp=part.dnp))
    out.extend(copper_lines(result))
    out.extend(zone_lines(names))
    out.append(")\n")
    return "".join(out)


# ---------------------------------------------------------------- project files
def fp_lib_table() -> str:
    """Point the project at the vendored libraries.

    Same trap as the placement board and the schematic: without this table (and
    the ``.kicad_pro`` beside it) ``kicad-cli`` reports every stock footprint as
    an unknown library, and an unresolved footprint is exempt from the courtyard
    checks DRC is supposed to run here.
    """
    libs = sorted({p.split(":", 1)[0] for p in _used_footprints()} - {"dcx"})
    rows = "".join(
        f'  (lib (name "{lib}")(type "KiCad")'
        f'(uri "${{KIPRJMOD}}/../../hardware/stock_footprints/{lib}.pretty")'
        f'(options "")(descr "vendored KiCad 10.0.6 footprint"))\n'
        for lib in libs)
    rows += ('  (lib (name "dcx")(type "KiCad")(uri "${KIPRJMOD}/dcx.pretty")'
             '(options "")(descr "generated footprints: mounting holes, and the '
             'BSC010N04LS6 land digitised from its datasheet"))\n')
    return f'(fp_lib_table\n  (version 7)\n{rows})\n'


def _used_footprints() -> list[str]:
    return [p.footprint for p in sch.parts() if p.footprint] + [HOLE_LIB_ID]


# ---------------------------------------------------------------- report
def assembly_review(placed: list[Placed], table: dict) -> dict:
    """Cross-check the board against the BOM that would be ordered.

    Read back from ``BOM.csv`` rather than from ``sch.parts()``: comparing the
    board to the table it was generated from proves nothing, while comparing it
    to the file a purchaser receives is the review this board actually needs.
    The two files are produced by different generators, so this is a real
    cross-check and not a tautology.
    """
    path = OUT / "BOM.csv"
    if not path.exists():
        raise SystemExit(f"{path} is missing: run tools/make_sr_fault_board.py first, "
                         f"otherwise the assembly review has nothing to compare against")
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    bom = {row["Reference"]: row for row in rows}
    board = {p.ref: p for p in placed}
    duplicated = sorted(r for r, n in collections.Counter(
        row["Reference"] for row in rows).items() if n > 1)
    mismatch = sorted(
        (ref for ref in set(board) & set(bom)
         if bom[ref]["Value"] != board[ref].value
         or bom[ref]["Footprint"] != board[ref].footprint),
        key=_natural)
    through_hole = sorted(
        (ref for ref in board if re.search(r"\(pad \"[^\"]*\" (np_)?thru_hole",
                                            _source(board[ref].footprint))),
        key=_natural)
    return {
        "source": "BOM.csv beside the board file",
        "bom_rows": len(rows),
        "parts_on_board": len(board),
        "in_bom_but_not_on_the_board": sorted(set(bom) - set(board), key=_natural),
        "on_the_board_but_not_in_the_bom": sorted(set(board) - set(bom), key=_natural),
        "value_or_footprint_mismatch": mismatch,
        "duplicate_bom_rows": duplicated,
        "dnp_parts_placed": sorted((r for r, p in board.items() if table[r].dnp),
                                   key=_natural),
        "through_hole_refs": through_hole,
        "position_file_note": "no position file is exported: it would look orderable "
                              "next to a board whose power nets are still tracks",
    }


def routing_report(placed: list[Placed], result: router.RouteResult | None = None) -> dict:
    """What was routed, what was not, and whether the copper it emitted is legal."""
    result = result if result is not None else route(placed)
    pads = pads_of(placed)
    names = net_table(list(_table().values()))
    widths, order = route_plan(pads, names)
    clashes = router.clearance_violations(pads, result.segments, result.vias)
    return {
        "routed": not result.unrouted,
        "segments": len(result.segments),
        "vias": len(result.vias),
        "connections_made": result.connections_made,
        "connections_attempted": result.connections_attempted,
        "unrouted_nets": [names[int(n)] if n.isdigit() else n for n in result.unrouted],
        "failures": [[f[0], f[1], f[2]] for f in result.failures],
        # Connections that had to enter a barrier corridor because no other
        # path existed.  Reported, not hidden: a cut pour is a real cost and
        # the next layout change is the one that has to pay it.
        "barrier_crossings": [[names[int(c[0])] if c[0].isdigit() else c[0], c[1], c[2]]
                              for c in result.barrier_crossings],
        "clearance_violations": clashes,
        "width_mm": {"signal": ROUTE_SIGNAL_MM, "power": ROUTE_POWER_MM},
        "power_nets": sorted(POWER_NETS),
        "route_order": [names[n] for n in order],
        "net_width_mm": {names[n]: w for n, w in widths.items()},
    }


def _box(points: tuple[tuple[float, float], ...]) -> tuple[float, float, float, float]:
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    return min(xs), min(ys), max(xs), max(ys)


def pour_conflicts() -> list[list[str]]:
    """Same-layer zones at equal priority whose boxes overlap.

    Overlapping zones of *different* nets are legal when their priorities
    differ -- that is exactly how VOUT's band gets carved out of the PGND
    plane.  At equal priority the winner is decided by fill order, which is not
    a design statement, so those pairs are reported and fail the check.
    """
    out = []
    for i, a in enumerate(POURS):
        for b in POURS[i + 1:]:
            if a.layer != b.layer or a.priority != b.priority:
                continue
            ax0, ay0, ax1, ay1 = _box(a.outline)
            bx0, by0, bx1, by1 = _box(b.outline)
            if ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1:
                out.append(sorted([a.net, b.net]))
    return out


# --------------------------------------------------------------- fill measurement
# The zone outlines are the design.  The fill is what KiCad decides to keep
# after clearance, thermal reliefs and island removal, and it is not in the
# committed file -- so it has to be measured, not assumed.  Everything below
# reads a board text that *does* carry ``filled_polygon`` blocks, i.e. one that
# kicad-cli wrote back after ``--refill-zones --save-board``.

Point = tuple[float, float]


def _signed_area(points: list[Point]) -> float:
    """Shoelace area, positive for one winding and negative for the other."""
    total = 0.0
    for (x0, y0), (x1, y1) in zip(points, points[1:] + points[:1]):
        total += x0 * y1 - x1 * y0
    return total / 2.0


def _inside(points: list[Point], x: float, y: float) -> bool:
    """Ray casting with the boundary counted as inside."""
    hit = False
    for (x0, y0), (x1, y1) in zip(points, points[1:] + points[:1]):
        if (y0 > y) != (y1 > y):
            if x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
                hit = not hit
        cross = (x1 - x0) * (y - y0) - (y1 - y0) * (x - x0)
        if (abs(cross) < 1e-9 and min(x0, x1) - 1e-9 <= x <= max(x0, x1) + 1e-9
                and min(y0, y1) - 1e-9 <= y <= max(y0, y1) + 1e-9):
            return True
    return hit


def _zone_blocks(text: str) -> list[str]:
    """Every ``(zone ...)`` block, splitting on balanced parentheses."""
    out, i = [], text.find("(zone")
    while i >= 0:
        end = sch.block_end(text, i)
        out.append(text[i:end])
        i = text.find("(zone", end)
    return out


def _pts(block: str) -> list[list[Point]]:
    """The coordinate lists inside one ``(filled_polygon ...)`` block."""
    lists = re.findall(r"\(pts\s+((?:\(xy [-\d.]+\s+[-\d.]+\)\s*)+)\)", block)
    return [[(float(a), float(b)) for a, b in re.findall(r"\(xy\s+([-\d.]+)\s+([-\d.]+)\)", p)]
            for p in lists]


def fill_patches(text: str) -> dict[str, list[dict]]:
    """Per net, the filled regions KiCad kept: outer contour, holes, area."""
    out: dict[str, list[dict]] = {}
    for block in _zone_blocks(text):
        m = re.search(r'\(net "([^"]+)"\)', block)
        if not m:
            continue
        patches = out.setdefault(m.group(1), [])
        for fp in _polygon_blocks(block):
            polys = _pts(fp)
            if not polys:
                continue
            # Holes are subtracted by |area|, not by winding: KiCad writes them
            # with the opposite orientation, but a reader that depends on that
            # adds each hole to the copper it was cut out of.
            patches.append({"outer": polys[0], "holes": polys[1:],
                            "area_mm2": abs(_signed_area(polys[0]))
                            - sum(abs(_signed_area(h)) for h in polys[1:])})
    return out


def _polygon_blocks(block: str) -> list[str]:
    out, i = [], block.find("(filled_polygon")
    while i >= 0:
        end = sch.block_end(block, i)
        out.append(block[i:end])
        i = block.find("(filled_polygon", end)
    return out


def fill_report(text: str, pads: list | None = None, names: list[str] | None = None,
                specs: list[tuple[str, str, int, list[Point]]] | None = None) -> dict:
    """Area, patches and pad coverage for every pour.

    ``specs`` is ``(net, layer, priority, outline)``; it defaults to ``POURS``
    so the call site cannot describe a different board than the one generated.
    The parameter exists for tests, which have to inject a geometry they can
    compute the answer for by hand.
    """
    pads = pads if pads is not None else pads_of(placement())
    names = names if names is not None else net_table(list(_table().values()))
    specs = specs if specs is not None else [(p.net, p.layer, p.priority, list(p.outline))
                                             for p in POURS]
    fills = fill_patches(text)
    pours = {}
    for net, layer, priority, outline in specs:
        patches = fills.get(net, [])
        own = [p for p in pads if p.net >= 0 and names[p.net] == net]
        within = [p for p in own if _inside(outline, p.x, p.y)]
        covered = [f"{p.ref}.{getattr(p, 'number', '?')}" for p in within
                   if any(_inside(pt["outer"], p.x, p.y)
                          and not any(_inside(h, p.x, p.y) for h in pt["holes"])
                          for pt in patches)]
        pours[net] = {
            "layer": layer,
            "priority": priority,
            "outline_area_mm2": abs(_signed_area(outline)),
            "patches": len(patches),
            "area_mm2": round(sum(p["area_mm2"] for p in patches), 3),
            "patch_areas_mm2": [round(p["area_mm2"], 1) for p in patches],
            "pads_in_outline": len(within),
            "pads_covered": covered,
            "pads_uncovered": [f"{p.ref}.{getattr(p, 'number', '?')}" for p in within
                               if f"{p.ref}.{getattr(p, 'number', '?')}" not in covered],
        }
    return {
        "pours": pours,
        "checks": {"every_pour_has_fill": all(v["patches"] > 0 for v in pours.values())},
        "note": "measured from a board kicad-cli wrote back after --refill-zones "
                "--save-board; the committed board carries outlines only.  "
                "pads_in_outline counts the pads of the pour's own net that lie "
                "inside the outline; a pour with none there (VOUT, SEC_A) still "
                "reaches its net through the tracks the fill touches, which is "
                "why isolation is judged by the DRC and not by this count",
    }


# ------------------------------------------------------------- current rating
#
# What the secondary current actually crosses.  The SEC_A/SEC_B pours stop at
# x 43, short of the SR column, because the Q1/Q2 source and gate lands run up
# x 44.6-45.7 and the drain land starts at x 46.87; a pour over that gap would
# carve the source corridor.  So the last few millimetres of a secondary half
# are the router's escape, and the escape -- not the fill -- is what a current
# claim has to be made against.  The fill cannot even be rated from the board
# text: the committed board carries the zone outlines and no fill at all.
#
# Two numbers, two different bases, both stated rather than blended:
#
# * ``i2t_a2s`` -- adiabatic heating of the copper to ``PULSE_RISE_K``, from
#   geometry, density, heat capacity and resistivity with the cooling term at
#   zero, so it understates how long the copper survives.  This is the basis
#   that fits this board: it exists to watch one fault event of a few tens of
#   microseconds.
# * ``chart_a`` -- IPC-2221's external-trace chart, per copper weight and
#   temperature rise.  A chart, quoted to say what a *continuous* current is
#   not, and carrying nothing about the via barrel: IPC-2221 has no barrel
#   term, so the continuous number bounds the track only.
#
# The barrel is what binds the pulse number at every copper weight.  A 0.3 mm
# drill with a 0.020 mm wall is 0.0201 mm2 of copper against the track's
# 0.028 mm2 at 1 oz, and both are the same length, so the via runs hotter
# sooner.  Enlarging the drill is the fix; widening the track is not.
COPPER_OZ_MM = 0.0348                    # 1 oz nominal, 35 um
COPPER_RHO_20C_OHM_MM = 1.72e-5
COPPER_ALPHA_PER_K = 0.00393
COPPER_CP_J_PER_G_K = 0.385
COPPER_G_PER_MM3 = 8.96e-3
PLATING_MM = 0.020                       # minimum barrel wall, not a specification
PULSE_RISE_K = 50.0
CHART_RISES_K = (10.0, 20.0)
CHART_K_EXTERNAL = 0.048                 # IPC-2221 external-layer coefficient
COPPER_WEIGHTS_OZ = (1, 2)               # undecided; both are reported

# The gap the escape crosses, as a margin off the two pieces it joins.  The
# pour margin reaches back into the outline to pick up the via that sits
# inside it; the land margin reaches into the drain land for the same reason.
# The y margin keeps the band off the rest of each net's copper while still
# spanning from one corner of the pour to the other.
ESCAPE_POUR_MARGIN_MM = 1.0
ESCAPE_LAND_MARGIN_MM = 0.5
ESCAPE_Y_MARGIN_MM = 1.5
SECONDARY_NETS = ("SEC_A", "SEC_B")


def copper_rho_ohm_mm(temp_c: float) -> float:
    return COPPER_RHO_20C_OHM_MM * (1.0 + COPPER_ALPHA_PER_K * (temp_c - 20.0))


def _element(kind: str, area_mm2: float, length_mm: float, **extra: object) -> dict:
    """Resistance and adiabatic I2t of one conductor of a given cross-section.

    ``i2t`` is ``mc dT / R(T_avg)``: the energy that heats the mass by
    ``PULSE_RISE_K`` divided by the resistance at the middle of that rise, so
    the resistivity increase is carried rather than ignored.
    """
    mass_g = area_mm2 * length_mm * COPPER_G_PER_MM3
    r20 = copper_rho_ohm_mm(20.0) * length_mm / area_mm2
    energy_j = mass_g * COPPER_CP_J_PER_G_K * PULSE_RISE_K
    r_mid = r20 * (1.0 + COPPER_ALPHA_PER_K * PULSE_RISE_K / 2.0)
    return {
        "kind": kind,
        **extra,
        "area_mm2": round(area_mm2, 5),
        "length_mm": round(length_mm, 3),
        "r20_mohm": round(r20 * 1e3, 3),
        "energy_j_for_pulse_rise": round(energy_j, 6),
        "i2t_a2s": round(energy_j / r_mid, 3),
    }


def track_element(width_mm: float, thickness_mm: float, length_mm: float) -> dict:
    return _element("track", width_mm * thickness_mm, length_mm,
                    width_mm=round(width_mm, 3), thickness_mm=round(thickness_mm, 4))


def via_element(drill_mm: float, length_mm: float) -> dict:
    outer = drill_mm + 2.0 * PLATING_MM
    area = math.pi / 4.0 * (outer ** 2 - drill_mm ** 2)
    return _element("via_barrel", area, length_mm,
                    drill_mm=round(drill_mm, 3), plating_mm=PLATING_MM)


def chart_current_a(width_mm: float, thickness_mm: float, rise_k: float) -> float:
    """IPC-2221 external-trace chart: I = k dT^0.44 A^0.725 with A in mil2."""
    area_mil2 = (width_mm / 0.0254) * (thickness_mm / 0.0254)
    return CHART_K_EXTERNAL * rise_k ** 0.44 * area_mil2 ** 0.725


def _drain_land(pads: list, net: int) -> tuple[float, float, float, float]:
    """The largest Q1/Q2 land of ``net`` -- the drain base the escape feeds."""
    lands = [p for p in pads if p.net == net and p.ref in ("Q1", "Q2")]
    if not lands:
        raise SystemExit(f"net {net} has no Q1/Q2 land to escape into")
    return max(lands, key=lambda p: p.w * p.h).rect


def escape_box(pour: Pour, land_rect: tuple[float, float, float, float]
               ) -> tuple[float, float, float, float]:
    """The rectangle an escape lies in: from inside the pour to inside the land.

    x spans the gap the fill cannot cross (pour edge at 43, drain land at
    46.87); y spans the pour with a margin, so the band holds the escape and
    not the rest of the net's copper at the far end of the board.
    """
    xs = [x for x, _ in pour.outline]
    ys = [y for _, y in pour.outline]
    return (max(xs) - ESCAPE_POUR_MARGIN_MM, land_rect[0] + ESCAPE_LAND_MARGIN_MM,
            min(ys) - ESCAPE_Y_MARGIN_MM, max(ys) + ESCAPE_Y_MARGIN_MM)


def _inside_box(x: float, y: float, box: tuple[float, float, float, float]) -> bool:
    return box[0] - 1e-9 <= x <= box[1] + 1e-9 and box[2] - 1e-9 <= y <= box[3] + 1e-9


def escape_rating(pads: list, result: router.RouteResult, names: list[str]) -> dict:
    """Rate the copper that leaves each secondary pour on its way to the SR.

    Reads the routed copper, not a table: the elements are whatever segments
    and vias of that net lie wholly inside the escape box, so a re-route moves
    the numbers with it.  ``checks.every_secondary_escape_is_rated`` is the
    invariant that the box caught a series path at all.
    """
    thickness = {oz: COPPER_OZ_MM * oz for oz in COPPER_WEIGHTS_OZ}
    rated: dict[str, dict] = {}
    for pour in POURS:
        if pour.net not in SECONDARY_NETS:
            continue
        net = names.index(pour.net)
        land = _drain_land(pads, net)
        box = escape_box(pour, land)
        segs = [s for s in result.segments
                if s.net == net and _inside_box(s.x0, s.y0, box) and _inside_box(s.x1, s.y1, box)]
        vias = [v for v in result.vias if v.net == net and _inside_box(v.x, v.y, box)]
        barrels = [via_element(router.VIA_DRILL_MM, THICKNESS_MM) for _ in vias]
        narrowest = min((s.width for s in segs), default=0.0)
        rows: dict[str, dict] = {}
        for oz in COPPER_WEIGHTS_OZ:
            elements = [track_element(s.width, thickness[oz], math.hypot(s.x1 - s.x0, s.y1 - s.y0))
                        for s in segs] + barrels
            worst = min(elements, key=lambda e: e["i2t_a2s"]) if elements else None
            rows[f"{oz}oz"] = {
                "copper_thickness_mm": round(thickness[oz], 4),
                "series_r_mohm": round(sum(e["r20_mohm"] for e in elements), 3),
                "i2t_a2s": worst["i2t_a2s"] if worst else None,
                "binding_element": (f'{worst["kind"]} '
                                    f'{worst.get("drill_mm", worst.get("width_mm"))} mm') if worst else None,
                "hold_ms_at_10a": round(worst["i2t_a2s"] / 100.0 * 1e3, 2) if worst else None,
                "chart_a": {f"{int(rise)}k_rise": round(
                    chart_current_a(narrowest, thickness[oz], rise), 2)
                    for rise in CHART_RISES_K} if narrowest else {},
            }
        rated[pour.net] = {
            "pour_right_mm": round(max(x for x, _ in pour.outline), 3),
            "drain_land_left_mm": round(land[0], 3),
            "escape_box_mm": [round(v, 3) for v in box],
            "tracks": len(segs),
            "vias": len(vias),
            "narrowest_track_mm": round(narrowest, 3),
            "elements": [track_element(s.width, thickness[COPPER_WEIGHTS_OZ[0]],
                                       math.hypot(s.x1 - s.x0, s.y1 - s.y0)) for s in segs] + barrels,
            "rating": rows,
        }
    return {
        "nets": rated,
        "assumptions": {
            "copper_thickness_mm": {f"{oz}oz": round(t, 4) for oz, t in thickness.items()},
            "barrel_plating_mm": PLATING_MM,
            "board_thickness_mm": THICKNESS_MM,
            "pulse_rise_k": PULSE_RISE_K,
            "chart_rises_k": list(CHART_RISES_K),
            "copper_density_g_per_mm3": COPPER_G_PER_MM3,
            "copper_heat_capacity_j_per_g_k": COPPER_CP_J_PER_G_K,
            "copper_rho_20c_ohm_mm": COPPER_RHO_20C_OHM_MM,
            "copper_alpha_per_k": COPPER_ALPHA_PER_K,
            "ipc2221_k_external": CHART_K_EXTERNAL,
        },
        "checks": {
            "every_secondary_escape_is_rated": all(
                v["tracks"] and v["vias"] for v in rated.values()) and bool(rated),
        },
        "note": "pulse: adiabatic, no cooling term, so the times are lower bounds.  "
                "continuous: IPC-2221 external-trace chart only -- it has no via-barrel "
                "term, so the continuous number bounds the track and says nothing about "
                "the barrel that binds the pulse number.  Neither number is a measurement "
                "and neither is a thermal model of this board.",
    }


def process_requirements(result: router.RouteResult) -> dict:
    """What a fabricator has to hold, split by where each number comes from.

    Two of these are measured on this board, four are the router's design rules,
    and material/finish are a choice.  Mask and silk colours are deliberately
    left to the fabricator: inventing a colour would put a preference where a
    requirement belongs.  The three lists exist so a reader can tell which is
    which without reading this docstring.
    """
    widths = [segment.width for segment in result.segments]
    return {
        "copper_layers": len({segment.layer for segment in result.segments}),
        "thickness_mm": THICKNESS_MM,
        "copper_weight_oz": FAB_COPPER_WEIGHT_OZ,
        "min_track_mm": round(min(widths), 3) if widths else None,
        "min_clearance_mm": router.CLEARANCE_MM,
        "min_drill_mm": router.VIA_DRILL_MM,
        "min_hole_to_copper_mm": router.HOLE_CLEARANCE_MM,
        "copper_to_edge_mm": router.EDGE_CLEARANCE_MM,
        "material": "FR-4",
        "surface_finish": "HASL, lead-free",
        "mask_and_silk_colour": "fabricator default -- not specified here",
        "measured_here": ["copper_layers", "min_track_mm"],
        "design_rules": ["min_clearance_mm", "min_drill_mm",
                         "min_hole_to_copper_mm", "copper_to_edge_mm"],
        "our_choice_not_measured": ["thickness_mm", "copper_weight_oz", "material",
                                    "surface_finish", "mask_and_silk_colour"],
    }


def report(placed: list[Placed] | None = None,
           result: router.RouteResult | None = None) -> dict:
    placed = placed or placement()
    result = result if result is not None else route(placed)
    table = {p.ref: p for p in sch.parts() if p.footprint}
    names = net_table(list(table.values()))
    routing = routing_report(placed, result)
    escape = escape_rating(pads_of(placed), result, names)
    rects = [(p.ref, p.rect) for p in placed]
    overlaps: list[list[str]] = []
    for i, (ra, a) in enumerate(rects):
        for rb, b in rects[i + 1:]:
            if _overlaps(a, b, GAP_MM):
                overlaps.append([ra, rb])
    for i, hole in enumerate(_hole_rects(), start=1):
        for ref, r in rects:
            if _overlaps(hole, r, GAP_MM):
                overlaps.append([f"H{i}", ref])
    inside = all(0 <= p.rect[0] and p.rect[2] <= BOARD_W_MM
                 and 0 <= p.rect[1] and p.rect[3] <= BOARD_D_MM
                 for p in placed)
    assembly = assembly_review(placed, table)
    return {
        "status": STATUS,
        "board": {
            "width_mm": BOARD_W_MM, "depth_mm": BOARD_D_MM,
            "layers": 2, "thickness_mm": THICKNESS_MM,
            "mounting_holes": [{"x_mm": x, "y_mm": y} for x, y in MOUNTING_HOLES],
        },
        "counts": {
            "parts_with_footprint": len(table),
            "named_nets": len(names) - 1,
            "test_points": sum(1 for p in placed if p.ref.startswith("TP")),
            "dnp": sum(1 for p in table.values() if p.dnp),
        },
        "placement": [
            {"ref": p.ref, "value": p.value, "footprint": p.footprint, "block": p.block,
             "x_mm": round(p.x, 2), "y_mm": round(p.y, 2), "rot_deg": p.rot,
             "courtyard_w_mm": round(p.w_mm, 2), "courtyard_d_mm": round(p.d_mm, 2)}
            for p in placed
        ],
        "blocks": {name: {"rect_mm": list(rect)} for name, rect in BLOCKS.items()},
        "pad_pin_mapping": {
            "symbol_pins_without_a_pad": pad_pin_mapping(table),
            "note": "Q1/Q2 use dcx:BSC010N04LS6, digitised from the datasheet's "
                    "board-pads figure (design/v3/pcb/bsc010n04ls6_land.json): the four "
                    "drain fingers are pads 5-8 on a common base and the source bar "
                    "repeats 1-3, so every symbol pin owns a land.  The vendored "
                    "Infineon PG-TDSON-8 this replaced numbered all five drain lands "
                    "'5' and left pins 6-8 without copper.",
        },
        "checks": {
            "every_footprinted_part_is_placed_exactly_once":
                len({p.ref for p in placed}) == len(placed) == len(table),
            "no_two_courtyards_are_closer_than_the_gap": not overlaps,
            "overlapping_pairs": overlaps,
            "every_part_is_inside_the_outline": inside,
            "every_pad_net_is_fully_connected": routing["routed"],
            "no_copper_is_closer_than_the_clearance": not routing["clearance_violations"],
            "the_bom_and_the_board_are_the_same_parts": not (
                assembly["on_the_board_but_not_in_the_bom"]
                or assembly["in_bom_but_not_on_the_board"]
                or assembly["value_or_footprint_mismatch"]
                or assembly["duplicate_bom_rows"]),
            "every_power_net_has_a_pour": {p.net for p in POURS} == POWER_NETS,
            "the_pours_are_ordered_where_they_overlap": not pour_conflicts(),
            "every_secondary_escape_is_rated":
                escape["checks"]["every_secondary_escape_is_rated"],
        },
        "assembly_review": assembly,
        "routed": routing["routed"],
        "routing": routing,
        "pours": {
            "fill": "outlines only in the board file; kicad-cli --refill-zones fills them "
                    "for DRC and the fill is never committed",
            "zones": [{"net": p.net, "layer": p.layer, "priority": p.priority,
                       "bbox_mm": list(_box(p.outline)), "why": p.why} for p in POURS],
            "overlapping_pairs_at_equal_priority": pour_conflicts(),
            "island_removal": "mode 0 (prune fills that touch no pad of their net), stated "
                              "explicitly so the fill does not follow a KiCad default that "
                              "may change; this is what deletes the far side of a corridor "
                              "once a foreign track has crossed it, so the route pressure "
                              "that keeps those tracks out is what keeps the fill",
            "measured_in": "fill.json -- kicad-cli refills a throwaway copy with "
                           "--refill-zones --save-board and the polygons are read back; "
                           "the numbers there are a build product, not a design intent",
        },
        "power_path": {
            "track_width_mm": ROUTE_POWER_MM,
            "poured_nets": [p.net for p in POURS],
            "escape_rating": escape,
            "note": "the fills are copper in parallel with the escapes, but a fill is not "
                    "in the board file -- only its outline is -- so the escape is the only "
                    "part that can be rated from the geometry that is.  Each secondary half "
                    "leaves its pour at x 43 and reaches the drain land at x 46.87 through "
                    "one 0.8 mm track and two 0.3 mm-drill vias in series, and escape_rating "
                    "quotes that path in both bases (adiabatic I2t for a fault pulse, "
                    "IPC-2221 chart for a continuous current) rather than blending them.  "
                    "The via barrel binds the pulse number at either copper weight.  VSS is "
                    "routed at signal width on purpose: it is the controller's source "
                    "reference through the R1 Kelvin tap, not a current path.",
        },
        "process_requirements": process_requirements(result),
        "manufacturing_package": (MANUFACTURING_PACKAGE_EXPORTED
                                  if FAB_MANIFEST.is_file() else "NOT_EXPORTED"),
        "hardware_built": False,
        "fabrication_approved": False,
        "evidence": {
            "footprints": "vendored KiCad 10.0.6 stock footprints (see "
                          "hardware/stock_footprints/PROVENANCE.md), plus two "
                          "generated ones in dcx.pretty: the mounting hole, and "
                          "BSC010N04LS6 whose lands come from "
                          "design/v3/pcb/bsc010n04ls6_land.json",
            "placement": "block packing, not an optimised placement; the power-stage "
                         "bodies are fixed to keep the commutation loop in one direction",
            "nets": "same part table as the schematic generator, so the net names are "
                    "the schematic's",
            "drc": "kicad-cli output goes to drc.json; the router's own clearance check "
                   "runs in CI, where kicad-cli is absent",
            "routing": "deterministic Manhattan grid router (tools/sr_board_router.py) on "
                       "two layers; the widths and the net order are in this file, and the "
                       "copper it emits is re-checked against the same clearance by "
                       "clearance_violations()",
            "pours": "zone outlines in POURS, filled only at DRC time; the fill is a build "
                     "product and its patchiness is reported, not assumed away",
        },
        "remaining_work": [
            "check the digitised land against a vendor CAD model or an IPC-7351 "
            "calculation when one is available: it is measured from Fig. 2 of the "
            "datasheet (max residual 4.9 um) but is still a redrawing, and neither "
            "this repository nor the sheet's board-pads figure says whether the "
            "lands are to IPC density level A, B or C",
            "widen the secondary escape before claiming more than a fault pulse: the "
            "0.8 mm track and the two 0.3 mm-drill vias between the pour edge at x 43 "
            "and the drain land at x 46.87 are quoted in power_path.escape_rating, and "
            "at 1 oz the chart puts one half at about 2 A continuous.  IPC-2221 has no "
            "via-barrel term, so a continuous rating needs a barrel calculation from the "
            "fabricator's plating spec, not a wider chart lookup",
            "keep the VSS Kelvin tap (R1) off the power return -- the PGND pour is what "
            "must not creep up to it, and that is a fill question, not a track question",
            "confirm the copper weight with the fabricator: the package asks for 1 oz, "
            "which is what the escape_rating chart numbers are quoted at; 2 oz would "
            "raise the track figure but not the via barrel that binds the pulse number",
            "the fab package in pcb/sr_fault_validation/fab/ is exported and is still "
            "not an approval: the manifest binds the nine gerbers, the drill file and "
            "the DNP-excluded position CSV to the board hash and repeats the escape "
            "rating as a stated limit, and the export fails if a layer it asked for is "
            "missing or a DNP part is still in the CSV.  hardware_built and "
            "fabrication_approved stay false until a person signs, and the 1 oz in it "
            "is a request to the fabricator, not a measurement",
        ],
    }


# ---------------------------------------------------------------- write / check
def _report_text(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def write() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    placed = placement()
    result = route(placed)                 # cached; the report asks for it again
    (OUT / BOARD).write_text(board_file(placed, result), encoding="utf-8", newline="\n")
    (OUT / "fp-lib-table").write_text(fp_lib_table(), encoding="utf-8", newline="\n")
    (OUT / "dcx.pretty").mkdir(exist_ok=True)
    (OUT / "dcx.pretty" / "MountingHole_3.2mm_M3.kicad_mod").write_text(
        mounting_hole_source(), encoding="utf-8", newline="\n")
    (OUT / "dcx.pretty" / "BSC010N04LS6.kicad_mod").write_text(
        bsc_source(), encoding="utf-8", newline="\n")
    data = report(placed, result)
    (OUT / REPORT).write_text(_report_text(data), encoding="utf-8", newline="\n")
    return data


DETAIL_ARRAYS = ("violations", "unconnected_items", "schematic_parity")


def drc_items(path: Path | None = None) -> dict[str, list[dict]]:
    """The three top-level item arrays of kicad-cli's DRC JSON.

    ``unconnected_items`` is *not* a violation -- kicad-cli puts the ratsnest in
    its own array.  A reader that opens only ``violations`` therefore sees zero
    unconnected items on a board carrying a hundred, which is how the guard
    "an unrouted board with no ratsnest means the netlist never reached the
    board" can fire on a perfectly good board.  ``schematic_parity`` is separate
    again: it is what catches a part that exists on only one side.
    """
    path = path or OUT / "drc.json"
    if not path.exists():
        return {name: [] for name in DETAIL_ARRAYS}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {name: data.get(name, []) for name in DETAIL_ARRAYS}


# A placement defect at this stage: something that would stop the board from
# being routed correctly, or that says the footprint did not resolve.
PLACEMENT_ERRORS = {"lib_footprint_issues", "lib_footprint_mismatch", "missing_courtyard",
                    "courtyards_overlap", "clearance", "shorting_items", "hole_clearance",
                    "hole_to_hole", "edge_clearance", "copper_edge_clearance"}

# A pour defect.  ``isolated_copper`` is a fill patch that touches no pad of
# its own net: KiCad pruned it to nothing useful.  This is the failure mode the
# pours exist to avoid -- if every patch under a power net is isolated, the net
# is back on its 0.8 mm escape track alone, and the board looks poured.
POUR_ERRORS = {"isolated_copper", "starved_thermal"}

# Cosmetic only: the reference designators have never been moved off one
# another, so a few still overlap.  Reported as backlog, not as a gate -- a
# gate that can never go green stops being read.
COSMETIC_TYPES = {"silk_overlap", "silk_over_copper", "text_over_copper",
                  "text_thickness", "text_height"}


def classify_violations(violations: list[dict]) -> dict[str, list[dict]]:
    """Split DRC violations into placement / pour / cosmetic / unclassified."""
    return {
        "placement": [v for v in violations if v.get("type") in PLACEMENT_ERRORS],
        "pours": [v for v in violations if v.get("type") in POUR_ERRORS],
        "cosmetic": [v for v in violations if v.get("type") in COSMETIC_TYPES],
        "other": [v for v in violations
                  if v.get("type") not in PLACEMENT_ERRORS | POUR_ERRORS | COSMETIC_TYPES],
    }


def drc_command(cli: Path, board: Path, out: Path) -> list[str]:
    """The ``kicad-cli pcb drc`` argv.

    ``--refill-zones`` fills the outlines in memory before DRC looks at them.
    Without it the zones are empty, and DRC then judges a board with no pour
    at all -- the check passes precisely because the copper is missing.

    ``--save-board`` is deliberately absent.  It is the only way to get the
    fill written back, and writing it back would make the committed board file
    depend on the KiCad version that computed it: 33.6k lines instead of 2.5k
    for the same design, and a diff on every version bump.
    """
    return [str(cli), "pcb", "drc", "--format", "json", "--severity-all",
            "--refill-zones", "-o", str(out), str(board)]


def run_drc(cli: Path, board: Path, out: Path) -> dict[str, list[dict]]:
    """Run kicad-cli and refuse to read a report it did not write.

    kicad-cli exits 0 for DRC *violations*, so return code is not a verdict --
    but a non-zero code is a load failure, and a missing report is a run that
    never happened.  Either way the old ``drc.json`` must not be read: it is a
    report about a different board, and reading it turns a broken file into
    "0 unconnected items".

    This is not hypothetical.  A zone token this KiCad does not accept made
    every load fail with exit 3, ``subprocess.run(check=False)`` swallowed it,
    and ``check()`` reported the previous run's "0 unconnected, 4 silk" as if
    it had just been measured.  Deleting the report first is the fix: after a
    failed run there is nothing to misread.
    """
    if out.exists():
        out.unlink()
    # ``encoding``/``errors`` are explicit on purpose.  The default text mode
    # decodes with the console code page (GBK here), and kicad-cli emits bytes
    # that are not valid GBK: the reader thread raised UnicodeDecodeError and
    # every captured message became ``None``.  A DRC runner that cannot quote
    # its own failure is a DRC runner that cannot fail.
    proc = subprocess.run(drc_command(cli, board, out), capture_output=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise SystemExit(f"kicad-cli DRC did not run (exit {proc.returncode}): {detail}")
    if not out.exists():
        raise SystemExit(f"kicad-cli exited 0 but wrote no report to {out}")
    return drc_items(out)


def fill_command(cli: Path, board: Path, out: Path) -> list[str]:
    """``kicad-cli pcb drc`` with the fill written back into ``board``.

    ``--save-board`` is legal only together with ``--refill-zones``, and it is
    used here on a throwaway copy: the fill is a measurement, not part of the
    committed board file.
    """
    return [str(cli), "pcb", "drc", "--format", "json", "--severity-all",
            "--refill-zones", "--save-board", "-o", str(out), str(board)]


def measure_fills(cli: Path, version: str = "") -> dict:
    """Refill a throwaway copy of the board and report what survived.

    The copy has to live in ``OUT``: the footprints are resolved through the
    project's ``fp-lib-table``, which is found next to the board.  A copy in a
    temp directory loads with every library missing and fills nothing.
    """
    tmp = OUT / "_fill_tmp.kicad_pcb"
    rpt = OUT / "_fill_tmp_drc.json"
    tmp.write_text((OUT / BOARD).read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    for path in (rpt, OUT / "_fill_tmp.kicad_prl"):
        path.unlink(missing_ok=True)
    try:
        proc = subprocess.run(fill_command(cli, tmp, rpt), capture_output=True,
                              encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout).strip()
            raise SystemExit(f"the fill could not be measured (exit {proc.returncode}): {detail}")
        if not rpt.exists():
            raise SystemExit(f"kicad-cli exited 0 but wrote no report to {rpt}")
        data = fill_report(tmp.read_text(encoding="utf-8"))
        items = drc_items(rpt)
        data["checks"]["no_pour_patch_is_isolated"] = not classify_violations(
            items["violations"])["pours"]
        data["checks"]["no_unconnected_items_with_the_zones_filled"] = not items[
            "unconnected_items"]
        data["kicad_cli"] = version
        return data
    finally:
        for path in (tmp, rpt, OUT / "_fill_tmp.kicad_prl"):
            path.unlink(missing_ok=True)


def check(fab: bool = False) -> None:
    data = write()
    checks = data["checks"]
    if not all(v for k, v in checks.items() if isinstance(v, bool)):
        raise SystemExit(f"placement checks failed: {checks}")
    print(f"board {data['board']['width_mm']} x {data['board']['depth_mm']} mm, "
          f"{data['counts']['parts_with_footprint']} parts, "
          f"{data['counts']['named_nets']} named nets, "
          f"{data['counts']['test_points']} test points")
    cli = find_kicad_cli()
    if cli is None:
        if fab:
            raise SystemExit("--fab needs kicad-cli (KICAD_CLI, PATH, or a standard "
                             "install): the gerbers are whatever kicad-cli plots")
        print("kicad-cli not found (KICAD_CLI, PATH, or a standard install) -- "
              "DRC NOT reproduced; the committed board was still regenerated")
        return
    version = subprocess.run([str(cli), "--version"], capture_output=True,
                             encoding="utf-8", errors="replace", check=False).stdout.strip()
    print("kicad-cli:", version)
    items = run_drc(cli, OUT / BOARD, OUT / "drc.json")
    vs = items["violations"]
    unconnected = items["unconnected_items"]
    parity = items["schematic_parity"]
    by_type: dict[str, int] = {}
    for v in vs:
        by_type[v["type"]] = by_type.get(v["type"], 0) + 1
    buckets = classify_violations(vs)
    real, pours, cosmetic = buckets["placement"], buckets["pours"], buckets["cosmetic"]
    other = buckets["other"]
    print(f"DRC: {len(vs)} violations {by_type or '{}'}")
    for v in real[:8]:
        print(f"  {v['severity']} {v['type']}: {v['description']}")
    print(f"pour backlog: {len(pours)} isolated fills (a gate)")
    for v in pours[:8]:
        print(f"  {v['severity']} {v['type']}: {v['description']}")
    print(f"routing backlog: {len(unconnected)} unconnected items")
    print(f"cosmetic backlog: {len(cosmetic)} silkscreen/text items (not a gate)")
    print(f"schematic parity: {len(parity)} items")
    if real or pours or parity or other:
        raise SystemExit(
            f"DRC found a defect -- {len(real)} courtyard/clearance/footprint items, "
            f"{len(pours)} isolated pour fills, {len(parity)} parity items, "
            f"{len(other)} unclassified")
    routed = data["routing"]["routed"]
    if routed and unconnected:
        raise SystemExit(
            f"the router reports every net connected but kicad-cli still sees "
            f"{len(unconnected)} unconnected items: the copper did not land on the pads "
            f"the netlist names")
    if not routed and not unconnected:
        raise SystemExit("no unconnected items on an unrouted board: the netlist did not "
                         "reach the board, so the DRC result means nothing")
    measure_and_record(cli, version)
    manifest = export_fab(cli, version, data)
    # ``report()`` reads the manifest's existence, so it was written before the
    # package existed; restate the one field the export changed and rewrite.
    data["manufacturing_package"] = MANUFACTURING_PACKAGE_EXPORTED
    (OUT / REPORT).write_text(_report_text(data), encoding="utf-8", newline="\n")
    print(f"fab: {len(manifest['files'])} files, "
          f"{sum(f['bytes'] for f in manifest['files']) / 1024.0:.0f} KiB, "
          f"{manifest['copper_weight_oz']} oz, kicad-cli {version}")
    for net, row in manifest["current_rating"]["nets"].items():
        lead = row["rating"][f"{COPPER_WEIGHTS_OZ[0]}oz"]
        print(f"  escape {net}: {row['tracks']} track(s) + {row['vias']} via(s), "
              f"{lead['series_r_mohm']} mOhm at {COPPER_WEIGHTS_OZ[0]} oz, "
              f"I2t {lead['i2t_a2s']} A2s by the {lead['binding_element']} "
              f"({lead['hold_ms_at_10a']} ms at 10 A), "
              f"chart {next(iter(lead['chart_a'].values()))} A at "
              f"{CHART_RISES_K[0]:.0f} K")


def measure_and_record(cli: Path, version: str) -> None:
    """Write ``fill.json`` and fail if a pour did not fill."""
    fills = measure_fills(cli, version)
    (OUT / "fill.json").write_text(json.dumps(fills, indent=2) + "\n", encoding="utf-8")
    for net, row in fills["pours"].items():
        print(f"fill {net:7s} {row['layer']:5s} {row['patches']} patch(es) "
              f"{row['area_mm2']:8.1f} mm2 of {row['outline_area_mm2']:7.1f} outline, "
              f"{row['pads_covered'] and len(row['pads_covered']) or 0}/"
              f"{row['pads_in_outline']} pads inside the outline on the fill")
    bad = [name for name, ok in fills["checks"].items() if not ok]
    if bad:
        raise SystemExit(f"the pours did not fill as designed: {bad}")


def fab_commands(cli: Path, board: Path, out: Path,
                 prefix: str = "sr_fault_validation") -> dict[str, list[str]]:
    """The three exports that make a fabrication package.

    ``--check-zones`` on the gerbers is the one that matters.  The committed
    board carries zone *outlines* and no fill, so a plot without it would ship
    empty pours next to a DRC run that refilled them -- the package would
    disagree with its own evidence.  The position file excludes the DNP parts:
    they have lands but are not placed, which is what "do not populate" means.

    ``prefix`` names the position CSV.  It defaults to this board's own stem so
    the committed ``fab/`` stays byte-identical; a second board passes its own
    rather than sharing a filename that would overwrite the first board's file
    if both packages were ever unpacked together.
    """
    return {
        "gerbers": [str(cli), "pcb", "export", "gerbers", "--check-zones",
                    "-l", FAB_GERBER_LAYERS, "-o", str(out), str(board)],
        "drill": [str(cli), "pcb", "export", "drill", "--format", "excellon",
                  "-u", "mm", "-o", str(out), str(board)],
        "position": [str(cli), "pcb", "export", "pos", "--format", "csv",
                     "--units", "mm", "--exclude-dnp",
                     "-o", str(out / f"{prefix}-pos.csv"), str(board)],
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def plotted_layers(out: Path) -> list[str]:
    """The gerber plots kicad-cli actually wrote, by layer name.

    A layer the board's ``(layers)`` table does not declare is dropped without
    a message or a non-zero exit, so "the export returned 0" is not evidence
    that every requested layer was plotted.
    """
    present = {p.suffix.lower() for p in out.iterdir() if p.is_file()}
    return [name for name, suffix in FAB_GERBER_SUFFIX.items() if suffix in present]


def check_plotted_layers(out: Path) -> None:
    """Fail, naming the layer, when a requested gerber layer produced no file."""
    missing = [name for name in FAB_GERBER_SUFFIX if name not in plotted_layers(out)]
    if missing:
        raise SystemExit(
            "kicad-cli plotted no file for: " + ", ".join(missing)
            + ".  It plots only the layers the board's own (layers) table declares;"
              " add them there rather than dropping them from the package.")


def position_refs(path: Path) -> set[str]:
    """The references a pick-and-place machine would act on, read from the CSV."""
    with path.open(encoding="utf-8", newline="") as fh:
        return {row["Ref"] for row in csv.DictReader(fh)}


def check_position_excludes_dnp(path: Path, dnp: set[str] | None = None) -> None:
    """Fail, naming the part, when a DNP part is still in the position file.

    ``--exclude-dnp`` reads the footprint's ``(attr ... dnp)``, not the part
    table.  The first package was exported with the flag on a board where no
    footprint carried it, so the ten DNP parts -- the gate clamps that are
    meant to stay unpopulated -- went into the CSV a machine follows.

    ``dnp`` defaults to *this* board's DNP set; another board passes its own so
    the guard names that board's parts instead of silently checking SR ones.
    """
    leaked = sorted(position_refs(path) & (_dnp_refs() if dnp is None else dnp))
    if leaked:
        raise SystemExit(
            f"{path.name} still places the DNP part(s) {', '.join(leaked)}.  "
            f"--exclude-dnp reads the footprint's (attr ... dnp); the dnp flag in the "
            f"part table has to be written onto the board as well.")


# Normalise kicad-cli's Windows CRLF Gerber/drill/position outputs to LF
# BEFORE hashing.  Git auto-CRLF otherwise silently rewrites their bytes
# after commit: both validation board manifests were already stale in checkout.
# These are textual numerical tooling formats, NOT PCB geometry changes.
FAB_TEXT_SUFFIXES = {
    ".gbl", ".gbs", ".gbp", ".gbo", ".gm1", ".gtl", ".gts", ".gtp",
    ".gto", ".gbrjob", ".drl", ".csv",
}


def normalise_fab_text_line_endings(directory: Path) -> list[str]:
    changed: list[str] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix.lower() not in FAB_TEXT_SUFFIXES:
            continue
        original = path.read_bytes()
        # Refuse an accidentally binary file; no silent corruption of drill
        # or pick-and-place exports merely because its extension was expected.
        if bytes([0]) in original:
            raise ValueError(f"{path.name}: binary content in textual fab export")
        fixed = original.replace(bytes([13, 10]), bytes([10]))
        if fixed != original:
            path.write_bytes(fixed)
            changed.append(path.name)
    return changed


def export_fab(cli: Path, version: str, data: dict) -> dict:
    """Write ``fab/`` and the manifest that says what the package is.

    The manifest repeats the escape rating rather than pointing at the board
    report: a fabricator receives the zip, not the repository, so the limit has
    to travel with the copper.  It also carries the two approval flags as
    false, because a package that can be ordered is exactly the artefact that
    gets mistaken for an approved one.
    """
    board = OUT / BOARD
    drc = OUT / "drc.json"
    fills = OUT / "fill.json"
    for path in (drc, fills):
        if not path.is_file():
            raise SystemExit(f"{path.name} is missing: run --check before --fab")
        if path.stat().st_mtime < board.stat().st_mtime:
            raise SystemExit(f"{path.name} is older than the board -- it describes a "
                             f"different design; run --check again")
    if not all(json.loads(fills.read_text(encoding="utf-8"))["checks"].values()):
        raise SystemExit("fill.json has a failed pour check; not packaging it")

    FAB.mkdir(parents=True, exist_ok=True)
    for stale in FAB.iterdir():
        if stale.is_file():
            stale.unlink()
    for name, argv in fab_commands(cli, board, FAB).items():
        proc = subprocess.run(argv, capture_output=True, encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            raise SystemExit(f"kicad-cli {name} export failed (exit {proc.returncode}): "
                             f"{(proc.stderr or proc.stdout).strip()}")
    normalise_fab_text_line_endings(FAB)
    # The assembly drawing is built from the placement table, not plotted from
    # the board: kicad-cli draws the silkscreen, which has the references
    # wherever layout left them and cannot mark a part "DNP".  Imported here
    # because ``assembly_drawing`` imports this module for that same table.
    import assembly_drawing
    assembly_drawing.write(FAB / "assembly.svg")
    files = sorted(p for p in FAB.iterdir() if p.is_file() and p.name != FAB_MANIFEST.name)
    if not files:
        raise SystemExit("the fabrication export wrote no files")
    check_plotted_layers(FAB)
    # A package can be complete by count and still instruct a machine to place
    # a part that must stay empty, so the position file is checked on content.
    check_position_excludes_dnp(FAB / "sr_fault_validation-pos.csv")
    rating = data["power_path"]["escape_rating"]
    manifest = {
        "board": BOARD,
        "board_sha256": _sha256(board),
        "kicad_cli": version,
        "copper_weight_oz": FAB_COPPER_WEIGHT_OZ,
        "layers": FAB_GERBER_LAYERS.split(","),
        "plotted_layers": plotted_layers(FAB),
        "excluded_from_position": sorted(_dnp_refs() & {p["ref"] for p in data["placement"]}),
        "files": [{"name": p.name, "bytes": p.stat().st_size, "sha256": _sha256(p)}
                  for p in files],
        "current_rating": rating,
        "process_requirements": data["process_requirements"],
        "what_this_is": "gerbers, drill, a position file and an assembly/DNP drawing for a "
                        "fault-response validation board: two UCC24624, two BSC010N04LS6, and "
                        "the fault interface.  The escapes are rated in current_rating.",
        "what_this_is_not": [
            "an approval to build: hardware_built and fabrication_approved are false",
            "a 100 A power stage -- the board is for one fault event of a few tens of "
            "microseconds, and the continuous figure in current_rating is a chart. "
            "The 10 A in the board document is a pulse, not a continuous rating",
            "a thermal model: current_rating has no cooling term and no junction "
            "temperature, and IPC-2221 has no via-barrel term at all",
            "a checked drawing: assembly.svg is generated from the same placement table "
            "as the copper, so the two cannot disagree -- but it has not been compared "
            "with a physical first article",
        ],
        "flags": {"hardware_built": False, "fabrication_approved": False},
    }
    FAB_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8", newline="\n")
    return manifest


def _dnp_refs() -> set[str]:
    return {p.ref for p in sch.parts() if p.dnp}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="regenerate, run kicad-cli DRC, measure the fills and export fab/")
    ap.add_argument("--write", action="store_true", help="regenerate the board and report")
    ap.add_argument("--fab", action="store_true",
                    help="like --check, and fail loudly if the fab package cannot be written")
    args = ap.parse_args()
    if args.check or args.fab:
        check(fab=args.fab)
    else:
        data = write()
        print(f"wrote {OUT} ({data['counts']['parts_with_footprint']} parts, "
              f"{data['board']['width_mm']} x {data['board']['depth_mm']} mm, "
              f"{data['counts']['named_nets']} nets)")


if __name__ == "__main__":
    main()

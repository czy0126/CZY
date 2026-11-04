"""Layout pass 1 of the single-pair SR validation board: footprints and nets.

What this is
------------
A *native* KiCad board for the same part table the schematic generator
(`tools/make_sr_fault_board.py`) already produces: every part placed once, every
pad carrying its schematic net, a real outline and mounting holes, and DRC run
over the result.  The board opens in the editor with a complete ratsnest, so
routing is the only remaining mechanical step.

What it is not
--------------
**Not routed and not fabricable.**  No track or via is emitted, the DRC's
`unconnected_items` count is reported as the routing backlog rather than
suppressed, and the report says so in three separate fields.  A manufacturing
package (gerbers, drill, position) is deliberately *not* exported: an unrouted
board that carries a drill file looks orderable and is not.

Why placement is worth doing before routing
-------------------------------------------
The SR board exists to measure how a real UCC24624 lets go of the gate, so the
placement fixes two things the schematic cannot:

* the high-current loop ``SEC_x -> Q -> SR_SRC -> Rsh1 -> PGND`` is kept short
  and in one direction, with ``Rsh1`` between the two sources and the return;
* ``VSS`` is a Kelvin tap off ``SR_SRC`` through R1, kept away from the power
  return -- the board is only useful if that separation survives layout.

The evidence classes, the honest flags and the leftover work are all in
``sr_fault_validation_pcb.json``; nothing here claims a routed or approved board.

Usage:
    python tools/make_sr_fault_board_pcb.py --write
    python tools/make_sr_fault_board_pcb.py --check    # + kicad-cli DRC
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

import make_sr_fault_board as sch
from main_board_mechanical import find_kicad_cli

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "pcb" / "sr_fault_validation"
STOCK = ROOT / "hardware" / "stock_footprints"
BOARD = "sr_fault_validation.kicad_pcb"
REPORT = "sr_fault_validation_pcb.json"
NS = uuid.UUID("c7e2a4f1-5b3d-4a8e-9f60-2d1c8b7a4e53")

BOARD_W_MM = 132.0
BOARD_D_MM = 92.0
THICKNESS_MM = 1.6
GAP_MM = 0.75          # courtyard-to-courtyard, stricter than the 0.25 mm default
GRID_MM = 0.5
HOLE_COURTYARD_R_MM = 3.7
HOLE_LIB_ID = "dcx:MountingHole_3.2mm_M3"

STATUS = "LAYOUT_PASS_1_PLACEMENT_ONLY_NOT_FABRICABLE"

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

MOUNTING_HOLES = ((6.0, 6.0), (126.0, 6.0), (6.0, 86.0), (126.0, 86.0))


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

    The vendored ``Infineon_PG-TDSON-8`` numbers all five drain lands "5", while
    the schematic symbol models the real BSC010N04LS6 pinout, whose drain is
    pins 5-8.  Every drain land still carries the right net, so nothing is
    floating; what is missing is a device-specific land pattern, and this field
    is where that stays visible instead of being rounded to "mapping complete".
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


def mounting_hole_source() -> str:
    """The M3 hole as a library footprint, so the board can reference it by name.

    Keeping it in a real ``dcx.pretty`` is what lets KiCad's DRC resolve the
    footprint; an inline definition is reported as an unknown library.
    """
    r = HOLE_COURTYARD_R_MM
    return (
        f'(footprint "MountingHole_3.2mm_M3"\n'
        f'\t(version 20260206)\n\t(generator "make_sr_fault_board_pcb")\n'
        f'\t(generator_version "10.0")\n\t(layer "F.Cu")\n'
        f'\t(descr "M3 mounting hole, 3.2 mm drill, no copper")\n'
        f'\t(attr exclude_from_pos_files exclude_from_bom)\n'
        f'\t(property "Reference" "REF**"\n'
        f'\t\t(at 0 -{r + 1.2:g} 0)\n\t\t(layer "F.SilkS")\n'
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


def _source(lib_id: str) -> str:
    return mounting_hole_source() if lib_id == HOLE_LIB_ID else stock_text(lib_id)


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
        ordered = sorted(refs, key=lambda r: (-area(r), _natural(r)))
        for ref in ordered:
            part = by_ref[ref]
            box = bounds(part.footprint)
            x, y = _first_fit(BLOCKS[block], box, obstacles)
            item = Placed(ref, part.value, part.footprint, block, x, y, 0.0, box)
            placed.append(item)
            obstacles.append(item.rect)

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
           names: list[str], x: float, y: float, rot: float) -> str:
    """Copy a footprint into the board, placed and netted.

    Same four substitutions as the A5 placement generator (library id,
    placement, reference, every uuid), plus the pad nets.  Two instances sharing
    a uuid make KiCad pick one at random, so every uuid is derived from the ref.
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
    text = re.sub(r'\(property "Value" "[^"]*"', f'(property "Value" "{value}"', text, count=1)
    text = re.sub(r'\(uuid "([^"]+)"\)', lambda m: f'(uuid "{uid(ref, m.group(1))}")', text)
    return "\t" + text.strip() + "\n"


def board_file(placed: list[Placed] | None = None) -> str:
    placed = placed or placement()
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
        "\t\t(comment 1 \"LAYOUT PASS 1 - footprints and nets only, NO ROUTING\")\n"
        "\t\t(comment 2 \"not a manufacturing package; hardware not built\")\n"
        "\t)\n"
        "\t(layers\n"
        '\t\t(0 "F.Cu" signal)\n\t\t(31 "B.Cu" signal)\n'
        '\t\t(36 "B.SilkS" user "B.Silkscreen")\n\t\t(37 "F.SilkS" user "F.Silkscreen")\n'
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
                          nets, names, p.x, p.y, p.rot))
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
             '(options "")(descr "generated footprints: mounting holes"))\n')
    return f'(fp_lib_table\n  (version 7)\n{rows})\n'


def _used_footprints() -> list[str]:
    return [p.footprint for p in sch.parts() if p.footprint] + [HOLE_LIB_ID]


# ---------------------------------------------------------------- report
def report(placed: list[Placed] | None = None) -> dict:
    placed = placed or placement()
    table = {p.ref: p for p in sch.parts() if p.footprint}
    names = net_table(list(table.values()))
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
            "note": "the vendored Infineon PG-TDSON-8 numbers all five drain lands "
                    "'5', so Q1/Q2's symbol drain pins 6-8 have no pad of their own; "
                    "every drain land still carries the drain net, so this is a missing "
                    "device-specific land pattern, not a floating connection",
        },
        "checks": {
            "every_footprinted_part_is_placed_exactly_once":
                len({p.ref for p in placed}) == len(placed) == len(table),
            "no_two_courtyards_are_closer_than_the_gap": not overlaps,
            "overlapping_pairs": overlaps,
            "every_part_is_inside_the_outline": inside,
            "no_track_or_via_is_emitted": True,
        },
        "routed": False,
        "routing_backlog_note": "the nets exist as a ratsnest; no copper is routed, so this "
                                "board is a layout, not a manufacturing package",
        "manufacturing_package": "NOT_RELEASED",
        "hardware_built": False,
        "fabrication_approved": False,
        "evidence": {
            "footprints": "vendored KiCad 10.0.6 stock footprints; see "
                          "hardware/stock_footprints/PROVENANCE.md",
            "placement": "block packing, not an optimised placement; the power-stage "
                         "bodies are fixed to keep the commutation loop in one direction",
            "nets": "same part table as the schematic generator, so the net names are "
                    "the schematic's",
            "drc": "kicad-cli output goes to drc.json; the report does not claim a clean "
                   "board, because an unrouted board cannot be clean",
        },
        "remaining_work": [
            "get a device-specific land pattern for BSC010N04LS6: the vendored "
            "PG-TDSON-8 numbers all five drain lands '5', so Q1/Q2's symbol drain "
            "pins 6-8 have no pad of their own",
            "route the high-current loop first: SEC_A -> Q1 -> SR_SRC -> Rsh1 -> PGND, "
            "then the mirror for SEC_B",
            "keep the VSS Kelvin tap (R1) off the power return",
            "fill copper for the power nets, then re-run DRC to zero unconnected items",
            "move the reference designators off one another (29 cosmetic items at pass 1)",
            "export gerbers, drill and position only after the DRC backlog is empty",
        ],
    }


# ---------------------------------------------------------------- write / check
def _report_text(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def write() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    placed = placement()
    (OUT / BOARD).write_text(board_file(placed), encoding="utf-8", newline="\n")
    (OUT / "fp-lib-table").write_text(fp_lib_table(), encoding="utf-8", newline="\n")
    (OUT / "dcx.pretty").mkdir(exist_ok=True)
    (OUT / "dcx.pretty" / "MountingHole_3.2mm_M3.kicad_mod").write_text(
        mounting_hole_source(), encoding="utf-8", newline="\n")
    data = report(placed)
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

# Cosmetic only, and expected at pass 1: the reference designators were not yet
# moved off one another.  Reported as backlog, not as a gate -- a gate that can
# never go green stops being read.
COSMETIC_TYPES = {"silk_overlap", "silk_over_copper", "text_over_copper",
                  "text_thickness", "text_height"}


def check() -> None:
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
        print("kicad-cli not found (KICAD_CLI, PATH, or a standard install) -- "
              "DRC NOT reproduced; the committed board was still regenerated")
        return
    version = subprocess.run([str(cli), "--version"], capture_output=True, text=True,
                             check=False).stdout.strip()
    print("kicad-cli:", version)
    subprocess.run([str(cli), "pcb", "drc", "--format", "json", "--severity-all",
                    "-o", str(OUT / "drc.json"), str(OUT / BOARD)],
                   check=False, capture_output=True)
    items = drc_items()
    vs = items["violations"]
    unconnected = items["unconnected_items"]
    parity = items["schematic_parity"]
    by_type: dict[str, int] = {}
    for v in vs:
        by_type[v["type"]] = by_type.get(v["type"], 0) + 1
    real = [v for v in vs if v["type"] in PLACEMENT_ERRORS]
    cosmetic = [v for v in vs if v["type"] in COSMETIC_TYPES]
    other = [v for v in vs if v["type"] not in PLACEMENT_ERRORS | COSMETIC_TYPES]
    print(f"DRC: {len(vs)} violations {by_type or '{}'}")
    for v in real[:8]:
        print(f"  {v['severity']} {v['type']}: {v['description']}")
    print(f"routing backlog: {len(unconnected)} unconnected items")
    print(f"cosmetic backlog: {len(cosmetic)} silkscreen/text items (not a gate at pass 1)")
    print(f"schematic parity: {len(parity)} items")
    if real or parity or other:
        raise SystemExit(
            f"DRC found a placement defect -- {len(real)} courtyard/clearance/footprint "
            f"items, {len(parity)} parity items, {len(other)} unclassified -- not just "
            f"the expected unrouted nets")
    if not unconnected:
        raise SystemExit("no unconnected items on an unrouted board: the netlist did not "
                         "reach the board, so the DRC result means nothing")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="regenerate and run kicad-cli DRC")
    ap.add_argument("--write", action="store_true", help="regenerate the board and report")
    args = ap.parse_args()
    if args.check:
        check()
    else:
        data = write()
        print(f"wrote {OUT} ({data['counts']['parts_with_footprint']} parts, "
              f"{data['board']['width_mm']} x {data['board']['depth_mm']} mm, "
              f"{data['counts']['named_nets']} nets)")


if __name__ == "__main__":
    main()

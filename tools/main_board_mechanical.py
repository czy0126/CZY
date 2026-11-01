"""A5: 1:1 mechanical placement of the main power stage (placement only).

What this is
------------
A single table of parts with real outlines, laid out on a KiCad board that
opens in the editor and renders in 3D.  There are **no nets and no tracks** --
this is the answer to "does it all physically fit, and where does the height
problem land", which is the question the delivery plan puts before routing.

What it is not
--------------
Not a routed board, not a DRC-clean design, not a manufacturing output.  Every
pad is unconnected by design.  `kicad-cli pcb drc` is still run, but only for
the two things a placement can be wrong about: courtyards that touch, and
footprints from a library the project cannot see (a footprint KiCad cannot
resolve is a black box, so its courtyard is not checked either -- the same trap
already documented for the schematic side in ``make_control_board.py``).

Where each number comes from
----------------------------
Every outline carries an evidence class, and the report prints it:

``generated-json``  read from a tool's JSON in this repo (ELP32 core, Cout
                    height, busbar section).
``kicad-library``   the stock footprint's own dimensions (the SR FET).
``datasheet``       a package size the BOM marks VERIFIED.
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
import json
import re
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "hardware" / "dcx_mech"
DESIGN = ROOT / "design" / "v3"
KICAD_SHARE = Path(r"C:\Users\27792\AppData\Local\Programs\KiCad\10.0\share\kicad")
KICAD_CLI = Path(r"C:\Users\27792\AppData\Local\Programs\KiCad\10.0\bin\kicad-cli.exe")
NS = uuid.UUID("a5b6c7d8-1e2f-4a3b-9c4d-5e6f7a8b9c0d")

HEIGHT_LIMIT_MM = 10.0
ELP32_FP = "dcx:ELP32_31.75x25.4"
EDGE_MARGIN_MM = 5.0
BOARD_T = 1.6


def uid(*parts: str) -> str:
    return str(uuid.uuid5(NS, "/".join(parts)))


def _load(rel: str) -> dict:
    return json.loads((DESIGN / rel).read_text(encoding="utf-8"))


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


def parts() -> tuple[Part, ...]:
    """The placement table.  Order is the reading order of the board, top to
    bottom, and every coordinate is the part *centre* in mm from the top-left."""
    core = _core()
    cout = _cout()
    bar = _bar()
    mag_w = core["outer_length_m"] * 1e3
    mag_d = core["core_depth_m"] * 1e3
    mag_h = core["height_max_m"] * 1e3
    elp32 = ELP32_FP
    COUT_FP = "dcx:Placeholder_Cout"
    tds = "Package_SON:Infineon_PG-TDSON-8_6.15x5.15mm"

    out: list[Part] = []
    # Row 1 -- the four transformers, one per 3:1:1 set, evenly spaced so the
    # four secondary loops are identical.  Symmetry is a current-sharing
    # argument, not decoration.
    for i, x in enumerate((20.0, 58.0, 96.0, 134.0), start=1):
        out.append(Part(f"T{i}", "3:1:1 ELP32", mag_w, mag_d, mag_h, x, 20.0,
                        "generated-json", elp32))
    # Row 2 -- primary side, left to right in power-flow order.
    out.append(Part("Lr", "1.0 uH", mag_w, mag_d, mag_h, 20.0, 52.0,
                    "generated-json", elp32,
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
    for i, x0 in enumerate((14.0, 52.0, 90.0, 128.0), start=1):
        out.append(Part(f"SR{i}A", "BSC010N04LS6", 7.36, 5.64, 1.0, x0, 82.0,
                        "kicad-library", tds))
        out.append(Part(f"SR{i}B", "BSC010N04LS6", 7.36, 5.64, 1.0, x0 + 10.0, 82.0,
                        "kicad-library", tds))
    # Row 4 -- the output bank, one row between the SRs and the busbar.
    for i in range(cout["n"]):
        out.append(Part(f"C{100 + i}", "470 uF 2.5 V", 7.3, 4.3, cout["height_mm"],
                        14.0 + 8.2 * i, 98.0, "generated-json", COUT_FP,
                        note="height from cout_bank.json; case size assumed"))
    # Row 5 -- the output busbar, last so the 100 A leaves at the board edge.
    out.append(Part("J_OUT", "20x2 mm bar", bar["length_mm"], bar["width_mm"],
                    bar["thickness_mm"], 100.0, 116.0, "generated-json",
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
def report() -> dict:
    height = _load("magnetics/magnetics_design.json")["height"]
    flat = height["flat_no_pocket"]
    clamp = height["with_0.5mm_clamp"]
    magnetics = sorted(p.ref for p in PARTS if p.footprint == ELP32_FP)
    gap, ga, gb = min_gap_mm()
    w, d = board_rect()
    return {
        "status": "placement only - no nets, no routing, unconnected pads are expected",
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
        "provisional": sorted(p.ref for p in PARTS if p.evidence == "PROVISIONAL"),
        "land_pattern_provisional": sorted(
            p.ref for p in PARTS
            if p.evidence == "datasheet" or "land pattern" in p.note.lower()),
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


def _outline_footprint(name: str, w: float, d: float, descr: str, pads: list[tuple[float, float]]) -> str:
    """A rectangular through-hole footprint: fab outline, courtyard at +0.25 mm,
    and one pad per terminal the caller names.  Deliberately minimal -- there is
    no copper land pattern here because the part is not selected."""
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
    for i, (px, py) in enumerate(pads, start=1):
        s += _pad(str(i), px, py, 2.0, 2.0)
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
        "ELP32_31.75x25.4.kicad_mod": _outline_footprint(
            "ELP32_31.75x25.4", w, d,
            "TDK ELP32 (B66287) 3:1:1 planar, 31.75x25.4x9.5 mm. "
            "Terminal positions PROVISIONAL: the winding exit is not drawn yet.",
            [(-10.0, 0.0), (10.0, 0.0)]),
        "Busbar_20x2.kicad_mod": _outline_footprint(
            "Busbar_20x2", bar["length_mm"], bar["width_mm"],
            "Output copper bar 80x20x2 mm. Contact resistance UNVERIFIED.",
            [(-35.0, 0.0), (35.0, 0.0)]),
        "Placeholder_18x6.kicad_mod": _outline_footprint(
            "Placeholder_18x6", 18, 6, "PROVISIONAL - Cr film capacitor, no part selected",
            [(-7.0, 0.0), (7.0, 0.0)]),
        "Placeholder_20x15.kicad_mod": _outline_footprint(
            "Placeholder_20x15", 20, 15, "PROVISIONAL - over-current CT, no part selected",
            [(-8.0, 0.0), (8.0, 0.0)]),
        "Placeholder_10x10.kicad_mod": _outline_footprint(
            "Placeholder_10x10", 10, 10, "PROVISIONAL - 48 V input terminal, no part selected",
            [(-2.54, 0.0), (2.54, 0.0)]),
        "Placeholder_12x12.kicad_mod": _outline_footprint(
            "Placeholder_12x12", 12, 12, "PROVISIONAL - control area, no layout done",
            []),
        "Placeholder_SON_5x6.kicad_mod": _outline_footprint(
            "Placeholder_SON_5x6", 5.00, 6.10,
            "PROVISIONAL land pattern - CSD19531Q5A (VSONP DQJ): body 5.00x6.10 from "
            "datasheet p9, but the recommended board pads are a figure, not text, and "
            "are not reproduced here",
            [(-1.5, -2.5), (-1.5, 2.5)]),
        "Placeholder_Cout.kicad_mod": _outline_footprint(
            "Placeholder_Cout", 7.3, 4.3,
            "Bulk output capacitor: height 1.9 mm is from cout_bank.json, the "
            "7.3x4.3 case size is PROVISIONAL",
            [(-2.0, 0.0), (2.0, 0.0)]),
    }
    return files


FP_TABLE = '(fp_lib_table\n  (version 7)\n  (lib (name "dcx")(type "KiCad")' \
           '(uri "${KIPRJMOD}/dcx.pretty")(options "")(descr "generated placement footprints"))\n)\n'


def project_file() -> str:
    """Same trap as the schematic side: without a ``.kicad_pro`` next to the
    board, ``kicad-cli`` never loads ``fp-lib-table``, so every ``dcx:``
    footprint is reported as an unknown library -- and an unresolved footprint
    has no courtyard, so DRC silently stops checking it.

    ``tracks``/``net_settings`` are empty on purpose: this file has no nets."""
    return json.dumps({
        "board": {}, "boards": [], "cvpcb": {}, "erc": {},
        "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
        "meta": {"filename": "power_stage_placement.kicad_pro", "version": 1},
        "net_settings": {}, "pcbnew": {"page_layout_descr_file": ""},
        "schematic": {"legacy_lib_dir": "", "legacy_lib_list": []},
        "sheets": [], "text_variables": {},
    }, indent=2) + "\n"


# ---------------------------------------------------------------- board file
def _embed(mod_text: str, lib_id: str, ref: str, value: str, x: float, y: float, rot: float) -> str:
    """Turn a ``.kicad_mod`` body into a placed footprint instance.

    A ``.kicad_pcb`` carries the geometry inline, so the library file is copied
    in rather than referenced.  Four things change: the library id, the
    placement, the reference, and every uuid (two instances sharing a uuid make
    KiCad pick one at random when the file is opened)."""
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
    return "\t" + text.strip() + "\n"


def board_file(libs: dict[str, str]) -> str:
    w, d = board_rect()
    mods = {f"dcx:{Path(name).stem}": text for name, text in libs.items()}
    out = [
        "(kicad_pcb\n\t(version 20260206)\n\t(generator \"main_board_mechanical\")\n"
        "\t(generator_version \"10.0\")\n\t(general (thickness 1.6))\n"
        "\t(paper \"A3\")\n\t(title_block\n"
        "\t\t(title \"DCX 48V-2V 100A - A5 1:1 power-stage placement\")\n"
        "\t\t(comment 1 \"PLACEMENT ONLY - no nets, no routing\")\n"
        "\t\t(comment 2 \"PROVISIONAL outlines: CT, Cr, J_IN, U2 area, Cout case size\")\n"
        "\t)\n"
        "\t(layers\n"
        '\t\t(0 "F.Cu" signal)\n\t\t(31 "B.Cu" signal)\n'
        '\t\t(36 "B.SilkS" user "B.Silkscreen")\n\t\t(37 "F.SilkS" user "F.Silkscreen")\n'
        '\t\t(44 "Edge.Cuts" user)\n\t\t(46 "B.CrtYd" user "B.Courtyard")\n'
        '\t\t(47 "F.CrtYd" user "F.Courtyard")\n'
        '\t\t(48 "B.Fab" user)\n\t\t(49 "F.Fab" user)\n\t)\n'
        "\t(setup (pad_to_mask_clearance 0))\n"
    ]
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
                                 part.x, part.y, part.rot).strip() + "\n")
    out.append(")\n")
    return "".join(out)


def _stock_footprint(lib_id: str) -> str:
    lib, name = lib_id.split(":", 1)
    path = KICAD_SHARE / "footprints" / f"{lib}.pretty" / f"{name}.kicad_mod"
    if not path.exists():
        raise SystemExit(f"{lib_id} is neither generated nor in {KICAD_SHARE}")
    return path.read_text(encoding="utf-8")


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
    if not KICAD_CLI.exists():
        return []
    svg = out_dir / "placement_1to1.svg"
    png = out_dir / "placement_top.png"
    subprocess.run([str(KICAD_CLI), "pcb", "export", "svg", "--mode-single", "--scale", "1",
                    "--page-size-mode", "2", "-l", "F.Fab,Edge.Cuts,F.CrtYd,F.SilkS",
                    "-o", str(svg), str(board)], check=False, capture_output=True)
    subprocess.run([str(KICAD_CLI), "pcb", "render", "--side", "top", "-w", "1400",
                    "-h", "1200", "--background", "opaque", "-o", str(png), str(board)],
                   check=False, capture_output=True)
    return [svg, png]


def violations(path: Path | None = None) -> list[dict]:
    path = path or OUT / "drc.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("violations", [])


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
    if not KICAD_CLI.exists():
        print("kicad-cli not installed - skipping DRC and drawings")
        return
    draw()
    subprocess.run([str(KICAD_CLI), "pcb", "drc", "--format", "json", "--severity-all",
                    "-o", str(OUT / "drc.json"), str(board)], check=False, capture_output=True)
    vs = violations()
    errors = [v for v in vs if v["severity"] == "error"]
    unknown = [v for v in vs if v["type"] == "lib_footprint_issues"]
    print(f"DRC: {len(vs)} violations, {len(errors)} errors, {len(unknown)} unknown-footprint")
    for v in (errors + unknown)[:5]:
        print(f"  {v['severity']} {v['type']}: {v['description']}")
    if errors or unknown:
        raise SystemExit("DRC is not clean -- a placement study may leave pads unconnected, "
                         "but a courtyard collision or an unresolved library is a real defect")


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

"""Assembly and DNP drawing for the single-pair SR validation board.

Why this file exists
--------------------
``fab/`` already carries gerbers, drill, a position file and a manifest.  The
position file is what a placer reads; it says *where* a part goes and, with
``--exclude-dnp``, which parts to skip.  What it cannot say is *which pads are
supposed to stay empty*, because the parts that are absent by design look
exactly like parts that were never ordered.

This drawing is the other half: a 1:1 plan view of every placed part, numbered
in table order, with the ten do-not-populate parts hatched in red, plus a table
that names each ref, its value, its footprint and its status.  A technician can
check orientation against it and a checker can confirm that ``R47`` is empty on
purpose rather than missing.

What it is not
--------------
Not an approval.  ``hardware_built`` and ``fabrication_approved`` are false and
the drawing says so on its face: it describes copper that has passed DRC, not a
board that has passed a thermal, EMC or first-article review.

Why an SVG and not a kicad-cli plot
-----------------------------------
``kicad-cli pcb export svg`` draws the silkscreen, which carries the reference
text wherever the layout happened to leave it -- some of it overlapping, and
none of it saying "DNP".  Generating the drawing from the same ``Placed`` table
the board is built from means the drawing and the copper cannot disagree: both
come from one list.  It also keeps the toolchain free of KiCad, which the
README's vendored-footprint rule already asks for.

Usage:
    python tools/assembly_drawing.py            # rewrite fab/assembly.svg
    python tools/assembly_drawing.py --check    # fail if the committed file is stale
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from xml.sax.saxutils import escape

import make_sr_fault_board_pcb as board

OUT = board.FAB / "assembly.svg"

# A4 portrait, millimetres.  The ``width``/``height`` attributes are what make a
# print measure true; a viewBox alone prints at the reader's DPI.
PAGE_W_MM = 210.0
PAGE_H_MM = 297.0
BOARD_W_MM = board.BOARD_W_MM
BOARD_D_MM = board.BOARD_D_MM
OFFSET_X_MM = 39.0          # (210 - 132) / 2
OFFSET_Y_MM = 14.0

TABLE_TOP_MM = 144.0
ROW_MM = 4.0
ROWS_PER_COLUMN = 36
COLUMN_X_MM = (22.0, 110.0)
# Offsets inside one table column: ref, value, footprint, status.
COL_DX_MM = (0.0, 18.0, 48.0, 74.0)

CALL_R_MM = 1.0             # callout bubble radius


def _short(lib_id: str) -> str:
    return lib_id.split(":", 1)[-1]


def _callout(p, part, index: int, offset_x: float = OFFSET_X_MM) -> list[str]:
    """One part: its courtyard box, a numbered callout, and a DNP mark."""
    x0, y0, x1, y1 = p.rect
    w, d = max(x1 - x0, 0.4), max(y1 - y0, 0.4)
    cx, cy = x0 + w / 2 + offset_x, y0 + d / 2 + OFFSET_Y_MM
    cls = "part dnp" if part.dnp else "part"
    lines = [f'  <g class="{cls}" data-ref="{escape(part.ref)}">',
             f'    <rect class="body" x="{x0 + offset_x:g}" y="{y0 + OFFSET_Y_MM:g}"'
             f' width="{w:g}" height="{d:g}"/>']
    # A bubble instead of live text: an 0805 body is 1.6 x 0.8 mm and the
    # reference would not be legible at 1:1 wherever it was put.
    lines += [f'    <circle class="callout-bubble" cx="{cx:g}" cy="{cy:g}" r="{CALL_R_MM:g}"/>',
              f'    <text class="callout" x="{cx:g}" y="{cy + 0.55:g}">{index}</text>']
    if part.dnp:
        lines.append(f'    <text class="dnp-mark" x="{cx:g}" y="{y1 + OFFSET_Y_MM + 1.5:g}">DNP</text>')
    lines.append("  </g>")
    return lines


def _row(index: int, ref: str, part, x: float, y: float) -> str:
    cls = "row dnp" if part.dnp else "row"
    cells = [f'<text class="idx" x="{x + COL_DX_MM[0] - 4:g}" y="{y:g}">{index}</text>',
             f'<text class="row" x="{x + COL_DX_MM[0]:g}" y="{y:g}">{escape(ref)}</text>',
             f'<text class="val" x="{x + COL_DX_MM[1]:g}" y="{y:g}">{escape(part.value)}</text>',
             f'<text class="fp" x="{x + COL_DX_MM[2]:g}" y="{y:g}">{escape(_short(part.footprint))}</text>']
    status = f'<text class="row dnp" x="{x + COL_DX_MM[3]:g}" y="{y:g}">{escape(ref)}</text>' if part.dnp else \
             f'<text class="row" x="{x + COL_DX_MM[3]:g}" y="{y:g}">PLACE</text>'
    cells.append(status)
    return f'  <g class="{cls}">' + "".join(cells) + "</g>"


DEFAULT_TITLE = ("SR fault validation board (PCB-FAB-01) -- assembly and DNP "
                 "drawing, 1:1 top side")
# The <title> element is the SVG's document title (window/tab text, screen
# readers).  It is separate from the printed heading above: that one carries the
# board number and the scale, this one is the short name, and the committed SR
# drawing has said exactly this since it was first generated.
DEFAULT_DOC_TITLE = "SR fault validation board -- assembly and DNP drawing"
DEFAULT_FOOTPRINT_NOTE = ("Footprints are vendored from hardware/stock_footprints "
                          "(sha256 in PROVENANCE.md) except dcx:BSC010N04LS6, which is "
                          "drawn from the datasheet land pattern.")


def svg(placed: list, table: dict | None = None, *,
        title: str = DEFAULT_TITLE,
        doc_title: str = DEFAULT_DOC_TITLE,
        board_mm: tuple[float, float] | None = None,
        footprint_note: str = DEFAULT_FOOTPRINT_NOTE) -> str:
    """The drawing, as text.  ``placed`` and ``table`` must come from the board
    generator -- a second part list would be a second source of truth.

    ``title``/``doc_title``/``board_mm``/``footprint_note`` exist so a second
    board can reuse the sheet instead of growing a copy of it.  Their defaults
    are the SR board's own values, which keeps ``fab/assembly.svg``
    byte-identical: a parameterised header must not silently move the committed
    drawing.  ``doc_title`` is the ``<title>`` element; leaving it at the
    default would put the SR board's name inside another board's file, where a
    screen reader and every grep would still find it.
    """
    table = table if table is not None else board._table()
    w_mm, d_mm = board_mm if board_mm is not None else (BOARD_W_MM, BOARD_D_MM)
    offset_x = (PAGE_W_MM - w_mm) / 2
    order = sorted((p for p in placed if p.ref in table), key=lambda p: board._natural(p.ref))
    dnp = [r for r, part in table.items() if part.dnp]
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{PAGE_W_MM:g}mm" '
        f'height="{PAGE_H_MM:g}mm" viewBox="0 0 {PAGE_W_MM:g} {PAGE_H_MM:g}">',
        f'  <title>{escape(doc_title)}</title>',
        "  <style>",
        "    text{font-family:'DejaVu Sans',Arial,sans-serif;fill:#1a1a1a}",
        "    .page{fill:#ffffff} .outline{fill:none;stroke:#111;stroke-width:0.35}",
        "    .body{fill:#f2f2f2;stroke:#444;stroke-width:0.15}",
        "    .part.dnp .body{fill:#f7c6c6;stroke:#b00020;stroke-width:0.25;stroke-dasharray:0.6 0.4}",
        "    .callout-bubble{fill:#fff;stroke:#444;stroke-width:0.12}",
        "    .part.dnp .callout-bubble{stroke:#b00020}",
        "    .callout{font-size:1.1px;text-anchor:middle}",
        "    .dnp-mark{font-size:0.9px;text-anchor:middle;fill:#b00020;font-weight:bold}",
        "    .title{font-size:4px;font-weight:bold} .note{font-size:2.1px}",
        "    .hdr{font-size:2px;font-weight:bold;fill:#333}",
        "    .row,.idx,.val,.fp{font-size:1.9px}",
        "    .row.dnp{fill:#b00020;font-weight:bold} .idx{fill:#666;text-anchor:end}",
        "  </style>",
        f'  <rect class="page" x="0" y="0" width="{PAGE_W_MM:g}" height="{PAGE_H_MM:g}"/>',
        f'  <text class="title" x="22" y="9">{escape(title)}</text>',
        f'  <rect class="outline" x="{offset_x:g}" y="{OFFSET_Y_MM:g}" '
        f'width="{w_mm:g}" height="{d_mm:g}"/>',
    ]
    for index, p in enumerate(order, start=1):
        lines += _callout(p, table[p.ref], index, offset_x)
    notes = [
        f"  <text class=\"note\" x=\"22\" y=\"114\">Scale 1:1 at A4. All {len(order)} placements "
        f"are on F.Cu (top side); the board is single-sided assembly.</text>",
        f"  <text class=\"note\" x=\"22\" y=\"119\">{len(dnp)} parts are DNP -- hatched red, marked "
        f"on the board and listed in red below. Their lands stay bare; they are "
        f"excluded from the position file.</text>",
        "  <text class=\"note\" x=\"22\" y=\"124\">Not an approval: hardware_built and "
        "fabrication_approved are false. DRC covers copper only -- no thermal, EMC or "
        "first-article review has been done.</text>",
        f"  <text class=\"note\" x=\"22\" y=\"129\">{escape(footprint_note)}</text>",
    ]
    lines += notes
    header = ["Ref", "Value", "Footprint", "Status"]
    for column, x in enumerate(COLUMN_X_MM):
        for label, dx in zip(header, (COL_DX_MM[0], COL_DX_MM[1], COL_DX_MM[2], COL_DX_MM[3])):
            if column and label == header[3]:
                continue          # the status column is the last one only
            lines.append(f'  <text class="hdr" x="{x + dx:g}" y="{TABLE_TOP_MM - 4:g}">'
                         f'{escape(label)}</text>')
    for index, p in enumerate(order, start=1):
        column = (index - 1) // ROWS_PER_COLUMN
        row = (index - 1) % ROWS_PER_COLUMN
        lines.append(_row(index, p.ref, table[p.ref], COLUMN_X_MM[column],
                          TABLE_TOP_MM + row * ROW_MM))
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def write(path: Path | None = None) -> Path:
    path = path or OUT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg(board.placement()), encoding="utf-8", newline="\n")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="fail if the committed drawing differs from a fresh one")
    args = parser.parse_args(argv)
    fresh = svg(board.placement())
    if args.check:
        if not OUT.is_file():
            print(f"{OUT} is missing -- run without --check", file=sys.stderr)
            return 1
        if OUT.read_text(encoding="utf-8") != fresh:
            print(f"{OUT} is stale -- rerun without --check", file=sys.stderr)
            return 1
        print(f"{OUT}: current")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(fresh, encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Digitise the CSD19531Q5A (Q5A, 5x6 mm VSON) land and stencil from the datasheet.

Why this exists
---------------
QH and QL on the A5 main board are the last two parts whose land pattern is a
placeholder box.  The datasheet *does* draw the recommended land and the
recommended stencil, but as figures rather than as text, so a footprint typed in
by eye from a picture is a number nobody can check.  It is extracted instead:
the drawings are vector art, and every dimension the model consumes is printed
on the sheet -- the land as a MIN/MAX table (sect. 7.2), the stencil as callouts
on the figure itself (sect. 7.3), including the inch equivalents in parentheses.

How the two figures are read
----------------------------
They are separate pages with separate scales, so each is fitted on its own:

* **sect. 7.2 land.**  Copper outlines are 1.0 pt strokes, dimension lines 0.5 pt.
  The drain is a comb -- a body rectangle plus four fingers that reach the left
  edge -- and the source/gate side is four separate rectangles.  The horizontal
  edge levels (eight of them) chain into four 0.65 mm bands and three 0.62 mm
  gaps, which is exactly 4.46 = F2 = F3 = F11.
* **sect. 7.3 stencil.**  The eight lead apertures are single quads; the four
  block apertures are closed four-sided loops.  All twelve are found by geometry,
  not by drawing index, so a redrawn figure fails the count instead of silently
  moving apertures.

Both figures print pin labels (1, 4, 5, 8) beside the pads they belong to, so
the pinout is measured rather than remembered: the left column is pins 5-8 top
to bottom and the right column is 4 down to 1.

Why the median of ratios, not a least-squares fit
-------------------------------------------------
A through-origin least squares is dragged by the two longest spans: a drafting
rounding on the overall width moves every other dimension, and on the stencil
figure it pushed the worst residual to 11.3 um where the median leaves 1.8 um.
Drafting rounding is not noise around a line, it is a floor of one grid step, so
the median is the right estimator -- and the leftover error is reported rather
than modelled away.

What this tool does NOT decide
------------------------------
Listed in ``limitations``: the exposed-pad number (9 is the symbol's, not the
sheet's), the mask expansion and the courtyard (this sheet draws neither -- both
are carried from the project's other land-pattern work), the 17.5 um by which
each lead aperture sits off its own pad centre (the stencil figure is symmetric
about the land's outer edges while the copper widths differ, 0.63 vs 0.70), and
the silkscreen, which is not on either figure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PDF = ROOT / "references" / "datasheets" / "csd19531q5a.pdf"
DEFAULT_JSON = ROOT / "design" / "v3" / "pcb" / "csd19531q5a_land.json"

PACKAGE_PAGE = 8
LAND_PAGE = 9
STENCIL_PAGE = 10
PACKAGE_TITLE = "Q5A Package Dimensions"
LAND_TITLE = "Recommended PCB Pattern"
STENCIL_TITLE = "Recommended Stencil Opening"

LAND_STROKE = 0.999779999256134
STENCIL_STROKE = 0.5186

LAND_REGION = (60.0, 90.0, 290.0, 250.0)      # x0, y0, x1, y1 of the sect. 7.2 figure
STENCIL_REGION = (140.0, 90.0, 510.0, 378.0)  # sect. 7.4 tape-and-reel starts below this
MIL_MM = 0.0254            # both figures are drafted on a 1/1000 inch grid
LAND_TOL_MM = MIL_MM       # worst land residual: the overall height, 21 um long
STENCIL_TOL_MM = 0.005     # the stencil figure lands inside 2 um
PAD_OVERLAP = 0.125        # a finger is pushed into its body so KiCad sees one land
MASK_EXPANSION = 0.05      # not on this sheet; the value the other land uses
COURTYARD = 0.25
BODY_PIN = "9"             # the exposed pad: the symbol's pin 9, not a printed one

# Every row the land table prints.  F3/F8/F9/F11 repeat other rows and are used
# as cross-checks rather than as model inputs.
LAND_USED = ("F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11")

# The printed millimetre callouts the stencil model consumes.  Values repeat on
# the sheet (four identical lead openings), so this is a set.
STENCIL_USED = (4.310, 3.020, 1.585, 1.235, 1.570, 1.270, 0.615, 1.105, 0.620,
                0.500, 0.385)


# ---------------------------------------------------------------- PDF access
def _flat(text: str) -> str:
    """Text with the furniture's soft separators turned into ordinary spaces."""
    return " ".join(re.sub(r"[\x00-\x1f]", " ", text).split())


def _open(pdf: Path):
    try:
        import fitz
    except ImportError as exc:      # pragma: no cover - depends on the machine
        raise SystemExit("PyMuPDF is needed only to regenerate this JSON.  "
                         "pip install pymupdf, or use the committed file.") from exc
    return fitz.open(pdf)


def _page(doc, index: int, title: str):
    page = doc[index]
    if title not in _flat(page.get_text("text")):
        raise SystemExit(f"page {index + 1} is not '{title}'; the PDF moved, so the "
                         f"page index is wrong")
    return page


def _labels(page) -> list[tuple[str, tuple[float, float, float, float]]]:
    out: list[tuple[str, tuple[float, float, float, float]]] = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                out.append((span["text"].strip(), tuple(span["bbox"])))
    return out


# ---------------------------------------------------------------- the tables
def _land_table(page) -> dict[str, dict]:
    """sect. 7.2: DIM | MILLIMETRES MIN MAX | INCHES MIN MAX, one row per F-number."""
    lines = [s.strip() for s in page.get_text("text").splitlines()]
    try:
        start = lines.index("DIM") + 5
    except ValueError:
        raise SystemExit("page 10 has no DIM header; the land table moved") from None
    out: dict[str, dict] = {}
    for i in range(start, len(lines) - 4, 5):
        key = lines[i]
        if not re.fullmatch(r"F\d{1,2}", key):
            break
        mm_min, mm_max, in_min, in_max = (float(lines[i + k]) for k in range(1, 5))
        out[key] = {"min": mm_min, "max": mm_max, "inch": [in_min, in_max]}
    if sorted(out) != sorted(LAND_USED):
        raise SystemExit(f"the land table has {sorted(out)}, not {sorted(LAND_USED)}")
    return out


def _package_table(doc) -> dict[str, dict]:
    """sect. 7.1: DIM | MIN NOM MAX, one row per dimension letter."""
    lines = [s.strip() for s in doc[PACKAGE_PAGE].get_text("text").splitlines()]
    try:
        start = lines.index("DIM") + 4
    except ValueError:
        raise SystemExit("page 9 has no DIM header; the package table moved") from None
    out: dict[str, dict] = {}
    for i in range(start, len(lines) - 3, 4):
        key = lines[i]
        if not re.fullmatch(r"[A-Za-z]\d{0,2}", key):
            break
        vals = [None if lines[i + k] in ("-", "–", "—") else float(lines[i + k])
                for k in range(1, 4)]
        out[key] = dict(zip(("min", "nom", "max"), vals))
    for need in ("D1", "E", "A"):
        if need not in out:
            raise SystemExit(f"page 9 no longer lists {need}")
    return out


# ---------------------------------------------------------------- geometry
def _strokes(page, width: float, region: tuple, tol: float = 5e-3) -> list:
    x0, y0, x1, y1 = region
    out = []
    for drawing in page.get_drawings():
        got = drawing["width"]
        if got is None or abs(got - width) > tol:
            continue
        r = drawing["rect"]
        if r.x0 < x0 - 1.0 or r.y0 < y0 - 1.0 or r.x1 > x1 + 1.0 or r.y1 > y1 + 1.0:
            continue
        out.append(drawing)
    return out


def _segments(drawings) -> list[tuple[float, float, float, float]]:
    out = []
    for drawing in drawings:
        for item in drawing["items"]:
            if item[0] == "l":
                out.append((item[1].x, item[1].y, item[2].x, item[2].y))
    return out


def _rects(drawings) -> list[list[float]]:
    out = []
    for drawing in drawings:
        if len(drawing["items"]) == 1 and drawing["items"][0][0] == "re":
            r = drawing["rect"]
            out.append([r.x0, r.y0, r.x1, r.y1])
    return out


def _components(segments) -> list[list[tuple[float, float, float, float]]]:
    """Group segments that share an endpoint -- one closed loop comes out whole."""
    parent: dict[tuple[float, float], tuple[float, float]] = {}

    def find(a):
        while parent.setdefault(a, a) != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for x0, y0, x1, y1 in segments:
        a = (round(x0, 2), round(y0, 2))
        b = (round(x1, 2), round(y1, 2))
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    groups: dict[tuple[float, float], list] = {}
    for seg in segments:
        groups.setdefault(find((round(seg[0], 2), round(seg[1], 2))), []).append(seg)
    return list(groups.values())


def _loops(segments) -> list[list[float]]:
    """Axis-aligned four-sided loops: two distinct x values, two distinct y values."""
    out = []
    for group in _components(segments):
        if len(group) < 4:
            continue
        xs = sorted({round(v, 2) for s in group for v in (s[0], s[2])})
        ys = sorted({round(v, 2) for s in group for v in (s[1], s[3])})
        if len(xs) != 2 or len(ys) != 2:
            continue
        out.append([xs[0], ys[0], xs[1], ys[1]])
    return out


# ---------------------------------------------------------------- measurement
def _land_geometry(page) -> dict:
    drawings = _strokes(page, LAND_STROKE, LAND_REGION)
    segments = _segments(drawings)
    pads = sorted(_rects(drawings), key=lambda r: r[1])
    verts = sorted({round(s[0], 2) for s in segments if abs(s[0] - s[2]) < 1e-6})
    horiz = sorted({round(s[1], 2) for s in segments if abs(s[1] - s[3]) < 1e-6})
    if len(verts) != 3:
        raise SystemExit(f"the comb has {len(verts)} vertical levels, not 3: {verts}")
    if len(horiz) != 8:
        raise SystemExit(f"the comb has {len(horiz)} horizontal levels, not 8: {horiz}")
    if len(pads) != 4:
        raise SystemExit(f"the source column has {len(pads)} lands, not 4")
    bands = [(horiz[2 * i], horiz[2 * i + 1]) for i in range(4)]
    gaps = [(horiz[2 * i + 1], horiz[2 * i + 2]) for i in range(3)]
    return {"segments": segments, "pads": pads, "verts": verts, "horiz": horiz,
            "x0": verts[0], "shoulder": verts[1], "body_right": verts[2],
            "pad_right": max(p[2] for p in pads), "bands": bands, "gaps": gaps}


def _stencil_geometry(page) -> dict:
    drawings = _strokes(page, STENCIL_STROKE, STENCIL_REGION)
    quads = sorted(([d["rect"].x0, d["rect"].y0, d["rect"].x1, d["rect"].y1]
                    for d in drawings
                    if len(d["items"]) == 1 and d["items"][0][0] == "qu"),
                   key=lambda r: (r[0], r[1]))
    loops = sorted(_loops(_segments(drawings)), key=lambda r: (r[0], r[1]))
    if len(quads) != 8:
        raise SystemExit(f"the stencil has {len(quads)} lead openings, not 8")
    if len(loops) != 4:
        raise SystemExit(f"the stencil has {len(loops)} block openings, not 4")
    xs = [v for r in quads + loops for v in (r[0], r[2])]
    ys = [v for r in quads + loops for v in (r[1], r[3])]
    mid = (min(xs) + max(xs)) / 2
    # Sorted by x alone, both left blocks come out before both right ones, so
    # ``blocks[1]`` is the left-bottom block and not the right one.  Split first.
    blocks = {"left": [r for r in loops if r[2] < mid],
              "right": [r for r in loops if r[0] >= mid]}
    if len(blocks["left"]) != 2 or len(blocks["right"]) != 2:
        raise SystemExit(f"block openings split {len(blocks['left'])}/"
                         f"{len(blocks['right'])}, not 2/2")
    return {"leads": quads, "blocks": blocks,
            "datum": (mid, (min(ys) + max(ys)) / 2)}


def _columns(geom: dict) -> dict[str, list]:
    """The eight lead openings split into their left and right columns, top down."""
    mid = (geom["leads"][0][0] + geom["leads"][-1][0]) / 2
    left = sorted((r for r in geom["leads"] if r[2] < mid), key=lambda r: r[1])
    right = sorted((r for r in geom["leads"] if r[2] >= mid), key=lambda r: r[1])
    if len(left) != 4 or len(right) != 4:
        raise SystemExit(f"lead openings split {len(left)}/{len(right)}, not 4/4")
    return {"left": left, "right": right}


# ---------------------------------------------------------------- the scale
def _anchor(name: str, drawn_pt: float, printed_mm: float, note: str) -> dict:
    return {"name": name, "drawn_pt": round(drawn_pt, 3), "printed_mm": printed_mm,
            "pt_per_mm": round(drawn_pt / printed_mm, 4),
            "usable": printed_mm >= 0.3, "note": note}


def _fit(anchors: list[dict]) -> tuple[float, float]:
    """Median of drawn/printed, and the worst residual left behind."""
    good = [a for a in anchors if a["usable"]]
    scale = 1.0 / statistics.median(a["pt_per_mm"] for a in good)
    return scale, max(abs(a["drawn_pt"] * scale - a["printed_mm"]) for a in good)


def _land_anchors(geom: dict, table: dict) -> list[dict]:
    v = lambda key: table[key]["min"]  # noqa: E731
    band = geom["bands"][0]
    return [
        _anchor("F1", geom["pad_right"] - geom["x0"], v("F1"), "tooth tip to pad outer edge"),
        _anchor("F2", geom["horiz"][-1] - geom["horiz"][0], v("F2"), "overall land height"),
        _anchor("F4", band[1] - band[0], v("F4"), "pad band height"),
        _anchor("F5", geom["gaps"][0][1] - geom["gaps"][0][0], v("F5"), "gap between bands"),
        _anchor("F6", geom["shoulder"] - geom["x0"], v("F6"), "tooth depth"),
        _anchor("F7", geom["pads"][0][2] - geom["pads"][0][0], v("F7"), "source pad width"),
        _anchor("F10", geom["body_right"] - geom["x0"], v("F10"),
                "tooth tip to the body's far edge"),
    ]


def _stencil_anchors(geom: dict) -> list[dict]:
    cols = _columns(geom)
    cx, cy = geom["datum"]
    left, right = cols["left"], cols["right"]
    lb, rb = geom["blocks"]["left"], geom["blocks"]["right"]
    return [
        _anchor("lead width", left[0][2] - left[0][0], 0.500, "one lead opening"),
        _anchor("lead height", left[0][3] - left[0][1], 0.500, "one lead opening"),
        _anchor("lead pitch", left[1][1] - left[0][1], 1.270, "row to row"),
        _anchor("overall height", left[-1][3] - left[0][1], 4.310, "outer edges"),
        _anchor("half width", cx - left[0][0], 3.020, "centre line to outer edge"),
        _anchor("centre to lead", left[2][1] - cy, 0.385,
                "centre line to the inner lead edge"),
        _anchor("left block", lb[0][2] - lb[0][0], 1.585, "block width"),
        _anchor("right block", rb[0][2] - rb[0][0], 1.235, "block width"),
        _anchor("block height", lb[0][3] - lb[0][1], 1.570, "block height"),
        _anchor("left gap", lb[0][0] - left[0][2], 0.615, "lead to block"),
        _anchor("right gap", right[0][0] - rb[0][2], 1.105, "block to lead"),
        _anchor("row gap", lb[1][1] - lb[0][3], 0.620, "between the block rows"),
    ]


# ---------------------------------------------------------------- the pinout
def _pin_map(page, region: tuple, x0: float, x1: float,
             bands) -> dict[tuple[str, int], int]:
    """Printed pin number -> (column, band), from where the label sits.

    ``region`` matters: the dimension tables below the figure also print bare
    digits (F10's maximum is ``5``), and those sit outside it.  Without the box
    the ``5`` lands in the right column and the pinout check fires.
    """
    out: dict[tuple[str, int], int] = {}
    for text, box in _labels(page):
        if not re.fullmatch(r"[1-8]", text):
            continue
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        if not (region[0] <= cx <= region[2] and region[1] <= cy <= region[3]):
            continue
        side = "left" if cx < x0 else "right" if cx > x1 else None
        if side is None:
            continue
        band = min(range(len(bands)),
                   key=lambda i: abs((bands[i][0] + bands[i][1]) / 2 - cy))
        out[(side, band)] = int(text)
    return out


def _column(pins: dict[tuple[str, int], int], side: str) -> list[int]:
    """Both ends of a column are printed; the middle follows from the step."""
    ends = {band: pin for (s, band), pin in pins.items() if s == side}
    if sorted(ends) != [0, 3]:
        raise SystemExit(f"the {side} column prints pins at bands {sorted(ends)}, not 0 and 3")
    step = (ends[3] - ends[0]) // 3
    if ends[0] + step * 3 != ends[3]:
        raise SystemExit(f"the {side} column prints {ends}, which is not evenly spaced")
    return [ends[0] + step * i for i in range(4)]


# ---------------------------------------------------------------- the model
def _bands(height: float, band: float, gap: float) -> list[tuple[float, float]]:
    """Four pad bands and the three gaps between them, top down, y up."""
    out, top = [], height / 2
    for i in range(7):
        step = band if i % 2 == 0 else gap
        out.append((top, top - step))
        top -= step
    if abs(top + height / 2) > 1e-9:
        raise SystemExit(f"4x{band} + 3x{gap} = {height} is not arithmetically true")
    return [out[0], out[2], out[4], out[6]]


def model(table: dict, package: dict, pins: dict) -> dict:
    v = lambda key: table[key]["min"]  # noqa: E731
    half, height = v("F1") / 2, v("F2")
    tooth, pad_w = v("F6"), v("F7")
    bands = _bands(height, v("F4"), v("F5"))
    body_x0, body_x1 = -half + tooth, -half + v("F10")

    body = {"number": BODY_PIN, "kind": "drain_body", "layers": ["F.Cu"],
            "rect": [body_x0, -height / 2, body_x1, height / 2]}
    teeth = [{"number": str(pins["left"][i]), "kind": "drain_tooth", "layers": ["F.Cu"],
              "rect": [-half, low, body_x0, high]} for i, (high, low) in enumerate(bands)]
    right = [{"number": str(pins["right"][i]), "kind": "source_pad", "layers": ["F.Cu"],
              "rect": [half - pad_w, low, half, high]} for i, (high, low) in enumerate(bands)]
    copper = [body] + teeth + right

    # Stencil: every number below is printed on the sheet.  The lead columns sit
    # symmetrically 3.020 from the centre line; the blocks hang off them.
    open_w, half_w = 0.500, 3.020
    paste = []
    for side, sign in (("left", -1.0), ("right", 1.0)):
        inner, outer = sign * (half_w - open_w), sign * half_w
        for i, (high, low) in enumerate(bands):
            mid = (high + low) / 2
            paste.append({"kind": "paste_lead", "side": side, "band": i,
                          "rect": [min(inner, outer), mid - open_w / 2,
                                   max(inner, outer), mid + open_w / 2]})
    # Each block hangs off a lead by its printed gap and grows towards the
    # centre line, so the far edge is the one the gap is measured from.
    edges = (("left", -(half_w - open_w - 0.615), 1.585),
             ("right", half_w - open_w - 1.105, 1.235))
    row_gap, block_h = 0.620, 1.570
    for side, far, width in edges:
        near = far + width if side == "left" else far - width
        for row, sign in (("top", 1.0), ("bottom", -1.0)):
            low, high = sign * row_gap / 2, sign * (row_gap / 2 + block_h)
            paste.append({"kind": "paste_block", "side": side, "row": row,
                          "rect": [min(far, near), min(low, high),
                                   max(far, near), max(low, high)]})

    mask = [_grow(p["rect"], MASK_EXPANSION) for p in copper]
    # A tooth keeps its drawn depth in ``copper`` -- that is what the figure
    # shows -- but the pad KiCad gets reaches PAD_OVERLAP further into the body,
    # so an importer cannot leave pins 5-8 on copper that merely touches.
    pads = ([{"number": p["number"], "kind": p["kind"], "layers": ["F.Cu"], "rect": p["rect"]}
             for p in [body] + right]
            + [{"number": p["number"], "kind": p["kind"], "layers": ["F.Cu"],
                "rect": [p["rect"][0], p["rect"][1], p["rect"][2] + PAD_OVERLAP, p["rect"][3]]}
               for p in teeth]
            + [{"number": "", "kind": "mask", "layers": ["F.Mask"], "rect": r} for r in mask]
            + [{"number": "", "kind": p["kind"], "layers": ["F.Paste"], "rect": p["rect"]}
               for p in paste])

    body_w, body_d = package["E"]["max"], package["D1"]["max"]
    return {"copper": {"body": body, "teeth": teeth, "right": right},
            "paste": paste, "mask": mask, "pads": pads,
            "courtyard": [-(body_w / 2 + COURTYARD), -(body_d / 2 + COURTYARD),
                          body_w / 2 + COURTYARD, body_d / 2 + COURTYARD],
            "body": {"w": body_w, "d": body_d}}


# ---------------------------------------------------------------- comparison
def _grow(rect: list[float], by: float) -> list[float]:
    return [rect[0] - by, rect[1] - by, rect[2] + by, rect[3] + by]


def _area(rect: list[float]) -> float:
    return (rect[2] - rect[0]) * (rect[3] - rect[1])


def _residual(model_rect: list[float], drawn: list[float]) -> float:
    return max(abs(a - b) for a, b in zip(model_rect, drawn))


def _match(modeled: list[dict], drawn: list[list[float]]) -> list[dict]:
    """Pair each modelled aperture with the drawn one nearest its centre.

    The drawing comes out sorted by x while the model lists the left column
    first, so zipping the raw lists would report a mirror image as an error.
    """
    if len(modeled) != len(drawn):
        raise SystemExit(f"the drawing has {len(drawn)} openings, the model {len(modeled)}")

    def centre(r):
        return ((r[0] + r[2]) / 2, (r[1] + r[3]) / 2)

    left = list(drawn)
    rows = []
    for item in modeled:
        cx, cy = centre(item["rect"])
        best = min(left, key=lambda r: (centre(r)[0] - cx) ** 2 + (centre(r)[1] - cy) ** 2)
        left.remove(best)
        row = {k: item[k] for k in item if k != "rect"}
        row.update({"rect": item["rect"], "drawn": best,
                    "residual_mm": round(_residual(item["rect"], best), 4)})
        rows.append(row)
    return rows


def _to_mm(rect: list[float], datum: tuple[float, float], scale: float) -> list[float]:
    """Page points (y down) to the footprint's millimetre frame (y up)."""
    return [(rect[0] - datum[0]) * scale, (datum[1] - rect[3]) * scale,
            (rect[2] - datum[0]) * scale, (datum[1] - rect[1]) * scale]


def _bbox_gap(a, b) -> float:
    dx = max(0.0, max(a[0] - b[2], b[0] - a[2]))
    dy = max(0.0, max(a[1] - b[3], b[1] - a[3]))
    return (dx * dx + dy * dy) ** 0.5


def _multiplicities(spans) -> dict[float, int]:
    """Pair each printed 'Nx' with the dimension label it sits beside."""
    values = [(t, b) for t, b in spans
              if not t.startswith("(") and re.fullmatch(r"\d+\.\d+", t)]
    out: dict[float, int] = {}
    for text, box in spans:
        # The sheet writes the repeat beside the inch value: "(0.020) 8x".
        m = re.search(r"(\d+)x\s*$", text)
        if not m:
            continue
        near, _ = min(values, key=lambda nb: _bbox_gap(box, nb[1]))
        out[float(near)] = int(m.group(1))
    return out


# ---------------------------------------------------------------- assembly
def build(pdf: Path = DEFAULT_PDF) -> dict:
    doc = _open(pdf)
    _page(doc, PACKAGE_PAGE, PACKAGE_TITLE)
    land_page = _page(doc, LAND_PAGE, LAND_TITLE)
    stencil_page = _page(doc, STENCIL_PAGE, STENCIL_TITLE)
    table = _land_table(land_page)
    package = _package_table(doc)

    land_geom = _land_geometry(land_page)
    stencil_geom = _stencil_geometry(stencil_page)
    stencil_cols = _columns(stencil_geom)
    land_anchors = _land_anchors(land_geom, table)
    stencil_anchors = _stencil_anchors(stencil_geom)
    land_scale, land_spread = _fit(land_anchors)
    stencil_scale, stencil_spread = _fit(stencil_anchors)

    # The pinout is printed on both figures; require them to agree rather than
    # trusting one.  The exposed pad carries no printed marker at all.
    land_pins = _pin_map(land_page, LAND_REGION, land_geom["x0"],
                         land_geom["pad_right"], land_geom["bands"])
    stencil_pins = _pin_map(stencil_page, STENCIL_REGION, stencil_cols["left"][0][0],
                            stencil_cols["right"][0][2],
                            [(r[1], r[3]) for r in stencil_cols["left"]])
    pins = {"left": _column(land_pins, "left"), "right": _column(land_pins, "right")}
    built = model(table, package, pins)

    land_datum = ((land_geom["x0"] + land_geom["pad_right"]) / 2,
                  (land_geom["horiz"][0] + land_geom["horiz"][-1]) / 2)
    drawn = {
        # The body starts at the shoulder -- x0 is the tooth tip, F6 further left.
        "body": _to_mm([land_geom["shoulder"], land_geom["horiz"][0],
                        land_geom["body_right"], land_geom["horiz"][-1]],
                       land_datum, land_scale),
        "pads": [_to_mm(r, land_datum, land_scale) for r in land_geom["pads"]],
        "teeth": [_to_mm([land_geom["x0"], b[0], land_geom["shoulder"], b[1]],
                         land_datum, land_scale) for b in land_geom["bands"]],
    }
    land_rows = (_match(built["copper"]["right"], drawn["pads"])
                 + _match(built["copper"]["teeth"], drawn["teeth"]))
    body_residual = _residual(built["copper"]["body"]["rect"], drawn["body"])

    stencil_datum = stencil_geom["datum"]
    drawn_paste = ([_to_mm(r, stencil_datum, stencil_scale) for r in stencil_geom["leads"]]
                   + [_to_mm(r, stencil_datum, stencil_scale)
                      for r in stencil_geom["blocks"]["left"] + stencil_geom["blocks"]["right"]])
    paste_rows = _match(built["paste"], drawn_paste)

    residuals = {f"land:{r['kind']}": r["residual_mm"] for r in land_rows}
    residuals["land:drain_body"] = round(body_residual, 4)
    for a in land_anchors:
        residuals[f"land:{a['name']}"] = round(abs(a["drawn_pt"] * land_scale
                                                   - a["printed_mm"]), 4)
    for a in stencil_anchors:
        residuals[f"stencil:{a['name']}"] = round(abs(a["drawn_pt"] * stencil_scale
                                                     - a["printed_mm"]), 4)
    paste_residual = max(r["residual_mm"] for r in paste_rows)
    residuals["stencil:paste_rect"] = round(paste_residual, 4)
    land_residual = max(v for k, v in residuals.items() if k.startswith("land:"))
    stencil_residual = max(v for k, v in residuals.items() if k.startswith("stencil:"))

    spans = [(t, b) for t, b in _labels(stencil_page)
             if STENCIL_REGION[0] <= (b[0] + b[2]) / 2 <= STENCIL_REGION[2]
             and STENCIL_REGION[1] <= (b[1] + b[3]) / 2 <= STENCIL_REGION[3]]
    printed = sorted({float(v) for t, _ in spans if not t.startswith("(")
                      for v in re.findall(r"\d+\.\d+", t)})
    printed_inch = sorted({float(v) for t, _ in spans if t.startswith("(")
                           for v in re.findall(r"\d+\.\d+", t)})
    used = sorted({round(v, 3) for v in STENCIL_USED})
    unassigned = [v for v in printed if round(v, 3) not in used]
    repeats = _multiplicities(spans)

    copper_area = sum(_area(p["rect"]) for p in
                      [built["copper"]["body"]] + built["copper"]["teeth"]
                      + built["copper"]["right"])
    paste_area = sum(_area(p["rect"]) for p in built["paste"])
    pad = built["copper"]["right"][0]["rect"]
    pad_centre = (pad[0] + pad[2]) / 2
    off_centre = max(abs(abs((p["rect"][0] + p["rect"][2]) / 2) - pad_centre)
                     for p in built["paste"] if p["kind"] == "paste_lead")
    v = lambda key: table[key]["min"]  # noqa: E731
    repeats_table = {"F2=F3=F11": len({v("F2"), v("F3"), v("F11")}) == 1,
                     "F4=F8": v("F4") == v("F8"), "F5=F9": v("F5") == v("F9")}
    chains = (abs(0.500 + 0.615 + 1.585 + 0.320 - 3.020) < 1e-9
              and abs(0.500 + 1.105 + 1.235 + 0.180 - 3.020) < 1e-9)

    checks = {
        "the_two_pages_are_the_land_and_its_stencil": True,
        # A misidentified feature misses by tens of percent; drafting rounding is
        # under one grid step.  Comparing residuals rather than ratios keeps the
        # small dimensions honest -- the 0.63 mm tooth is 2.4 % off the fitted
        # scale, which is 15 um, and a ratio test would call that a misread.
        "every_scale_anchor_agrees":
            all(abs(a["drawn_pt"] * land_scale - a["printed_mm"]) <= LAND_TOL_MM
                for a in land_anchors)
            and all(abs(a["drawn_pt"] * stencil_scale - a["printed_mm"]) <= STENCIL_TOL_MM
                    for a in stencil_anchors),
        "every_land_dimension_matches_the_drawing": land_residual <= LAND_TOL_MM,
        "every_stencil_callout_matches_the_drawing": stencil_residual <= STENCIL_TOL_MM,
        "every_aperture_matches_the_drawing": paste_residual <= STENCIL_TOL_MM,
        "the_pad_bands_chain_to_the_printed_height":
            abs(4 * v("F4") + 3 * v("F5") - v("F2")) < 1e-9,
        "the_table_repeats_the_dimensions_it_should": all(repeats_table.values()),
        "the_stencil_chain_closes_on_the_printed_half_width": chains,
        "the_stencil_leads_sit_on_the_pad_rows": all(
            abs((r["rect"][1] + r["rect"][3]) / 2
                - (built["copper"]["right"][r["band"]]["rect"][1]
                   + built["copper"]["right"][r["band"]]["rect"][3]) / 2) <= STENCIL_TOL_MM
            for r in paste_rows if r["kind"] == "paste_lead"),
        "every_modelled_aperture_is_drawn": len(paste_rows) == len(built["paste"]),
        "the_printed_multiplicities_match_the_aperture_counts": repeats == {0.5: 8, 1.57: 4},
        "the_two_figures_print_the_same_pinout": land_pins == stencil_pins,
        "the_stencil_is_smaller_than_the_land": paste_area < copper_area,
        "every_pad_number_is_a_symbol_pin":
            {p["number"] for p in built["pads"] if p["number"]} == {str(i) for i in range(1, 10)},
        "the_courtyard_clears_the_land": all(
            built["courtyard"][0] < p["rect"][0] and p["rect"][2] < built["courtyard"][2]
            and built["courtyard"][1] < p["rect"][1] and p["rect"][3] < built["courtyard"][3]
            for p in built["pads"]),
        "no_printed_millimetre_callout_is_unexplained": unassigned == [],
    }
    failed = sorted(k for k, ok in checks.items() if not ok)
    if failed:
        raise SystemExit(f"the drawings no longer support this land pattern: {failed}")

    return {
        "source": {"pdf": str(pdf.resolve().relative_to(ROOT)).replace("\\", "/"),
                   "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
                   "pages": {"package": PACKAGE_PAGE + 1, "land": LAND_PAGE + 1,
                             "stencil": STENCIL_PAGE + 1},
                   "figures": [PACKAGE_TITLE, LAND_TITLE, STENCIL_TITLE],
                   "revision": "SLPS406B, 2013-09 to 2014-05"},
        "pinout": {"left_pins": pins["left"], "right_pins": pins["right"],
                   "body_pin": BODY_PIN,
                   "printed_labels": {f"{s}{b}": n for (s, b), n in sorted(land_pins.items())},
                   "column_order": "top to bottom in the drawing's frame"},
        "datum_pt": {"land": [round(x, 3) for x in land_datum],
                     "stencil": [round(x, 3) for x in stencil_datum]},
        "scale": {"land": {"mm_per_pt": round(land_scale, 7),
                           "residual_max_mm": round(land_spread, 4),
                           "anchors": land_anchors},
                  "stencil": {"mm_per_pt": round(stencil_scale, 7),
                              "residual_max_mm": round(stencil_spread, 4),
                              "anchors": stencil_anchors}},
        "copper": built["copper"], "mask": built["mask"], "paste": built["paste"],
        "pads": built["pads"], "courtyard": built["courtyard"], "body": built["body"],
        "pad_overlap_mm": PAD_OVERLAP, "mask_expansion_mm": MASK_EXPANSION,
        "results": {
            "residuals_mm": residuals,
            "land_residual_max_mm": round(land_residual, 4),
            "stencil_residual_max_mm": round(stencil_residual, 4),
            "residual_max_mm": round(max(residuals.values()), 4),
            "tolerances_mm": {"land": LAND_TOL_MM, "stencil": STENCIL_TOL_MM},
            "drawn_land": drawn,
            "drawn_paste": paste_rows,
            "copper_area_mm2": round(copper_area, 3),
            "paste_area_mm2": round(paste_area, 3),
            "paste_fraction": round(paste_area / copper_area, 4),
            "paste_off_pad_centre_mm": round(off_centre, 4),
            "pad_band_chain": {"band_mm": v("F4"), "gap_mm": v("F5"), "steps": 7,
                               "sum_mm": round(4 * v("F4") + 3 * v("F5"), 4)},
            "table_repeats": repeats_table,
        },
        "callouts": {"land_table": table, "package_table": package,
                     "stencil_printed_mm": printed,
                     "stencil_printed_inch": printed_inch,
                     "stencil_used_mm": used,
                     "stencil_unassigned_mm": unassigned,
                     "stencil_repeats": {f"{k}": n for k, n in sorted(repeats.items())}},
        "checks": checks,
        "limitations": [
            "The exposed pad is numbered 9 because the symbol's drain is pins 5-9; "
            "neither figure prints a number for it.  Pins 5-8 and 9 are one node, so "
            "a different assignment would only relabel copper.",
            "This sheet draws no solder-mask layer.  Each copper region is grown by "
            "0.05 mm, the expansion the project's BSC010N04LS6 land uses; the number "
            "comes from that sheet, not from this one.",
            "This sheet draws no courtyard.  The body is the page-9 maximum "
            "(E x D1) plus 0.25 mm per side, the project's convention.",
            "The stencil figure is symmetric about the land's outer edges (0.0825 mm "
            "inset either side) while the copper is not -- the drain teeth are 0.63 "
            "wide and the source pads 0.70 -- so every lead aperture sits 0.0175 mm "
            "off its own pad centre.  The sheet's chain is emitted as drawn rather "
            "than re-centred, because re-centring would be an unprinted edit.",
            "Silkscreen is not on either figure; only the body outline and a pin-1 "
            "wedge are drawn, at project convention.",
            "No 3D model: the package here is 6.10 x 5.00 mm, which matches TI's Q5A, "
            "but no vendored STEP exists for it.",
        ],
    }


# ---------------------------------------------------------------- footprint
_NS = uuid.uuid5(uuid.NAMESPACE_DNS, "dcx.design-48v-2v.csd19531q5a.land")


def _uid(*parts: str) -> str:
    return str(uuid.uuid5(_NS, "/".join(parts)))


def footprint_text(data: dict, name: str = "CSD19531Q5A") -> str:
    """The digitised land as a KiCad footprint, one pad per layer of the drawing.

    Copper pads carry only ``F.Cu``, mask openings only ``F.Mask`` and stencil
    apertures only ``F.Paste``.  Letting a copper pad imply its own mask would
    replace the drawn expansion with the land outline, and imply a stencil equal
    to the land.  The four drain fingers are pushed 0.125 mm into the body so a
    CAD importer cannot leave pins 5-8 on copper that only touches.
    """
    failed = sorted(k for k, ok in data["checks"].items() if not ok)
    if failed:
        raise SystemExit(f"the land JSON fails its own checks: {failed}")
    worst = data["results"]["residual_max_mm"]
    scale = data["scale"]["land"]["mm_per_pt"]
    out = [
        f'(footprint "{name}"\n'
        '\t(version 20260206)\n\t(generator "csd19531q5a_land")\n'
        '\t(generator_version "10.0")\n\t(layer "F.Cu")\n'
        f'\t(descr "TI CSD19531Q5A Q5A 6.10x5.00 mm.  Land and stencil digitised from '
        f'SLPS406B sect. 7.2/7.3 (scale {scale:.6f} mm/pt, max residual {worst * 1000:.1f} um, '
        f'source sha256 {data["source"]["sha256"]}).  Drain 5-9 on one comb, gate 4, '
        f'source 1-3.")\n'
        '\t(attr smd)\n'
        '\t(duplicate_pad_numbers_are_jumpers no)\n'
        '\t(property "Reference" "REF**"\n'
        '\t\t(at 0 -3.4 0)\n\t\t(layer "F.SilkS")\n'
        f'\t\t(uuid "{_uid("ref")}")\n'
        '\t\t(effects (font (size 1 1) (thickness 0.15)))\n\t)\n'
        f'\t(property "Value" "{name}"\n'
        '\t\t(at 0 3.4 0)\n\t\t(layer "F.Fab")\n'
        f'\t\t(uuid "{_uid("value")}")\n'
        '\t\t(effects (font (size 1 1) (thickness 0.15)))\n\t)\n'
    ]
    x0, y0, x1, y1 = data["courtyard"]
    # Silkscreen: two horizontal edges only.  The pad bands run the full height,
    # so a vertical silk line would cross four pads.
    for i, (start, end) in enumerate((((-3.13, 2.58), (3.13, 2.58)),
                                      ((-3.13, -2.58), (3.13, -2.58)))):
        out.append(f'\t(fp_line\n\t\t(start {start[0]:g} {start[1]:g})\n'
                   f'\t\t(end {end[0]:g} {end[1]:g})\n'
                   '\t\t(stroke (width 0.12) (type solid))\n'
                   f'\t\t(layer "F.SilkS")\n\t\t(uuid "{_uid("silk", str(i))}")\n\t)\n')
    # Pin 1 is the bottom-right lead.  Its marker sits *outside* the courtyard
    # because everything inside the right edge is solder-mask opening: an
    # inboard wedge at (3.12, -2.30) tripped DRC's silk_over_copper by 20 um,
    # and the mask there is the drawn expansion, not something to shrink.
    out.append('\t(fp_poly\n\t\t(pts (xy 3.36 -1.85) (xy 3.66 -2.00) (xy 3.36 -2.15))\n'
               '\t\t(stroke (width 0.12) (type solid))\n\t\t(fill yes)\n'
               f'\t\t(layer "F.SilkS")\n\t\t(uuid "{_uid("pin1")}")\n\t)\n')
    hw, hd = data["body"]["w"] / 2, data["body"]["d"] / 2
    for i, (start, end) in enumerate((
            ((-hw, hd), (hw - 0.6, hd)), ((hw - 0.6, hd), (hw, hd - 0.6)),
            ((hw, hd - 0.6), (hw, -hd)), ((hw, -hd), (-hw, -hd)),
            ((-hw, -hd), (-hw, hd)))):
        out.append(f'\t(fp_line\n\t\t(start {start[0]:.4f} {start[1]:.4f})\n'
                   f'\t\t(end {end[0]:.4f} {end[1]:.4f})\n'
                   '\t\t(stroke (width 0.1) (type solid))\n'
                   f'\t\t(layer "F.Fab")\n\t\t(uuid "{_uid("fab", str(i))}")\n\t)\n')
    out.append(f'\t(fp_text user "${{REFERENCE}}"\n\t\t(at 0 0 90)\n\t\t(layer "F.Fab")\n'
               f'\t\t(uuid "{_uid("fabref")}")\n'
               '\t\t(effects (font (size 1 1) (thickness 0.15)))\n\t)\n')
    for i, (start, end) in enumerate((
            ((x0, y0), (x1, y0)), ((x0, y0), (x0, y1)),
            ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)))):
        out.append(f'\t(fp_line\n\t\t(start {start[0]:g} {start[1]:g})\n'
                   f'\t\t(end {end[0]:g} {end[1]:g})\n'
                   '\t\t(stroke (width 0.05) (type solid))\n'
                   f'\t\t(layer "F.CrtYd")\n\t\t(uuid "{_uid("crt", str(i))}")\n\t)\n')
    for i, pad in enumerate(data["pads"]):
        px0, py0, px1, py1 = pad["rect"]
        layers = " ".join(f'"{layer}"' for layer in pad["layers"])
        out.append(f'\t(pad "{pad["number"]}" smd rect\n'
                   f'\t\t(at {(px0 + px1) / 2:.4f} {(py0 + py1) / 2:.4f})\n'
                   f'\t\t(size {px1 - px0:.4f} {py1 - py0:.4f})\n'
                   f'\t\t(layers {layers})\n'
                   f'\t\t(uuid "{_uid("pad", str(i))}")\n\t)\n')
    out.append('\t(embedded_fonts no)\n)\n')
    return "".join(out)


# ---------------------------------------------------------------- entry
def json_text(data: dict) -> str:
    return json.dumps(data, indent=1) + "\n"


def write(path: Path = DEFAULT_JSON) -> dict:
    data = build()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json_text(data), encoding="utf-8", newline="\n")
    return data


def check(path: Path = DEFAULT_JSON) -> None:
    """Fail if the committed JSON is not what the PDF produces today."""
    if not path.is_file():
        raise SystemExit(f"{path} is missing; run with --write")
    if path.read_text(encoding="utf-8") != json_text(build()):
        raise SystemExit(f"{path} is stale; re-run with --write")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--write", action="store_true", help="regenerate the JSON")
    parser.add_argument("--check", action="store_true", help="regenerate and compare")
    args = parser.parse_args()
    if args.check:
        check(args.json)
        print(f"{args.json} matches {args.pdf.name}")
        return
    data = write(args.json) if args.write else build(args.pdf)
    if args.write:
        print(f"wrote {args.json}")
    r = data["results"]
    for which in ("land", "stencil"):
        s = data["scale"][which]
        print(f"{which}: {s['mm_per_pt']:.7f} mm/pt  "
              f"anchor residual {s['residual_max_mm'] * 1000:.1f} um")
    print(f"copper {r['copper_area_mm2']:.3f} mm2  paste {r['paste_area_mm2']:.3f} mm2 "
          f"({r['paste_fraction'] * 100:.1f} %)  {len(data['pads'])} pads")
    print(f"max residual {r['residual_max_mm'] * 1000:.1f} um  "
          f"unassigned callouts {data['callouts']['stencil_unassigned_mm']}")


if __name__ == "__main__":
    main()

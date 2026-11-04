"""Digitise the BSC010N04LS6 (PG-TDSON-8-FL) land pattern from its datasheet.

Why this exists
---------------
The vendored KiCad footprint ``Infineon_PG-TDSON-8_6.15x5.15mm`` numbers all five
of its drain lands "5".  That is a legal way to say "pins 5-8 are one node", but
the schematic symbol models the real BSC010N04LS6 pinout, whose drain *is* pins
5-8, so pins 6, 7 and 8 end up with no pad of their own.  The sanctioned fix is a
device-specific land pattern -- and a land pattern typed in by eye from a picture
is a number nobody can check.  So it is extracted instead: the drawing is vector
art, every dimension on it is also a printed callout, and nothing is emitted that
the drawing does not both measure and label.

How the figure is read
----------------------
Page 11 is Figure 2, "Outline Boardpads (PG-TDSON-8-FL), dimensions in mm".  Its
three layers are separated by *stroke width*, not colour, which is what makes an
exact extraction possible:

* **0.8535 pt black outline -- the copper land.**  Every dimension on the sheet
  measures this line's centreline: the fingers are printed 0.5 and measure
  8.83 pt = 0.4997 mm here, while the grey shape around them is 0.598 mm.
* **width-0 grey (0.50196) rectangle -- the solder mask opening.**  It is the
  copper outline grown by 0.05 on every side, i.e. the sheet's own "0.05".
* **0.4359 pt hatch inside thick quads (detail view) -- the stencil apertures.**
  The quads are the artist's own rectangles and are what is measured; clustering
  the hatch dashes reproduces the same 15 rectangles to 5 um, and that
  cross-check is kept in ``results.hatch_clusters``.

The scale is measured, not assumed: eleven dimensions that are both printed and
drawn are divided out, the median gives mm-per-point, and the spread across them
is the error bar.  Everything else -- mask expansion, paste inset, courtyard,
pad numbering -- is then *checked* against the drawing, so swapping the PDF for
another revision fails here instead of silently moving the land.

What this tool does NOT decide
------------------------------
Three things are read off the sheet by rule rather than by dimension, and are
listed in ``limitations``: the pin-to-finger assignment (pins 5-8 are one node,
so a wrong assignment is electrically invisible and only cosmetic), the stencil
inset from the land tip (0.05, inference -- the drawn value is 0.055), and the
solder-mask layer identity (the legend's grey "copper" swatch says otherwise;
the dimensions and the 0.05 paste inset say the grey is a grown envelope).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PDF = ROOT / "references" / "datasheets" / "bsc010n04ls6.pdf"
DEFAULT_JSON = ROOT / "design" / "v3" / "pcb" / "bsc010n04ls6_land.json"

PAGE_INDEX = 10
FIGURE_TEXT = "Outline Boardpads (PG-TDSON-8-FL), dimensions in mm"

COPPER_STROKE = 0.8535434007644653    # the dimensioned land outline
HATCH_STROKE = 0.43585193157196045    # one stencil hatch dash
DATUM_STROKE = 0.2542469799518585     # the part-centre cross
GREY = 0.5019599795341492             # the mask envelope
DETAIL_X0 = 300.0                     # the detail view sits right of the left one
MIN_ANCHOR_PT = 3.0                   # shorter than this a dimension is noise
CROSS_MIN_PT = 6.0                    # the centre cross is 2.8 mm; ticks are 0.05 mm
ANCHOR_TOL = 0.02                     # catch misidentified features, not drafting rounding
TOL_MM = 0.010                        # a model dimension must land this close

# Every printed callout the model consumes: value -> what it dimensions.  The
# sheet prints these once; several are used twice (symmetry), which is why the
# ledger below compares *values*, not counts.
USED = {
    0.05: "mask expansion / the step between the drain base and its fingers",
    0.15: "source bar overhang past the pin-1..3 finger edge",
    0.18: "stencil block column left of the centre line (a distance; the sign is negative)",
    0.35: "source lead stencil aperture length",
    0.40: "stencil aperture width, narrow direction (leads and blocks)",
    0.50: "finger width (drain and source) and the gate land width",
    0.55: "source lead land length",
    0.80: "drain lead land length and drain lead stencil length",
    0.90: "source bar stencil aperture length",
    0.95: "stencil block row, distance from the centre line",
    1.10: "source bar stencil aperture pitch",
    1.055: "source land height / gate land length",
    1.13: "drain base outer edge, distance from the centre line",
    1.27: "finger pitch",
    1.40: "stencil block width",
    1.42: "stencil block column right of the centre line",
    1.70: "stencil block height",
    1.815: "first source bar stencil row",
    1.905: "each finger row, distance from the centre line",
    2.205: "drain half width",
    2.27: "source bar inner edge, distance from the centre line",
    2.525: "drain base inner edge, distance from the centre line",
    2.798: "gate land centre, distance from the centre line",
    2.875: "drain lead stencil aperture centre, distance from the centre line",
    3.10: "source bar stencil aperture span (3 x 0.9 + 2 x 0.2)",
    3.19: "source land width",
    3.325: "land tip, distance from the centre line",
}

# Model geometry, in mm, package centre at the origin.  +x points at the drain
# leads, +y at pin 1's side; every value below is one of the callouts above.
TIP = 3.325
HALF_WIDTH = 2.205
PITCH = 1.27
FINGER_W = 0.50
DRAIN_LEAD = 0.80
SOURCE_LEAD = 0.55
BASE_OUTER = 1.13
SOURCE_NEAR = 2.27
SOURCE_WIDTH = 3.19
OVERHANG = 0.15
GATE_LEN = 1.055
GATE_W = 0.50
MASK_EXPANSION = 0.05
PASTE_LEAD_W = 0.40
PASTE_DRAIN_LEN = 0.80
PASTE_SOURCE_LEN = 0.35
PASTE_GATE_LEN = 0.80
PASTE_BAR = (0.40, 0.90)
PASTE_BAR_PITCH = 1.10
PASTE_BAR_FIRST = 1.815
PASTE_BLOCK = (1.40, 1.70)
PASTE_BLOCK_CX = (1.42, -0.18)   # the callouts are magnitudes; this one sits left of centre
PASTE_BLOCK_CY = 0.95
PASTE_TIP_INSET = 0.05
PAD_OVERLAP = 0.125     # how far a finger runs into its base so the copper is one piece
COURTYARD = 0.25
BODY = (6.15, 5.15)

# Pinout, from page 1: "Drain Pin 5-8 / Gate Pin 4 / Source Pin 1-3".  The
# finger-to-pin assignment follows SO-8 numbering (1 bottom-left going up, 8
# bottom-right going up the other side), which puts pin 4's gate at +y and pin 1
# at -y; the sheet's "Pin1" marker sits at the bottom-left of the left view.
DRAIN_PINS = ((1.905, "5"), (0.635, "6"), (-0.635, "7"), (-1.905, "8"))
SOURCE_PINS = ((-1.905, "1"), (-0.635, "2"), (0.635, "3"))
GATE_ROW = 1.905


# ---------------------------------------------------------------- PDF access
def _flat(text: str) -> str:
    """Text with the furniture's soft separators turned into ordinary spaces.

    These drawings separate words with ``\\x03`` rather than a space, so a
    literal search for "Outline Boardpads" fails on text that is visibly there.
    """
    return " ".join(re.sub(r"[\x00-\x1f]", " ", text).split())


def _page(pdf: Path):
    """The figure page, or a hard stop explaining which dependency is missing."""
    try:
        import fitz
    except ImportError as exc:      # pragma: no cover - depends on the machine
        raise SystemExit("PyMuPDF is needed only to regenerate this JSON.  "
                         "pip install pymupdf, or use the committed file.") from exc
    doc = fitz.open(pdf)
    page = doc[PAGE_INDEX]
    title = _flat(page.get_text("text"))
    if FIGURE_TEXT.split(",")[0] not in title:
        raise SystemExit(f"page {PAGE_INDEX + 1} is not Figure 2; the PDF moved, "
                         f"so the page index is wrong")
    return page


def _num_spans(page, y_max: float = 500.0) -> list[float]:
    """Every printed decimal in the drawing area, as a float."""
    out: list[float] = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                if span["bbox"][1] >= y_max:
                    continue
                out += [float(v) for v in re.findall(r"\d+\.\d+", span["text"])]
    return out


def _pinout(page) -> dict:
    """Assert the pinout instead of trusting memory; page 1 carries it as text."""
    flat = _flat(page.parent[0].get_text("text"))
    wanted = {"drain": "Drain Pin 5-8", "gate": "Gate Pin 4", "source": "Source Pin 1-3"}
    missing = [v for v in wanted.values() if v not in flat]
    if missing:
        raise SystemExit(f"page 1 no longer states {missing}; the pinout is the "
                         f"one thing this tool cannot infer from Figure 2")
    return {"drain_pins": [5, 6, 7, 8], "gate_pin": 4, "source_pins": [1, 2, 3],
            "package": "PG-TDSON-8-FL", "quoted": {k: v for k, v in wanted.items()}}


# ---------------------------------------------------------------- geometry
def _strokes(page, width: float | None, tol: float = 1e-3) -> list:
    """Drawings whose stroke width is ``width`` (``None`` means exactly zero)."""
    out = []
    for drawing in page.get_drawings():
        got = drawing["width"]
        if got is None:
            continue
        if (got if width else 0.0) != width and abs(got - (width or 0.0)) > tol:
            continue
        out.append(drawing)
    return out


def _lines(drawing) -> list[tuple[float, float, float, float]]:
    return [(a.x, a.y, b.x, b.y) for kind, a, b in
            ((it[0], it[1], it[2]) for it in drawing["items"]) if kind == "l"]


def _rows(segments: list[tuple[float, float, float, float]]) -> dict[float, list]:
    """Horizontal segments grouped by y, with touching spans merged."""
    rows: dict[float, list[tuple[float, float]]] = {}
    for x0, y0, x1, y1 in segments:
        if abs(y0 - y1) > 1e-6:
            continue
        rows.setdefault(round(y0, 3), []).append((min(x0, x1), max(x0, x1)))
    merged: dict[float, list[tuple[float, float]]] = {}
    for y, spans in rows.items():
        out: list[tuple[float, float]] = []
        for lo, hi in sorted(spans):
            if out and lo <= out[-1][1] + 1e-6:
                out[-1] = (out[-1][0], max(out[-1][1], hi))
            else:
                out.append((lo, hi))
        merged[y] = out
    return merged


def _land(segments: list[tuple[float, float, float, float]]) -> dict:
    """Split a rectilinear land outline into its finger row and its body.

    These lands have exactly three horizontal levels: the finger tips, the
    shoulder where the fingers meet the body, and the body's far edge.  Span
    counts cannot tell them apart -- the shoulder splits into fingers+1 spans on
    the drain (the 0.05 overhang steps) and ties with the tips on the source --
    but the far edge is the only level drawn as a *single* full-width span.  So
    the far edge is found by uniqueness, and the tips are whichever of the two
    remaining levels sits farther from it, which makes one rule serve the drain
    (fingers at low y) and the source (fingers at high y) alike.
    """
    rows = _rows(segments)
    if len(rows) != 3:
        raise SystemExit(f"a land outline has {len(rows)} horizontal levels, not 3")
    full = [y for y, spans in rows.items() if len(spans) == 1]
    if len(full) != 1:
        raise SystemExit(f"a land outline has {len(full)} full-width edges, not 1")
    outer = full[0]
    shoulder, tip_level = sorted((y for y in rows if y != outer),
                                 key=lambda y: abs(y - outer))
    xs = [v for s in segments for v in (s[0], s[2])]
    return {"tip_level": tip_level, "tip_spans": rows[tip_level],
            "shoulder": shoulder, "outer": outer,
            "x0": min(xs), "x1": max(xs)}


def _cross(page) -> dict[str, tuple[float, float]]:
    """The part-centre cross of each view: two short strokes that intersect.

    Neither thickness nor length separates it: the cross shares its 0.254 pt
    stroke with the dimension lines, and every extension line on this sheet is
    also 7.07 pt long -- the artist draws the extension to a fixed length.  What
    is unique is that the cross's two strokes *bisect* each other.  An extension
    line meets the dimension line it serves at its end, never at its midpoint,
    so requiring both midpoints to coincide removes those -- but the sheet also
    has ~2 900 tiny 0.89 pt ticks ("4x" repetition marks) that do bisect, so a
    floor on the stroke's length is needed too.  Together they leave one pair
    per view: the 2.8 mm marker at the part centre.
    """
    horiz: list[tuple[float, float, float]] = []
    vert: list[tuple[float, float, float]] = []
    for drawing in _strokes(page, DATUM_STROKE):
        if len(drawing["items"]) != 1 or drawing["items"][0][0] != "l":
            continue
        x0, y0, x1, y1 = _lines(drawing)[0]
        if math.hypot(x1 - x0, y1 - y0) < CROSS_MIN_PT:
            continue
        if abs(y1 - y0) < 1e-6:
            horiz.append((min(x0, x1), max(x0, x1), (y0 + y1) / 2))
        elif abs(x1 - x0) < 1e-6:
            vert.append((min(y0, y1), max(y0, y1), (x0 + x1) / 2))

    out: dict[str, tuple[float, float]] = {}
    for lo, hi, y in horiz:
        for vlo, vhi, x in vert:
            if not (lo <= x <= hi and vlo <= y <= vhi):
                continue
            if abs((lo + hi) / 2 - x) > 0.05 or abs((vlo + vhi) / 2 - y) > 0.05:
                continue
            view = "left" if x < DETAIL_X0 else "detail"
            if view in out:
                raise SystemExit(f"the {view} view has more than one centre cross")
            out[view] = (x, y)
    if set(out) != {"left", "detail"}:
        raise SystemExit(f"found a centre cross in {sorted(out) or 'neither'} view")
    return out


def measure(page) -> dict:
    """Everything the drawing states, in PDF points, before a scale is chosen."""
    cross = _cross(page)
    cx, cy = cross["left"]
    cx_detail, cy_detail = cross["detail"]
    if abs(cy_detail - cy) > 0.05:
        raise SystemExit("the two views no longer share a y datum, so the detail "
                         "view's paste apertures cannot be mapped onto the lands")

    copper = [d for d in _strokes(page, COPPER_STROKE)
              if len(d["items"]) >= 4 or any(it[0] in ("qu", "re") for it in d["items"])]
    left = [d for d in copper if d["rect"].x1 < DETAIL_X0]
    detail = [d for d in copper if d["rect"].x0 >= DETAIL_X0]
    rectilinear = [d for d in left if [i[0] for i in d["items"]].count("l") >= 8]
    quads = [d for d in left if d not in rectilinear]
    if len(rectilinear) != 2 or len(quads) != 1:
        raise SystemExit(f"expected two rectilinear lands and one gate, found "
                         f"{len(rectilinear)} and {len(quads)}")
    lands = sorted((_land(_lines(d)) for d in rectilinear),
                   key=lambda land: -land["x1"])
    drain, source = lands[0], lands[1]
    gate = {"x0": quads[0]["rect"].x0, "x1": quads[0]["rect"].x1,
            "y0": quads[0]["rect"].y0, "y1": quads[0]["rect"].y1}

    masks = []
    for d in _strokes(page, None):
        colour = d["color"]
        if colour is None or abs(colour[0] - GREY) > 1e-3:
            continue
        if d["rect"].y0 > 390:                     # the legend swatch sits at 400
            continue
        # Each grey region is drawn as four separate edge strokes plus one
        # filled rectangle.  The edges are not regions -- their bounding box is
        # a line -- so only boxes with area describe an opening.
        if d["rect"].width <= 1e-3 or d["rect"].height <= 1e-3:
            continue
        masks.append(tuple(round(v, 3) for v in d["rect"]))
    masks.sort()

    return {
        "cx": cx, "cy": cy, "cx_detail": cx_detail,
        "drain": drain, "source": source, "gate": gate,
        "mask_boxes": sorted(set(masks)),
        "aperture_quads": sorted((d["rect"] for d in detail), key=lambda r: (r.y0, r.x0)),
        "hatch": _hatch_clusters([_lines(d) for d in _strokes(page, HATCH_STROKE)
                                  if d["rect"].x0 >= DETAIL_X0]),
    }


def _hatch_clusters(strokes: list, pad_pt: float = 0.2) -> list[tuple]:
    """Union-find over hatch dashes grown by ``pad_pt``; one cluster per aperture.

    Independent of the thick quads, so the two disagreeing is a real signal.
    """
    boxes = [(min(s[0], s[2]), min(s[1], s[3]), max(s[0], s[2]), max(s[1], s[3]))
             for segs in strokes for s in segs]
    parent = list(range(len(boxes)))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for i, a in enumerate(boxes):
        for j in range(i + 1, len(boxes)):
            b = boxes[j]
            if (a[0] - pad_pt < b[2] and b[0] - pad_pt < a[2]
                    and a[1] - pad_pt < b[3] and b[1] - pad_pt < a[3]):
                parent[find(i)] = find(j)
    groups: dict[int, list] = {}
    for i in range(len(boxes)):
        groups.setdefault(find(i), []).append(boxes[i])
    out = [(min(b[0] for b in g), min(b[1] for b in g),
            max(b[2] for b in g), max(b[3] for b in g)) for g in groups.values()]
    return sorted(tuple(round(v, 3) for v in box) for box in out)


# ---------------------------------------------------------------- model
def _rect(x0: float, y0: float, x1: float, y1: float) -> list[float]:
    return [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)]


def _union(rects: list[list[float]]) -> list[float]:
    return [min(r[0] for r in rects), min(r[1] for r in rects),
            max(r[2] for r in rects), max(r[3] for r in rects)]


def _grow(rect: list[float], by: float) -> list[float]:
    return _rect(rect[0] - by, rect[1] - by, rect[2] + by, rect[3] + by)


def model() -> dict:
    """The land as built from printed callouts, package centre at the origin."""
    near = TIP - DRAIN_LEAD
    base = _rect(-BASE_OUTER, -HALF_WIDTH, near, HALF_WIDTH)
    drain_fingers = [{"pin": pin, "rect": _rect(near, y - FINGER_W / 2, TIP, y + FINGER_W / 2)}
                     for y, pin in DRAIN_PINS]
    bar_far = SOURCE_NEAR + (GATE_LEN - SOURCE_LEAD)
    # The bar runs from the last source finger's outer edge (0.635 + 0.25) down
    # past the first finger by the printed 0.15 overhang: 3.19 long, which is
    # the printed source land width.  Bounding it by the gate row instead would
    # make it 3.83 -- the drawing and the mask both say 0.885 is the far edge.
    bar = _rect(-bar_far, -(GATE_ROW + FINGER_W / 2 + OVERHANG), -SOURCE_NEAR,
                SOURCE_PINS[-1][0] + FINGER_W / 2)
    source_fingers = [{"pin": pin, "rect": _rect(-TIP, y - FINGER_W / 2, -bar_far, y + FINGER_W / 2)}
                      for y, pin in SOURCE_PINS]
    gate = _rect(-TIP, GATE_ROW - GATE_W / 2, -SOURCE_NEAR, GATE_ROW + GATE_W / 2)

    paste = []
    for y, _ in DRAIN_PINS:
        paste.append({"kind": "drain_lead", "rect": _rect(
            TIP - PASTE_TIP_INSET - PASTE_DRAIN_LEN, y - PASTE_LEAD_W / 2,
            TIP - PASTE_TIP_INSET, y + PASTE_LEAD_W / 2)})
    for cx in PASTE_BLOCK_CX:
        for sign, side in ((1.0, "right"), (-1.0, "left")):
            paste.append({"kind": f"block_{side}", "rect": _rect(
                cx - PASTE_BLOCK[0] / 2, sign * PASTE_BLOCK_CY - PASTE_BLOCK[1] / 2,
                cx + PASTE_BLOCK[0] / 2, sign * PASTE_BLOCK_CY + PASTE_BLOCK[1] / 2)})
    bar_cx = -(SOURCE_NEAR + (GATE_LEN - SOURCE_LEAD) / 2)
    for k in range(3):
        cy = -PASTE_BAR_FIRST + k * PASTE_BAR_PITCH
        paste.append({"kind": "source_bar", "rect": _rect(
            bar_cx - PASTE_BAR[0] / 2, cy - PASTE_BAR[1] / 2,
            bar_cx + PASTE_BAR[0] / 2, cy + PASTE_BAR[1] / 2)})
    for y, _ in SOURCE_PINS:
        paste.append({"kind": "source_lead", "rect": _rect(
            -TIP + PASTE_TIP_INSET, y - PASTE_LEAD_W / 2,
            -TIP + PASTE_TIP_INSET + PASTE_SOURCE_LEN, y + PASTE_LEAD_W / 2)})
    paste.append({"kind": "gate", "rect": _rect(
        -TIP + PASTE_TIP_INSET, GATE_ROW - PASTE_LEAD_W / 2,
        -TIP + PASTE_TIP_INSET + PASTE_GATE_LEN, GATE_ROW + PASTE_LEAD_W / 2)})

    # One copper pad per land, each carrying its own pin number.  The drain
    # base is "5" and each of its four fingers repeats the number of the lead
    # it serves, so pins 6, 7 and 8 finally own pads; the source side repeats
    # that pattern for pins 1-3.  A finger is pushed PAD_OVERLAP into its body
    # so KiCad sees one continuous piece of copper -- same node either way, but
    # a gap would leave the lead unconnected in the DRC.
    pads = [{"number": "5", "kind": "drain_base", "rect": base, "layers": ["F.Cu"]}]
    for finger in drain_fingers:
        x0, y0, x1, y1 = finger["rect"]
        pads.append({"number": finger["pin"], "kind": "drain_lead", "layers": ["F.Cu"],
                     "rect": _rect(x0 - PAD_OVERLAP, y0, x1, y1)})
    pads.append({"number": "1", "kind": "source_bar", "rect": bar, "layers": ["F.Cu"]})
    for finger in source_fingers:
        x0, y0, x1, y1 = finger["rect"]
        pads.append({"number": finger["pin"], "kind": "source_lead", "layers": ["F.Cu"],
                     "rect": _rect(x0, y0, x1 + PAD_OVERLAP, y1)})
    pads.append({"number": "4", "kind": "gate", "rect": gate, "layers": ["F.Cu"]})

    # The drawing opens the mask as one rectangle over each whole land, not as
    # a grown copy of every finger -- the grey region has four straight sides
    # and no notch.  So the openings are explicit F.Mask rectangles, and the
    # copper pads carry no mask margin at all.
    mask = {
        "drain": _grow(_union([base] + [f["rect"] for f in drain_fingers]), MASK_EXPANSION),
        "source": _grow(_union([bar] + [f["rect"] for f in source_fingers]), MASK_EXPANSION),
        "gate": _grow(gate, MASK_EXPANSION),
    }
    for kind, rect in mask.items():
        pads.append({"number": "", "kind": "mask:" + kind, "rect": rect, "layers": ["F.Mask"]})
    for item in paste:
        pads.append({"number": "", "kind": "paste:" + item["kind"], "rect": item["rect"],
                     "layers": ["F.Paste"]})

    xs = [v for p in pads if "F.Cu" in p["layers"] for v in (p["rect"][0], p["rect"][2])]
    ys = [v for p in pads if "F.Cu" in p["layers"] for v in (p["rect"][1], p["rect"][3])]
    cx = max(max(abs(min(xs)), abs(max(xs))) + COURTYARD, BODY[0] / 2 + COURTYARD)
    cy = max(max(abs(min(ys)), abs(max(ys))) + COURTYARD, BODY[1] / 2 + COURTYARD)
    return {"copper": {"drain_base": base, "drain_fingers": drain_fingers,
                       "source_bar": bar, "source_fingers": source_fingers, "gate": gate},
            "mask": mask, "paste": paste, "pads": pads,
            "courtyard": _rect(-cx, -cy, cx, cy)}


# ---------------------------------------------------------------- assembly
def _to_mm(box: tuple, cx: float, cy: float, scale: float) -> list[float]:
    """PDF rect -> KiCad mm, package centre at the origin.

    +x points at the drain leads, so the drawing's y maps to -x; +y points at
    pin 1, so the drawing's x maps to +y.
    """
    x_pdf0, y_pdf0, x_pdf1, y_pdf1 = box
    return [round(-(y_pdf1 - cy) * scale, 4), round((x_pdf0 - cx) * scale, 4),
            round(-(y_pdf0 - cy) * scale, 4), round((x_pdf1 - cx) * scale, 4)]


def _measured_land(land: dict, cx: float, cy: float, scale: float) -> dict:
    """The drawn land in mm: a body rect and its finger rects.

    The body's x extent is the shoulder-to-far-edge distance and its y extent is
    the outline's whole x span; the fingers share one x extent, tips to
    shoulder, and take their y from their own spans.  Because the rule is
    expressed in "distance from the shoulder", it reads the drain (fingers at
    low y) and the source (fingers at high y) with the same code.
    """
    body_x = sorted((-(land["outer"] - cy) * scale, -(land["shoulder"] - cy) * scale))
    body_y = sorted(((land["x0"] - cx) * scale, (land["x1"] - cx) * scale))
    finger_x = sorted((-(land["tip_level"] - cy) * scale, -(land["shoulder"] - cy) * scale))
    fingers = []
    for s0, s1 in sorted(land["tip_spans"]):
        y0, y1 = sorted(((s0 - cx) * scale, (s1 - cx) * scale))
        fingers.append(_rect(finger_x[0], y0, finger_x[1], y1))
    return {"body": _rect(body_x[0], body_y[0], body_x[1], body_y[1]), "fingers": fingers}


def _anchors(m: dict) -> list[dict]:
    """Printed dimensions that are also drawn, as pt-per-mm ratios.

    Every entry is one printed callout divided by the same distance measured on
    the drawing, so the twelve of them should agree -- their spread is the
    scale's honest error bar.  ``base_to_finger_step`` is the 0.05 shoulder
    step, kept in the list but flagged unusable: at 0.87 pt it is shorter than
    the drawing's own line width.
    """
    drain, source, gate, cy = m["drain"], m["source"], m["gate"], m["cy"]
    tips = sorted(drain["tip_spans"])
    centres = [(a + b) / 2 for a, b in tips]
    return [
        {"name": "finger_pitch", "pt": statistics.mean(b - a for a, b in zip(centres, centres[1:])),
         "mm": PITCH},
        {"name": "finger_width", "pt": statistics.mean(b - a for a, b in tips), "mm": FINGER_W},
        {"name": "drain_half_width", "pt": (drain["x1"] - drain["x0"]) / 2, "mm": HALF_WIDTH},
        {"name": "land_tip", "pt": abs(drain["tip_level"] - cy), "mm": TIP},
        {"name": "drain_shoulder", "pt": abs(drain["shoulder"] - cy), "mm": TIP - DRAIN_LEAD},
        {"name": "drain_outer", "pt": abs(drain["outer"] - cy), "mm": BASE_OUTER},
        {"name": "drain_lead_len", "pt": abs(drain["tip_level"] - drain["shoulder"]), "mm": DRAIN_LEAD},
        {"name": "source_land_width", "pt": source["x1"] - source["x0"], "mm": SOURCE_WIDTH},
        {"name": "source_lead_len", "pt": abs(source["tip_level"] - source["shoulder"]), "mm": SOURCE_LEAD},
        {"name": "source_bar_inner", "pt": abs(source["outer"] - cy), "mm": SOURCE_NEAR},
        {"name": "gate_length", "pt": abs(gate["y1"] - gate["y0"]), "mm": GATE_LEN},
        {"name": "gate_width", "pt": abs(gate["x1"] - gate["x0"]), "mm": GATE_W},
        {"name": "base_to_finger_step", "pt": abs(drain["x1"] - max(b for _, b in tips)), "mm": 0.05},
    ]


def build(pdf: Path = DEFAULT_PDF) -> dict:
    page = _page(pdf)
    m = measure(page)
    model_ = model()

    anchors = _anchors(m)
    for a in anchors:
        a["pt_per_mm"] = round(a["pt"] / a["mm"], 4)
        a["usable"] = a["pt"] >= MIN_ANCHOR_PT
    usable = [a["pt_per_mm"] for a in anchors if a["usable"]]
    scale = 1.0 / statistics.median(usable)
    spread = (max(usable) - min(usable)) / statistics.median(usable)

    cx, cy = m["cx"], m["cy"]
    drain = _measured_land(m["drain"], cx, cy, scale)
    source = _measured_land(m["source"], cx, cy, scale)
    measured = {
        "drain_base": drain["body"], "drain_fingers": drain["fingers"],
        "source_bar": source["body"], "source_fingers": source["fingers"],
        "gate": _to_mm((m["gate"]["x0"], m["gate"]["y0"], m["gate"]["x1"], m["gate"]["y1"]),
                       cx, cy, scale),
        "paste": [_to_mm((r.x0, r.y0, r.x1, r.y1), m["cx_detail"], cy, scale)
                  for r in m["aperture_quads"]],
        "mask": [_to_mm(box, cx, cy, scale) for box in m["mask_boxes"]],
        "hatch": [_to_mm(box, m["cx_detail"], cy, scale) for box in m["hatch"]],
    }

    return _assemble(pdf, m, model_, anchors, scale, spread, measured)


def _residual(model_rect: list[float], drawn: list[float]) -> float:
    return max(abs(a - b) for a, b in zip(model_rect, drawn))


def _match(paste: list[dict], drawn: list[list[float]]) -> tuple[list[dict], list[dict]]:
    """Pair each drawn aperture with the model aperture it realises."""
    used: set[int] = set()
    rows: list[dict] = []
    for rect in drawn:
        centre = ((rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2)
        best, dist = None, 1e9
        for i, item in enumerate(paste):
            if i in used:
                continue
            m = item["rect"]
            d = max(abs(centre[0] - (m[0] + m[2]) / 2), abs(centre[1] - (m[1] + m[3]) / 2))
            if d < dist:
                best, dist = i, d
        if best is None or dist > 0.05:
            raise SystemExit(f"a stencil aperture at {centre} matches no model aperture "
                             f"(nearest is {dist:.3f} mm away)")
        used.add(best)
        rows.append({"kind": paste[best]["kind"], "drawn": rect,
                     "residual_mm": round(_residual(paste[best]["rect"], rect), 4)})
    missing = [paste[i]["kind"] for i in range(len(paste)) if i not in used]
    return rows, [{"kind": k, "note": "modelled but not drawn"} for k in missing]


def _area(rect: list[float]) -> float:
    return (rect[2] - rect[0]) * (rect[3] - rect[1])


def _assemble(pdf: Path, m: dict, model_: dict, anchors: list[dict], scale: float,
              spread: float, measured: dict) -> dict:
    copper = model_["copper"]
    paste_rows, paste_missing = _match(model_["paste"], measured["paste"])

    # The mask opening is each land's *bounding* rectangle grown by 0.05 -- not
    # every finger grown on its own.  Both leave the same copper underneath, so
    # only the drawing can tell them apart: the grey region has four straight
    # sides and no notch between the fingers.
    boxes = {"drain": _union([measured["drain_base"]] + measured["drain_fingers"]),
             "source": _union([measured["source_bar"]] + measured["source_fingers"]),
             "gate": measured["gate"]}
    mask_rows, mask_missing = _match(
        [{"kind": k, "rect": _grow(v, MASK_EXPANSION)} for k, v in boxes.items()],
        measured["mask"])

    # The model lists a land's fingers in pin order while the measurement comes
    # back sorted by y, so the two lists run in opposite directions.  Pair them
    # by position first; zipping the raw lists reports a mirror image as a
    # multi-millimetre error.
    def _pair(modeled: list[dict], drawn: list[list[float]]) -> float:
        if len(modeled) != len(drawn):
            raise SystemExit(f"the drawing has {len(drawn)} fingers, the model {len(modeled)}")
        by_y = lambda r: (r[1] + r[3]) / 2  # noqa: E731
        left = sorted((f["rect"] for f in modeled), key=by_y)
        right = sorted(drawn, key=by_y)
        return max(_residual(a, b) for a, b in zip(left, right))

    residuals = {
        "drain_base": _residual(copper["drain_base"], measured["drain_base"]),
        "source_bar": _residual(copper["source_bar"], measured["source_bar"]),
        "gate": _residual(copper["gate"], measured["gate"]),
        "drain_fingers": _pair(copper["drain_fingers"], measured["drain_fingers"]),
        "source_fingers": _pair(copper["source_fingers"], measured["source_fingers"]),
        "paste": max((r["residual_mm"] for r in paste_rows), default=1e9),
        "mask": max((r["residual_mm"] for r in mask_rows), default=1e9),
    }
    bar_rows = sorted((r["drawn"] for r in paste_rows if r["kind"] == "source_bar"),
                      key=lambda r: r[1])
    residuals["paste_bar_span"] = (abs((bar_rows[-1][3] - bar_rows[0][1]) - 3.10)
                                   if len(bar_rows) == 3 else 1e9)
    residuals = {k: round(v, 4) for k, v in residuals.items()}

    printed = sorted(set(_num_spans(_page(pdf))))
    used = sorted({round(v, 3) for v in USED})
    unassigned = [v for v in printed if round(v, 3) not in used]

    copper_area = (sum(_area(r) for r in [copper["drain_base"], copper["source_bar"], copper["gate"]])
                   + sum(_area(f["rect"]) for f in copper["drain_fingers"])
                   + sum(_area(f["rect"]) for f in copper["source_fingers"]))
    paste_area = sum(_area(p["rect"]) for p in model_["paste"])
    pins = sorted({p["number"] for p in model_["pads"] if p["number"]})
    hatch = sorted(measured["hatch"])
    quads = sorted(measured["paste"])
    hatch_residual = (max(max(abs(a - b) for a, b in zip(h, q)) for h, q in zip(hatch, quads))
                      if len(hatch) == len(quads) else 1e9)

    checks = {
        "the_page_is_figure_2": True,
        # This check exists to catch a *misidentified* feature -- 0.55 attached
        # to the 0.8 edge would miss by 45 % -- not to certify the sheet's
        # precision.  The sheet is drawn, not computed: its own 0.55 callout
        # measures 0.544 mm, a 1.0 % drafting rounding, and that is why the
        # threshold sits at 2 % while ``spread`` (1.2 %) is reported as the
        # real error bar on the fitted scale.
        "every_scale_anchor_agrees": all(abs(a["pt_per_mm"] - 1 / scale) / (1 / scale) < ANCHOR_TOL
                                         for a in anchors if a["usable"]),
        "every_model_dimension_matches_the_drawing": all(v <= TOL_MM for v in residuals.values()),
        "the_stencil_quads_and_the_hatch_agree": hatch_residual <= TOL_MM,
        "every_modelled_aperture_is_drawn": not paste_missing and not mask_missing,
        "the_stencil_is_smaller_than_the_land": paste_area < copper_area,
        "every_pad_number_is_a_symbol_pin": set(pins) == {"1", "2", "3", "4", "5", "6", "7", "8"},
    }
    if not all(checks.values()):
        raise SystemExit(f"the drawing no longer supports this land pattern: "
                         f"{[k for k, v in checks.items() if not v]}")

    return {
        "source": {"pdf": str(pdf.relative_to(ROOT)).replace("\\", "/"),
                   "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
                   "page_index": PAGE_INDEX, "figure": FIGURE_TEXT,
                   "revision": "2.3, 2022-07-21"},
        "pinout": _pinout(_page(pdf)),
        "datum_pt": {"left": [round(m["cx"], 4), round(m["cy"], 4)],
                     "detail": [round(m["cx_detail"], 4), round(m["cy"], 4)]},
        "scale": {"mm_per_pt": round(scale, 7), "spread": round(spread, 6),
                  "excluded_below_pt": MIN_ANCHOR_PT, "anchors": anchors},
        "copper": copper, "mask": model_["mask"], "paste": model_["paste"], "pads": model_["pads"],
        "courtyard": model_["courtyard"], "body": {"w": BODY[0], "d": BODY[1]},
        "pad_overlap_mm": PAD_OVERLAP, "mask_expansion_mm": MASK_EXPANSION,
        "results": {
            "residuals_mm": residuals,
            "drawn_paste": paste_rows,
            "drawn_mask": mask_rows,
            "copper_area_mm2": round(copper_area, 3),
            "paste_area_mm2": round(paste_area, 3),
            "paste_fraction": round(paste_area / copper_area, 4),
            "hatch_clusters": len(m["hatch"]),
            "hatch_vs_quad_max_mm": round(hatch_residual, 4),
        },
        "callouts": {"printed": printed, "used": used, "unassigned": unassigned},
        "checks": checks,
        "limitations": [
            "The finger-to-pin assignment follows SO-8 numbering, not a printed "
            "marker: pins 5-8 are one electrical node, so a wrong assignment is "
            "invisible electrically and only relabels copper.",
            "The stencil inset from the land tip is 0.05 by inference; the drawing "
            "measures 0.055 and the 0.05 callout is used elsewhere.",
            "The legend's 'copper' swatch is a grey fill, while every dimension on "
            "the sheet measures the thick black outline and the stencil clears it "
            "by exactly 0.05.  The black outline is read as copper and the grey as "
            "the mask opening grown by 0.05; the swatch is the contrary evidence.",
            "No 3D model of this land; the vendored footprint's model is for the "
            "same body, not for these lands.",
            "Silkscreen and F.Fab outlines are not on the drawing and are carried "
            "over from the vendored footprint unchanged.",
        ],
    }


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
    fresh = json_text(build())
    if path.read_text(encoding="utf-8") != fresh:
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
    print(f"scale {data['scale']['mm_per_pt']:.7f} mm/pt  spread {data['scale']['spread'] * 100:.3f} %")
    print(f"copper {r['copper_area_mm2']:.3f} mm2  paste {r['paste_area_mm2']:.3f} mm2 "
          f"({r['paste_fraction'] * 100:.1f} %)  {len(data['pads'])} pads")
    print(f"max residual {max(r['residuals_mm'].values()) * 1000:.1f} um  "
          f"unassigned callouts {data['callouts']['unassigned']}")


if __name__ == "__main__":
    main()

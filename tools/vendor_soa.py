"""Digitise the SOA and Zth diagrams out of the vendored BSC010N04LS6 PDF.

SOURCE-03 needs the *drawn* safe-operating-area family and the transient
thermal impedance, not the headline "285 A / 1140 A" figures.  Those two
diagrams exist only as vector graphics in ``references/datasheets``.  This
tool reads the strokes and the axis tick labels of the original page and
writes them as numbers, so a screening tool can compare measured waveforms
against the vendor curve instead of against a remembered number.

Two things make the extraction non-trivial:

* the only data-bearing stroke width is 1.2 pt (cell borders are 0.9 pt);
* PyMuPDF reports every dash as its own one-segment drawing, so the duty-cycle
  family in the Zth plot arrives as thousands of 0.65 pt chords.  The
  single-pulse trace is the one drawn with long chords, and its identity is
  then *verified* by requiring it to be the lower envelope of all ink at every
  sampled abscissa.

PyMuPDF is not a project dependency (it is not in requirements.txt and the CI
image does not install it), so the import is lazy: the committed JSON is the
artifact everyone reads, and only regeneration needs the library.

Usage:
    python tools/vendor_soa.py --json design/v3/power_priority/vendor_soa_digitized.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PDF = ROOT / "references/datasheets/bsc010n04ls6.pdf"
DEFAULT_JSON = ROOT / "design/v3/power_priority/vendor_soa_digitized.json"

CURVE_STROKE_PT = 1.2
STROKE_TOLERANCE_PT = 0.01
CHAIN_TOLERANCE_PT = 0.3      # endpoints this close are the same node
CHAIN_MIN_COSINE = 0.2        # refuse to turn back on a shared diagonal
SOLID_CHORD_MIN_PT = 2.0      # single-pulse trace vs the 0.65 pt duty chords
ENVELOPE_TOLERANCE_PT = 1.5
PLOT_PADDING_PT = 3.0
SOA_LABEL = re.compile(r"^(?P<n>\d+)\s*(?P<unit>ns|us|ms)$")
UNIT_S = {"ns": 1e-9, "us": 1e-6, "ms": 1e-3}
AXIS_EXPONENT = re.compile(r"^-?\d$")


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\x03", " ")).strip().lower()


def load_page(pdf: Path) -> tuple[object, int]:
    """Return the page that carries both diagrams, and its index."""
    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover - exercised only without the library
        raise SystemExit("vendor_soa needs PyMuPDF to re-read the PDF (pip install pymupdf)") from exc
    doc = pymupdf.open(pdf)
    for index, page in enumerate(doc):
        text = _normalise(page.get_text())
        if "safe operating area" in text and "transient thermal impedance" in text:
            return page, index
    raise SystemExit(f"{pdf} has no page carrying both the SOA and Zth diagrams")


def spans_of(page: object) -> list[dict]:
    return [s for block in page.get_text("dict")["blocks"] for line in block.get("lines", [])
            for s in line["spans"]]


def chart_regions(page: object) -> list[dict]:
    """Split the page into the two diagram columns from their titles.

    The left edge is the title word, which sits left of the phrase span, so the
    region starts 30 pt before the phrase; the right edge stops 40 pt short of
    the next column's title so the two charts cannot share a tick label.
    """
    spans = spans_of(page)
    anchors = []
    for phrase in ("safe operating area", "transient thermal impedance"):
        hit = [s for s in spans if phrase in _normalise(s["text"])]
        if len(hit) != 1:
            raise SystemExit(f"expected exactly one {phrase!r} title span, found {len(hit)}")
        anchors.append(hit[0])
    anchors.sort(key=lambda s: s["bbox"][0])
    width = page.rect.width
    regions = []
    for i, span in enumerate(anchors):
        right = anchors[i + 1]["bbox"][0] - 40.0 if i + 1 < len(anchors) else width
        name = "soa" if i == 0 else "zth"
        regions.append({"name": name, "x0": span["bbox"][0] - 30.0, "x1": right,
                         "y0": span["bbox"][3]})
    return regions


def tick_labels(spans: list[dict], region: dict) -> list[dict]:
    """``10`` plus a raised integer exponent, e.g. the label of a decade tick.

    The exponent is a separate 5 pt span whose left edge touches the 8 pt
    ``10`` span.  The x-axis labels are the ones sitting lowest on the page;
    every other tick label in the same column belongs to the y axis.
    """
    out = []
    for i, span in enumerate(spans):
        if span["text"] != "10" or abs(span["size"] - 8.0) > 0.1:
            continue
        box = span["bbox"]
        if not (region["x0"] <= box[0] <= region["x1"] and box[1] > region["y0"]):
            continue
        for other in spans[i + 1:]:
            if not AXIS_EXPONENT.match(other["text"]) or abs(other["size"] - 5.0) > 0.1:
                continue
            tail = other["bbox"]
            if abs(tail[0] - box[2]) < 0.6 and abs(tail[1] - box[1]) < 3.0:
                out.append({"value": 10 ** int(other["text"]), "box": box, "exponent_box": tail})
                break
    if len(out) < 4:
        raise SystemExit(f"{region['name']}: found only {len(out)} decade labels")
    lowest = max(label["box"][1] for label in out)
    for label in out:
        label["axis"] = "x" if abs(label["box"][1] - lowest) <= 1.0 else "y"
    return out


def _combined_centre(label: dict, axis: str) -> float:
    """Centres the label as one block: the exponent is part of it."""
    lo = 0 if axis == "x" else 1
    hi = 2 if axis == "x" else 3
    return (min(label["box"][lo], label["exponent_box"][lo])
            + max(label["box"][hi], label["exponent_box"][hi])) / 2.0


def _least_squares(points: list[tuple[float, float]]) -> tuple[float, float]:
    n = len(points)
    mx = sum(p[0] for p in points) / n
    my = sum(p[1] for p in points) / n
    slope = sum((x - mx) * (y - my) for x, y in points) / sum((x - mx) ** 2 for x, _ in points)
    return my - slope * mx, slope


def calibrate(labels: list[dict]) -> dict:
    """Fit position = zero + pt_per_decade * log10(value) on each axis."""
    out = {}
    for axis in ("x", "y"):
        group = [label for label in labels if label["axis"] == axis]
        if len(group) < 2:
            raise SystemExit(f"need two {axis} tick labels to calibrate")
        intercept, slope = _least_squares([(math.log10(g["value"]), _combined_centre(g, axis))
                                           for g in group])
        out[f"{axis}_zero_pt"] = intercept
        out[f"{axis}_pt_per_decade"] = slope
        out[f"{axis}_ticks"] = sorted(g["value"] for g in group)
    return out


def to_value(pos: float, zero: float, pt_per_decade: float) -> float:
    return 10.0 ** ((pos - zero) / pt_per_decade)


def strokes(page: object) -> list[tuple[float, float, float, float]]:
    out = []
    for drawing in page.get_drawings():
        width = drawing.get("width")
        if width is None or abs(width - CURVE_STROKE_PT) > STROKE_TOLERANCE_PT:
            continue
        for item in drawing["items"]:
            if item[0] == "l":
                a, b = item[1], item[2]
                out.append((a.x, a.y, b.x, b.y))
    return out


def _inside(box: tuple[float, float, float, float], x: float, y: float, pad: float = 0.0) -> bool:
    return box[0] - pad <= x <= box[2] + pad and box[1] - pad <= y <= box[3] + pad


def chain(segments: list[tuple[float, float, float, float]]) -> list[list[tuple[float, float]]]:
    """Join touching chords into polylines, never doubling back on a merge."""
    grid = lambda v: round(v / CHAIN_TOLERANCE_PT)
    edges: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    for index, (x1, y1, x2, y2) in enumerate(segments):
        edges[(grid(x1), grid(y1))].append((index, 0))
        edges[(grid(x2), grid(y2))].append((index, 1))
    used = [False] * len(segments)
    chains: list[list[tuple[float, float]]] = []

    def other_end(index: int, end: int) -> tuple[float, float]:
        x1, y1, x2, y2 = segments[index]
        return (x2, y2) if end == 0 else (x1, y1)

    for start in range(len(segments)):
        if used[start]:
            continue
        used[start] = True
        points = [(segments[start][0], segments[start][1]), (segments[start][2], segments[start][3])]
        for forward in (True, False):
            while True:
                end = points[-1] if forward else points[0]
                prev = points[-2] if forward else points[1]
                vx, vy = end[0] - prev[0], end[1] - prev[1]
                norm = math.hypot(vx, vy) or 1.0
                vx, vy = vx / norm, vy / norm
                best, best_dot = None, -2.0
                for index, side in edges[(grid(end[0]), grid(end[1]))]:
                    if used[index]:
                        continue
                    far = other_end(index, side)
                    wx, wy = far[0] - end[0], far[1] - end[1]
                    length = math.hypot(wx, wy) or 1.0
                    dot = (vx * wx + vy * wy) / length
                    if dot > best_dot:
                        best, best_dot = (index, far), dot
                if best is None or best_dot < CHAIN_MIN_COSINE:
                    break
                used[best[0]] = True
                if forward:
                    points.append(best[1])
                else:
                    points.insert(0, best[1])
        chains.append(points)
    return chains


def _plot_box(labels: list[dict], pad: float = PLOT_PADDING_PT) -> tuple[float, float, float, float]:
    xs, ys = [], []
    for label in labels:
        for box in (label["box"], label["exponent_box"]):
            xs.extend((box[0], box[2]))
            ys.extend((box[1], box[3]))
    return (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)


def legend_box(spans: list[dict], region: dict) -> tuple[float, float, float, float] | None:
    """Bounding box of the Zth legend swatches, which are not data.

    The legend texts are fixed strings in the drawing; if a revision renames
    them the box shrinks and the envelope check below fails loudly.
    """
    wanted = {"single pulse", "0.01", "0.02", "0.05", "0.1", "0.2", "0.5"}
    boxes = [s["bbox"] for s in spans
             if region["x0"] <= s["bbox"][0] <= region["x1"] and s["text"].strip().lower() in wanted]
    if len(boxes) < 4:
        return None
    return (min(b[0] for b in boxes) - 4.0, min(b[1] for b in boxes) - 4.0,
            max(b[2] for b in boxes) + 4.0, max(b[3] for b in boxes) + 4.0)


def soa_labels(spans: list[dict], box: tuple[float, float, float, float]) -> list[dict]:
    out = []
    for span in spans:
        text = span["text"].strip()
        if text.upper() == "DC":
            out.append({"label": "DC", "pulse_s": None, "box": span["bbox"]})
            continue
        match = SOA_LABEL.match(text.replace("µs", "us"))
        if match and match.group("unit") in UNIT_S and _inside(box, *span["bbox"][:2]):
            out.append({"label": f"{match.group('n')} {match.group('unit')}",
                        "pulse_s": _round(int(match.group("n")) * UNIT_S[match.group("unit")]),
                        "box": span["bbox"]})
    return out


def _log_i_at(points: list[tuple[float, float]], v: float) -> float:
    """Interpolate log I against log V; clamp outside the drawn range."""
    best = min(points, key=lambda p: abs(math.log10(p[0] / v)))
    if v <= points[0][0]:
        return points[0][1]
    if v >= points[-1][0]:
        return points[-1][1]
    for (v0, i0), (v1, i1) in zip(points, points[1:]):
        if v0 <= v <= v1 and v1 > v0:
            share = (math.log10(v) - math.log10(v0)) / (math.log10(v1) - math.log10(v0))
            return 10.0 ** (math.log10(i0) + share * (math.log10(i1) - math.log10(i0)))
    return best[1]


def digitize(pdf: Path) -> dict:
    page, page_index = load_page(pdf)
    spans = spans_of(page)
    regions = chart_regions(page)
    segments = strokes(page)
    result = {
        "source": {
            "pdf": str(pdf.relative_to(ROOT)).replace("\\", "/"),
            "sha256": hashlib.sha256(Path(pdf).read_bytes()).hexdigest(),
            "page_index": page_index,
            "page_size_pt": [round(page.rect.width, 2), round(page.rect.height, 2)],
        },
        "method": {
            "text": ("decade tick labels are paired with their drawn strokes; the single-pulse "
                     "trace is the only family drawn with long chords and is verified to be the "
                     "lower envelope of all ink"),
            "calibration_error": ("axes are fitted from tick-label centres; the drawn 40 V edge "
                                  "reads 41.07 V and the 1140 A plateau reads 1125 A, so treat "
                                  "either axis as a few percent"),
        },
    }
    checks = {}
    for region in regions:
        labels = tick_labels(spans, region)
        calibration = calibrate(labels)
        box = _plot_box(labels)
        inside = [s for s in segments
                  if _inside(box, s[0], s[1]) and _inside(box, s[2], s[3])]
        x_to_value = lambda x: to_value(x, calibration["x_zero_pt"], calibration["x_pt_per_decade"])
        y_to_value = lambda y: to_value(y, calibration["y_zero_pt"], calibration["y_pt_per_decade"])
        result.setdefault("calibration", {})[region["name"]] = calibration

        if region["name"] == "soa":
            chains = sorted(chain(inside), key=len, reverse=True)
            if len(chains) < 6:
                raise SystemExit(f"expected six SOA curves, recovered {len(chains)}")
            if len(chains) > 6 and len(chains[5]) < 2 * len(chains[6]):
                raise SystemExit("the sixth SOA chain is not separated from the noise chords")
            curves = []
            for points in chains[:6]:
                if points[0][0] > points[-1][0]:
                    points = points[::-1]
                curves.append([(x_to_value(x), y_to_value(y)) for x, y in points])
            legend = soa_labels(spans, box)
            if len(legend) != 6:
                raise SystemExit(f"expected six SOA labels, found {len(legend)}: "
                                 f"{[g['label'] for g in legend]}")
            assigned = _match(curves, legend, x_to_value, y_to_value)
            ordered = sorted(assigned, key=lambda pair: (pair[0]["pulse_s"] is None,
                                                         pair[0]["pulse_s"] or 0.0))
            result["soa"] = {"curves": [
                {"label": label["label"], "pulse_s": label["pulse_s"],
                 "points": [[_round(v), _round(i)] for v, i in curve]}
                for label, curve in ordered]}
            checks["six_soa_curves_recovered"] = len(result["soa"]["curves"]) == 6
            checks["soa_labels_form_a_bijection"] = True
        else:
            skip = legend_box(spans, region)
            data = [s for s in inside
                    if skip is None or not (_inside(skip, s[0], s[1]) or _inside(skip, s[2], s[3]))]
            solid = [s for s in data if math.hypot(s[2] - s[0], s[3] - s[1]) > SOLID_CHORD_MIN_PT]
            chains = sorted(chain(solid), key=len, reverse=True)
            if len(chains) != 1 or len(chains[0]) < 20:
                raise SystemExit(f"expected one single-pulse trace, recovered {len(chains)}")
            points = chains[0]
            if points[0][0] > points[-1][0]:
                points = points[::-1]
            _assert_lower_envelope(points, data)
            trace = [[_round(x_to_value(x)), _round(y_to_value(y))] for x, y in points]
            result["zth"] = {"single_pulse": trace, "duty_curves_digitized": False}
            checks["single_pulse_trace_is_the_lower_envelope"] = True
            checks["zth_is_monotone"] = all(b[1] >= a[1] * 0.999 for a, b in zip(trace, trace[1:]))

    result["checks"] = {"ok": all(checks.values()), **checks}
    return result


def _round(value: float) -> float:
    return float(f"{value:.6g}")


def _match(curves: list[list[tuple[float, float]]], labels: list[dict],
           x_to_value, y_to_value) -> list[tuple[dict, list[tuple[float, float]]]]:
    """Exhaustive label-to-curve assignment minimising total log-I distance."""
    centres = []
    for label in labels:
        box = label["box"]
        centres.append((x_to_value((box[0] + box[2]) / 2.0), y_to_value((box[1] + box[3]) / 2.0)))
    cost = [[abs(math.log10(_log_i_at(curve, v)) - math.log10(i)) for curve in curves]
            for v, i in centres]
    best, best_total = None, math.inf
    for perm in _permutations(range(len(curves))):
        total = sum(cost[j][perm[j]] for j in range(len(labels)))
        if total < best_total:
            best, best_total = perm, total
    if best is None:
        raise SystemExit("no label-to-curve assignment exists")
    assignment = [(labels[j], curves[best[j]]) for j in range(len(labels))]
    if sum(abs(math.log10(_log_i_at(c, v)) - math.log10(i)) for (v, i), (_, c) in
           zip(centres, assignment)) > 1.0:
        raise SystemExit("label-to-curve assignment is not confident")
    return assignment


def _permutations(items: range) -> list[tuple[int, ...]]:
    if len(items) == 1:
        return [(items[0],)]
    out = []
    for i, head in enumerate(items):
        rest = [x for x in items if x != head]
        for tail in _permutations(rest):
            out.append((head,) + tail)
    return out


def _assert_lower_envelope(points: list[tuple[float, float]],
                           segments: list[tuple[float, float, float, float]]) -> None:
    """No ink may sit below the trace, measured at the same abscissa.

    Sampling the chord's own stroke at its vertex returns the same y, so the
    comparison is one-sided: only a *foreign* stroke below the trace fails.
    """
    ink: dict[float, float] = defaultdict(float)
    samples = sorted({round(p[0], 3) for p in points})
    for x0, y0, x1, y1 in segments:
        for x in samples:
            if min(x0, x1) - 0.5 <= x <= max(x0, x1) + 0.5:
                if abs(x1 - x0) < 1e-9:
                    ink[x] = max(ink[x], max(y0, y1))
                else:
                    share = (x - x0) / (x1 - x0)
                    ink[x] = max(ink[x], y0 + share * (y1 - y0))
    for x, y in points:
        key = round(x, 3)
        if key in ink and ink[key] > y + ENVELOPE_TOLERANCE_PT:
            raise SystemExit(f"the long-chord trace at x={x:.2f} is not the lower envelope "
                             f"(y={y:.2f}, lowest ink y={ink[key]:.2f})")


def soa_limit_at(curve: dict, voltage: float) -> float:
    """The chart's current limit at ``voltage``, interpolated in log-log."""
    return _log_i_at([tuple(p) for p in curve["points"]], voltage)


def zth_at(trace: list[list[float]], seconds: float) -> float:
    """Zth at a pulse width, with a square-root extension below the drawn floor.

    The chart starts at 10 us; a 5 ns solver step is far below it.  Between the
    first two digitised points the drawn trace is steep, but using its slope
    would understate Zth for shorter pulses, so the extension uses the
    square-root asymptote, which is the conservative side.
    """
    if seconds >= trace[-1][0]:
        return trace[-1][1]
    if seconds <= trace[0][0]:
        return trace[0][1] * math.sqrt(seconds / trace[0][0])
    for (t0, z0), (t1, z1) in zip(trace, trace[1:]):
        if t0 <= seconds <= t1:
            share = (math.log10(seconds) - math.log10(t0)) / (math.log10(t1) - math.log10(t0))
            return 10.0 ** (math.log10(z0) + share * (math.log10(z1) - math.log10(z0)))
    return trace[-1][1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    args = parser.parse_args()
    data = digitize(args.pdf)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {args.json}")
    if not data["checks"]["ok"]:
        raise SystemExit("digitisation checks failed")


if __name__ == "__main__":
    main()

"""Plan the G1 driver-ECO short-loop copper and check it offline before creating it.

The placement candidate is accepted (``driver_eco_report.json``).  This module
turns the roadmap step -- real copper for the primary gate loops, the
high-side bootstrap, and workable supply returns -- into explicit segments,
checks them against every pad read back from the native board, and emits the
LCEDA invocation body that creates exactly those segments.

Two copper layers are used.  The committed :data:`PLAN` is the layer-1 gate
loop.  Its geometry seals the bootstrap diode outside the GH_DRV wall, so the
bootstrap, SW return, VCC12 and PGND connections cross to the bottom layer
through vias (:data:`STUBS` = short layer-1 pad-to-via stubs, :data:`BOTTOM` =
the layer-2 runs, :data:`VIAS` = the through holes between them).

Clearance checking is layer aware: a trace only conflicts with copper on its
own layer, but a via is a hole through every layer, so it must clear every pad
and trace regardless of layer.  New LCEDA boards default to two copper layers
(``PCB_Layer.setTheNumberOfCopperLayers`` remarks); ``emit_js`` refuses to run
if the board reports fewer than two rather than silently changing the stackup.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
from pathlib import Path

import make_g1_report as g

HERE = Path(__file__).resolve().parent
MIL = g.MIL
#: mm hard floor before creation.  This is the board's own safety-spacing value
#: for Track/Pad/Via against each other in the 1 oz table of
#: ``driver_rules_raw.json`` (Track vs Track is 0.102 there, Copper Zone 0.254);
#: keeping the floor at the strictest applicable number means the offline check
#: cannot pass something the native DRC would flag for track/pad/via contacts.
#: Copper zones (0.254) are not modelled offline; there are none in this window.
CLEARANCE = 0.152

#: net -> width (mm) and one or more polylines (mm, Y down).  Branches are
#: separate polylines that meet on a junction; consecutive points are one segment.
PLAN: dict[str, dict] = {
    "GH_DRV": {"width": 0.25, "paths": [[(52.499, 62.499), (51.0, 62.499),
                                         (49.174, 60.673), (49.174, 57.501)]]},
    "GH": {"width": 0.2, "paths": [
        [(50.681, 57.501), (50.681, 56.3), (48.247, 56.3), (48.247, 55.001)],
        # Branch from the T at x=49.05, not from (50.681, 56.3): starting at the
        # trunk end would draw the 1.631 mm run twice and inflate the planned
        # length against the readback.
        [(49.05, 56.3), (49.05, 53.6), (49.268, 53.332),
         (49.268, 52.751), (49.903, 52.751)]]},
    "GL_DRV": {"width": 0.25, "paths": [[(55.499, 61.001), (57.0, 61.001),
                                         (58.174, 59.827), (58.174, 57.501)]]},
    "GL": {"width": 0.2, "paths": [
        [(59.680, 57.501), (59.680, 56.3), (57.247, 56.3), (57.247, 55.001)],
        [(58.05, 56.3), (58.05, 53.6), (58.268, 53.332),
         (58.268, 52.751), (58.903, 52.751)]]},
    "HB": {"width": 0.3, "paths": [[(52.499, 61.999), (51.8, 61.999),
                                    (50.3, 60.499), (50.3, 60.0)]]},
}

#: Layer-1 stubs: pad centre -> via centre.  Every stub is short and same-net.
#: The HB stub into C5.1 is deliberately diagonal: a collinear continuation of
#: the existing HB line would be merged by the editor on save and then read back
#: as one unplanned segment.
STUBS: dict[str, dict] = {
    "HB": {"width": 0.25, "layer": 1, "paths": [
        [(45.827, 61.999), (44.8, 61.999)],
        [(50.3, 60.0), (50.9, 59.0)]]},
    "VCC12": {"width": 0.25, "layer": 1, "paths": [
        [(48.174, 61.999), (48.174, 63.5)],
        [(52.499, 61.001), (51.6, 61.001)],
        [(56.299, 65.001), (56.299, 63.9)],
        [(56.299, 67.0), (56.299, 66.0)]]},
    "PGND": {"width": 0.25, "layer": 1, "paths": [
        [(55.499, 61.501), (56.5, 61.56)],
        [(58.753, 55.001), (58.753, 54.0)],
        [(57.701, 65.001), (57.701, 63.9)],
        [(57.701, 67.0), (57.701, 66.0)]]},
    "SW": {"width": 0.25, "layer": 1, "paths": [
        [(52.499, 63.0), (52.499, 63.9)],
        [(51.699, 60.0), (51.699, 59.0)],
        [(49.754, 55.001), (49.754, 54.0)]]},
}

#: Layer-2 runs between the vias.  They may pass under layer-1 SMD pads; only
#: through-hole (multi-layer) pads and other layer-2 copper are obstacles.
BOTTOM: dict[str, dict] = {
    "HB": {"width": 0.3, "layer": 2, "paths": [
        [(44.8, 61.999), (50.9, 59.0)]]},
    "VCC12": {"width": 0.3, "layer": 2, "paths": [
        [(48.174, 63.5), (51.6, 61.001), (51.6, 64.8), (56.299, 64.8)],
        [(56.299, 63.9), (56.299, 66.0)]]},
    "PGND": {"width": 0.3, "layer": 2, "paths": [
        [(56.5, 61.56), (57.701, 63.9)],
        [(57.701, 63.9), (57.701, 66.0)],
        [(56.5, 61.56), (58.753, 54.0)]]},
    "SW": {"width": 0.3, "layer": 2, "paths": [
        [(52.499, 63.9), (52.6, 62.5), (51.699, 59.0), (49.754, 54.0)]]},
}

#: The board's own rule set ("JLCPCB Capability(Two Layers Board)", read with
#: ``pcb_Drc.getCurrentRuleConfiguration()``) allows 0.3 <= inner <= 6.3 mm and
#: 0.5 <= outer <= 10 mm.  The editor stores mil at 0.1 mil, truncated: a 0.5 mm
#: outer comes back as 19.6 mil (0.4978 mm), i.e. just under the rule minimum,
#: so the outer is asked for as 0.505 mm and lands at 19.8 mil.  The drill moved
#: from 0.2 to 0.3 mm because the native DRC reported 13 "Via Size" errors
#: (7.9 < 11.8 mil).  Going to 0.6 mm outer instead would break three
#: trace-to-via clearances (0.559/0.564/0.595 mm against 0.575/0.6).
VIA_HOLE = 0.3
VIA_DIAMETER = 0.505

#: net, centre (board mm, Y down).  Every via must be touched by a same-net
#: stub or bottom run; ``check_plan`` rejects a dangling via.
VIAS = [
    {"net": "HB", "x": 44.8, "y": 61.999},
    {"net": "HB", "x": 50.9, "y": 59.0},
    {"net": "VCC12", "x": 48.174, "y": 63.5},
    {"net": "VCC12", "x": 51.6, "y": 61.001},
    {"net": "VCC12", "x": 56.299, "y": 63.9},
    {"net": "VCC12", "x": 56.299, "y": 66.0},
    {"net": "PGND", "x": 56.5, "y": 61.56},
    {"net": "PGND", "x": 58.753, "y": 54.0},
    {"net": "PGND", "x": 57.701, "y": 63.9},
    {"net": "PGND", "x": 57.701, "y": 66.0},
    {"net": "SW", "x": 52.499, "y": 63.9},
    {"net": "SW", "x": 51.699, "y": 59.0},
    {"net": "SW", "x": 49.754, "y": 54.0},
]
for _v in VIAS:
    _v.setdefault("hole", VIA_HOLE)
    _v.setdefault("diameter", VIA_DIAMETER)

#: Connections deliberately left out of this increment.
REMAINING = [
    {"net": "SW", "endpoints": ["C5.2", "R18.2", "QH.1-3"],
     "blocker": "C5.2 -> R18.2 is now routed on layer 2; the QH.1-3 source pins are a "
                "100 A power-loop connection and must be copper pour/bar, not this signal trace."},
]



def _plan_list(plan) -> list[dict]:
    """Accept one plan dict or a list of them."""
    return list(plan) if isinstance(plan, (list, tuple)) else [plan]


def segments(plan) -> list[dict]:
    """Flatten one or more plans into the individual straight segments."""
    out = []
    for one in _plan_list(plan):
        for net, spec in one.items():
            layer = spec.get("layer", 1)
            for pts in spec["paths"]:
                for a, b in zip(pts, pts[1:]):
                    out.append({"net": net, "width": spec["width"], "layer": layer,
                                "a": a, "b": b})
    return out


def load_pads(readback: Path) -> list[dict]:
    """Pads with their true net, layer and rotated bounding box, in board mm (Y down).

    A pad with no net is still copper: ``net`` becomes ``""`` so it can never
    equal a planned net, and it stays an obstacle.  Dropping it (the first
    version skipped them) hid a track running straight through D_CT1.2 - the
    native DRC reported 0 mil where the rule wants >= 6 mil.
    """
    value = json.loads(readback.read_text(encoding="utf-8"))["value"]
    pads = []
    for p in value["pads"]:
        x0, y0, x1, y1 = g.pad_bbox_mm(p)
        pads.append({"ref": p.get("ref"), "pin": str(p.get("PadNumber")),
                     "net": p.get("Net") or "", "layer": p.get("Layer", 1),
                     "bbox": (x0, y0, x1, y1),
                     "x": (x0 + x1) / 2, "y": (y0 + y1) / 2})
    return pads


def _pad_on_layer(pad_layer: int, trace_layer: int) -> bool:
    """A pad blocks a trace when it is on that layer or is a multi-layer pad."""
    return pad_layer in (0, 12) or pad_layer == trace_layer


def _point_segment(px: float, py: float, a: tuple, b: tuple) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    if dx == dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _segment_segment(a: tuple, b: tuple, c: tuple, d: tuple) -> float:
    """Minimum distance between two closed segments (0 when they intersect)."""
    def orient(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    def on_seg(p, q, r):
        return (min(p[0], r[0]) - 1e-12 <= q[0] <= max(p[0], r[0]) + 1e-12
                and min(p[1], r[1]) - 1e-12 <= q[1] <= max(p[1], r[1]) + 1e-12)

    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    if ((o1 > 0) != (o2 > 0)) and ((o3 > 0) != (o4 > 0)):
        return 0.0
    if o1 == 0 and on_seg(a, c, b):
        return 0.0
    if o2 == 0 and on_seg(a, d, b):
        return 0.0
    if o3 == 0 and on_seg(c, a, d):
        return 0.0
    if o4 == 0 and on_seg(c, b, d):
        return 0.0
    return min(_point_segment(*a, c, d), _point_segment(*b, c, d),
               _point_segment(*c, a, b), _point_segment(*d, a, b))


def _segment_rect(a: tuple, b: tuple, box: tuple) -> float:
    x0, y0, x1, y1 = box
    if x0 <= a[0] <= x1 and y0 <= a[1] <= y1:
        return 0.0
    if x0 <= b[0] <= x1 and y0 <= b[1] <= y1:
        return 0.0
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    edges = list(zip(corners, corners[1:] + corners[:1]))
    return min(_segment_segment(a, b, c, d) for c, d in edges)


def _point_rect(px: float, py: float, box: tuple) -> float:
    x0, y0, x1, y1 = box
    return math.hypot(max(x0 - px, 0.0, px - x1), max(y0 - py, 0.0, py - y1))


def find_conflicts(pads: list[dict], segs: list[dict], clearance: float = CLEARANCE,
                   vias: list[dict] | None = None) -> list[dict]:
    """Layer-aware clearances.

    A trace only meets copper on its own layer, so layer-1 SMD pads do not block
    a layer-2 run.  A via is a through hole: it is checked against every pad and
    every trace regardless of layer.
    """
    vias = vias or []
    out = []
    for s in segs:
        layer = s.get("layer", 1)
        for p in pads:
            if p["net"] == s["net"] or not _pad_on_layer(p["layer"], layer):
                continue
            need = s["width"] / 2 + clearance
            d = _segment_rect(s["a"], s["b"], p["bbox"])
            if d < need - 1e-9:
                out.append({"kind": "pad", "net": s["net"], "layer": layer,
                            "other": f"{p['ref']}.{p['pin']}", "other_net": p["net"],
                            "distance_mm": round(d, 4), "needed_mm": round(need, 4)})
        for v in vias:
            if v["net"] == s["net"]:
                continue
            need = s["width"] / 2 + v["diameter"] / 2 + clearance
            d = _point_segment(v["x"], v["y"], s["a"], s["b"])
            if d < need - 1e-9:
                out.append({"kind": "via", "net": s["net"], "other": f"via {v['net']}",
                            "other_net": v["net"], "distance_mm": round(d, 4),
                            "needed_mm": round(need, 4)})
    for s1, s2 in itertools.combinations(segs, 2):
        if s1["net"] == s2["net"] or s1.get("layer", 1) != s2.get("layer", 1):
            continue
        need = (s1["width"] + s2["width"]) / 2 + clearance
        d = _segment_segment(s1["a"], s1["b"], s2["a"], s2["b"])
        if d < need - 1e-9:
            out.append({"kind": "trace", "net": s1["net"], "other": s2["net"],
                        "layer": s1.get("layer", 1),
                        "distance_mm": round(d, 4), "needed_mm": round(need, 4)})
    for v in vias:
        for p in pads:
            if p["net"] == v["net"]:
                continue
            need = v["diameter"] / 2 + clearance
            d = _point_rect(v["x"], v["y"], p["bbox"])
            if d < need - 1e-9:
                out.append({"kind": "via-pad", "net": v["net"], "other": f"{p['ref']}.{p['pin']}",
                            "other_net": p["net"], "distance_mm": round(d, 4),
                            "needed_mm": round(need, 4)})
    for v1, v2 in itertools.combinations(vias, 2):
        if v1["net"] == v2["net"]:
            continue
        need = (v1["diameter"] + v2["diameter"]) / 2 + clearance
        d = math.hypot(v1["x"] - v2["x"], v1["y"] - v2["y"])
        if d < need - 1e-9:
            out.append({"kind": "via-via", "net": v1["net"], "other": v2["net"],
                        "distance_mm": round(d, 4), "needed_mm": round(need, 4)})
    return out


def margins(pads: list[dict], segs: list[dict], vias: list[dict] | None = None) -> list[dict]:
    """Per-net tightest clearance actually available, for the report."""
    vias = vias or []
    rows = []
    for net in sorted({s["net"] for s in segs} | {v["net"] for v in vias}):
        best = None
        for s in (s for s in segs if s["net"] == net):
            for p in pads:
                if p["net"] == net or not _pad_on_layer(p["layer"], s.get("layer", 1)):
                    continue
                d = _segment_rect(s["a"], s["b"], p["bbox"]) - s["width"] / 2
                best = d if best is None else min(best, d)
            for s2 in segs:
                if s2["net"] == net or s2.get("layer", 1) != s.get("layer", 1):
                    continue
                d = _segment_segment(s["a"], s["b"], s2["a"], s2["b"]) - (s["width"] + s2["width"]) / 2
                best = d if best is None else min(best, d)
            for v in vias:
                if v["net"] == net:
                    continue
                d = _point_segment(v["x"], v["y"], s["a"], s["b"]) - s["width"] / 2 - v["diameter"] / 2
                best = d if best is None else min(best, d)
        for v in (v for v in vias if v["net"] == net):
            for p in pads:
                if p["net"] == net:
                    continue
                d = _point_rect(v["x"], v["y"], p["bbox"]) - v["diameter"] / 2
                best = d if best is None else min(best, d)
            for v2 in vias:
                if v2["net"] == net:
                    continue
                d = math.hypot(v["x"] - v2["x"], v["y"] - v2["y"]) - (v["diameter"] + v2["diameter"]) / 2
                best = d if best is None else min(best, d)
        rows.append({"net": net, "min_clearance_mm": round(best, 3) if best is not None else None})
    return rows


def endpoint_problems(pads: list[dict], path: dict, same_net: tuple = (), tol: float = 0.02,
                      vias: list[dict] | None = None) -> list[str]:
    """First/last point of each polyline must land on a same-net pad, trace or via."""
    vias = vias or []
    layer = path.get("layer", 1)
    problems = []
    for label, pt in (("start", path["points"][0]), ("end", path["points"][-1])):
        on_pad = any(p["net"] == path["net"] and _pad_on_layer(p["layer"], layer)
                     and p["bbox"][0] - tol <= pt[0] <= p["bbox"][2] + tol
                     and p["bbox"][1] - tol <= pt[1] <= p["bbox"][3] + tol for p in pads)
        on_trace = any(s["net"] == path["net"] and s.get("layer", 1) == layer
                       and _point_segment(pt[0], pt[1], s["a"], s["b"]) <= tol
                       for s in same_net)
        on_via = any(v["net"] == path["net"]
                     and math.hypot(v["x"] - pt[0], v["y"] - pt[1]) <= tol for v in vias)
        if not (on_pad or on_trace or on_via):
            problems.append(f"{path['net']} {label} {pt} is not on a same-net pad, trace or via")
    return problems


def check_plan(pads: list[dict], plan, clearance: float = CLEARANCE,
               vias: list[dict] | None = None) -> list[dict]:
    """Check one plan or a list of plans, plus the vias that join them."""
    vias = vias or []
    plans = _plan_list(plan)
    segs = segments(plans)
    problems = find_conflicts(pads, segs, clearance, vias)
    for one in plans:
        for net, spec in one.items():
            layer = spec.get("layer", 1)
            for pts in spec["paths"]:
                problems += [{"kind": "endpoint", "net": net, "detail": d}
                             for d in endpoint_problems(
                                 pads, {"net": net, "layer": layer, "points": pts},
                                 tuple(s for s in segs if s["net"] == net), vias=vias)]
    for v in vias:
        touched = any(s["net"] == v["net"] and (
            math.hypot(s["a"][0] - v["x"], s["a"][1] - v["y"]) <= 0.02
            or math.hypot(s["b"][0] - v["x"], s["b"][1] - v["y"]) <= 0.02
            or _point_segment(v["x"], v["y"], s["a"], s["b"]) <= 0.02) for s in segs)
        if not touched:
            problems.append({"kind": "via-dangling", "net": v["net"],
                             "at": [v["x"], v["y"]]})
    return problems


def _mil(x: float, y: float) -> tuple[float, float]:
    return round(x * MIL, 3), round(-y * MIL, 3)


def emit_js(plan, vias: list[dict] | None = None) -> str:
    """LCEDA invocation body: open the board, create the lines and vias, save.

    Refuses to run on a board with fewer than two copper layers: growing the
    stackup is a reviewable design change, not something this script may do
    silently.
    """
    vias = vias or []
    rows = []
    for s in segments(plan):
        a = _mil(*s["a"])
        b = _mil(*s["b"])
        rows.append([s["net"], s["layer"], round(s["width"] * MIL, 3),
                     a[0], a[1], b[0], b[1]])
    via_rows = []
    for v in vias:
        x, y = _mil(v["x"], v["y"])
        via_rows.append([v["net"], x, y, round(v["hole"] * MIL, 3),
                         round(v["diameter"] * MIL, 3)])
    return """return await (async () => {
  let board;
  for (let i = 0; i < 20 && !board; i++) {
    const info = await eda.dmt_Project.getCurrentProjectInfo();
    board = info?.data?.find(b => b?.pcb?.uuid);
    if (!board) await new Promise(r => setTimeout(r, 500));
  }
  if (!board) throw new Error('PCB document missing');
  await eda.dmt_EditorControl.openDocument(board.pcb.uuid);
  await new Promise(r => setTimeout(r, 1000));
  const copperLayers = await eda.pcb_Layer.getTheNumberOfCopperLayers();
  if (copperLayers < 2) {
    throw new Error('board reports ' + copperLayers + ' copper layer(s); this plan needs 2. '
      + 'Changing the stackup is a separate reviewed design step.');
  }
  const lines = %s;
  const vias = %s;
  const out = { copperLayers, created: [], failed: [], viasCreated: [] };
  for (const [net, layer, w, x1, y1, x2, y2] of lines) {
    try {
      const l = await eda.pcb_PrimitiveLine.create(net, layer, x1, y1, x2, y2, w, false);
      if (!l) { out.failed.push([net, layer, x1, y1, x2, y2, 'null']); continue; }
      out.created.push([net, layer, x1, y1, x2, y2, w,
                        l.getState_PrimitiveId ? l.getState_PrimitiveId() : null]);
    } catch (e) {
      out.failed.push([net, layer, x1, y1, x2, y2, String(e && e.message || e)]);
    }
  }
  for (const [net, x, y, hole, diameter] of vias) {
    try {
      const v = await eda.pcb_PrimitiveVia.create(net, x, y, hole, diameter, 0, null);
      if (!v) { out.failed.push(['via', net, x, y, 'null']); continue; }
      out.viasCreated.push([net, x, y, hole, diameter,
                            v.getState_PrimitiveId ? v.getState_PrimitiveId() : null]);
    } catch (e) {
      out.failed.push(['via', net, x, y, String(e && e.message || e)]);
    }
  }
  out.lines = (await eda.pcb_PrimitiveLine.getAll()).length;
  out.vias = (await eda.pcb_PrimitiveVia.getAll()).length;
  out.saved = await eda.pcb_Document.save();
  return out;
})();""" % (json.dumps(rows), json.dumps(via_rows))


def _covered(plan_seg: dict, mine: list[dict], tol: float = 0.01) -> tuple[bool, list[dict]]:
    """Is every point of ``plan_seg`` covered by collinear same-net readback lines?

    The editor splits a polyline at a T-junction on save, so a planned segment
    can come back as two halves.  Coverage, not one-to-one identity, is what
    guarantees the copper exists.
    """
    ax, ay = plan_seg["a"]
    bx, by = plan_seg["b"]
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    spans = []
    for s in mine:
        if abs(s["width"] - plan_seg["width"]) > tol:
            continue
        if s.get("layer", 1) != plan_seg.get("layer", 1):
            continue
        if any(abs(_point_segment(pt[0], pt[1], plan_seg["a"], plan_seg["b"])) > tol
               for pt in (s["a"], s["b"])):
            continue  # a different segment of the same net, not part of this wall
        ts = sorted(((p[0] - ax) * dx + (p[1] - ay) * dy) / (length * length) for p in (s["a"], s["b"]))
        lo, hi = max(0.0, ts[0]), min(1.0, ts[1])
        if hi > lo:
            spans.append((lo, hi))
    if not spans:
        return False, [{"reason": "no readback line for this net and width"}]
    spans.sort()
    end = 0.0
    for lo, hi in spans:
        if lo > end + tol / max(length, 1e-9):
            return False, [{"reason": "gap in coverage", "at_t": round(end, 4)}]
        end = max(end, hi)
    return end >= 1.0 - tol / max(length, 1e-9), []


def verify_lines(plan, lines_mm: list[dict], tol: float = 0.01) -> list[dict]:
    """Check readback lines cover the plan and every line lies on the plan."""
    planned = segments(plan)
    problems = []
    for p in planned:
        ok, why = _covered(p, lines_mm, tol)
        if not ok:
            problems.append({"kind": "coverage", "net": p["net"], "layer": p["layer"],
                             "at": [p["a"], p["b"]], "why": why})
    for s in lines_mm:
        hit = any(
            s["net"] == p["net"] and s.get("layer", 1) == p["layer"]
            and abs(s["width"] - p["width"]) <= tol
            and all(_point_segment(*pt, p["a"], p["b"]) <= tol for pt in (s["a"], s["b"]))
            for p in planned)
        if not hit:
            problems.append({"kind": "unplanned", "net": s["net"], "layer": s.get("layer", 1),
                             "at": [s["a"], s["b"]]})
    return problems


def lines_from_readback(readback: Path) -> list[dict]:
    value = json.loads(readback.read_text(encoding="utf-8"))["value"]
    return [{"net": l["net"], "layer": l["layer"], "width": l["width"] / MIL,
             "a": (l["x1"] / MIL, -l["y1"] / MIL), "b": (l["x2"] / MIL, -l["y2"] / MIL)}
            for l in value["lines"]]


def vias_from_readback(readback: Path) -> list[dict]:
    value = json.loads(readback.read_text(encoding="utf-8"))["value"]
    return [{"net": v["net"], "x": v["x"] / MIL, "y": -v["y"] / MIL,
             "hole": v["hole"] / MIL, "diameter": v["diameter"] / MIL}
            for v in value.get("vias", [])]


def verify_vias(vias: list[dict], readback_vias: list[dict], tol: float = 0.02) -> list[dict]:
    """Every planned via must exist at its centre and no unplanned via may remain."""
    problems = []
    for v in vias:
        hit = any(r["net"] == v["net"]
                  and math.hypot(r["x"] - v["x"], r["y"] - v["y"]) <= tol
                  and abs(r["diameter"] - v["diameter"]) <= tol for r in readback_vias)
        if not hit:
            problems.append({"kind": "via-missing", "net": v["net"], "at": [v["x"], v["y"]]})
    for r in readback_vias:
        hit = any(r["net"] == v["net"] and math.hypot(r["x"] - v["x"], r["y"] - v["y"]) <= tol
                  for v in vias)
        if not hit:
            problems.append({"kind": "via-unplanned", "net": r["net"], "at": [r["x"], r["y"]]})
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--emit-js", action="store_true", help="print the LCEDA body")
    ap.add_argument("--write-plan", action="store_true", help="write driver_route_plan.json")
    ap.add_argument("--check", action="store_true", help="run the offline check")
    ap.add_argument("--verify", action="store_true", help="verify a fresh reopen readback")
    args = ap.parse_args()
    pads = load_pads(HERE / "driver_readback.json")
    plans = [PLAN, STUBS, BOTTOM]
    segs = segments(plans)
    problems = check_plan(pads, plans, vias=VIAS)
    if args.emit_js:
        print(emit_js(plans, VIAS))
    if args.verify:
        return verify_and_report()
    if args.check or not (args.emit_js or args.write_plan):
        print(json.dumps({"pads": len(pads), "segments": len(segs), "vias": len(VIAS),
                          "problems": problems, "margins": margins(pads, segs, VIAS)},
                         ensure_ascii=False, indent=2))
    if args.write_plan:
        payload = {"date": "2026-11-10", "status": "G1_ROUTE_PLAN_NOT_FOR_FAB",
                   "clearance_floor_mm": CLEARANCE,
                   "layers": 2, "via_hole_mm": VIA_HOLE, "via_diameter_mm": VIA_DIAMETER,
                   "layer_1_plan": PLAN, "layer_1_stubs": STUBS, "layer_2_plan": BOTTOM,
                   "vias": VIAS, "segments": segs,
                   "margins": margins(pads, segs, VIAS),
                   "remaining_connections": REMAINING}
        (HERE / "driver_route_plan.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 1 if problems else 0


def _sha(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def drc_summary(path: Path | None = None) -> dict | None:
    """Group counts from the native DRC raw export (``None`` when it is absent).

    ``driver_drc_raw.json`` is written by ``run_driver_drc.py``; it holds the
    untouched ``pcb_Drc.check(true, false, true)`` envelope.
    """
    path = path or (HERE / "driver_drc_raw.json")
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8")).get("value") or {}
    groups = {}
    for group in value.get("raw") or []:
        groups[group["name"]] = sum(len(net.get("list") or [])
                                    for net in group.get("list") or [])
    return {"rule_config": value.get("rule_config"), "groups": groups,
            "physical_errors": groups.get("Physical Error", 0),
            "total_errors": sum(groups.values()), "source": path.name}


def verify_and_report() -> int:
    """Turn the fresh-reopen readback into the route increment record."""
    readback_path = HERE / "driver_route_readback.json"
    value = json.loads(readback_path.read_text(encoding="utf-8"))["value"]
    lines = lines_from_readback(readback_path)
    readback_vias = vias_from_readback(readback_path)
    plans = [PLAN, STUBS, BOTTOM]
    line_problems = verify_lines(plans, lines)
    via_problems = verify_vias(VIAS, readback_vias)
    base = json.loads((HERE / "driver_readback.json").read_text(encoding="utf-8"))["value"]
    old = {c["ref"]: (c["X"], c["Y"]) for c in base["components"]}
    drift = [{"ref": c["ref"], "dx_mil": round(c["X"] - old[c["ref"]][0], 4),
              "dy_mil": round(c["Y"] - old[c["ref"]][1], 4)}
             for c in value["components"] if c["ref"] in old
             and (abs(c["X"] - old[c["ref"]][0]) > 1e-6 or abs(c["Y"] - old[c["ref"]][1]) > 1e-6)]
    counts_ok = (len(value["components"]) == 77 and len(value["pads"]) == 299
                 and len(value["nets"]) == 65 and value["polylines"] == 38)
    per_net = {}
    for s in segments(plans):
        length = math.hypot(s["b"][0] - s["a"][0], s["b"][1] - s["a"][1])
        per_net[s["net"]] = round(per_net.get(s["net"], 0) + length, 3)
    readback_per_net = {}
    for s in lines:
        length = math.hypot(s["b"][0] - s["a"][0], s["b"][1] - s["a"][1])
        readback_per_net[s["net"]] = round(readback_per_net.get(s["net"], 0) + length, 3)
    drc = drc_summary()
    report = {
        "date": "2026-11-10", "status": "G1_ROUTE_INCREMENT_NOT_FOR_FAB",
        "hardware_qualified": False, "partial_routing": True, "fully_routed": False,
        "native_drc_passed": bool(drc and drc["total_errors"] == 0), "erc_passed": False,
        "native_drc": drc or {"source": None,
                              "why": "driver_drc_raw.json not present; run run_driver_drc.py"},
        "geometry_evidence": "NATIVE_REOPEN_READBACK",
        "layout_counts": {"components": len(value["components"]), "pads": len(value["pads"]),
                          "nets": len(value["nets"]), "polylines": value["polylines"],
                          "unchanged": counts_ok},
        "lines": {"count": len(lines),
                  "by_layer": {str(n): sum(1 for s in lines if s.get("layer") == n)
                               for n in sorted({s.get("layer") for s in lines})},
                  "planned_segments": len(segments(plans)),
                  "planned_length_mm_per_net": per_net,
                  "readback_length_mm_per_net": readback_per_net,
                  "coverage_problems": line_problems},
        "vias": {"planned": len(VIAS), "readback": len(readback_vias),
                 "hole_mm": VIA_HOLE, "diameter_mm": VIA_DIAMETER,
                 "annular_ring_mm": round((VIA_DIAMETER - VIA_HOLE) / 2, 4),
                 "problems": via_problems},
        "placement_drift": drift,
        "nets_routed": sorted(set(PLAN) | set(STUBS) | set(BOTTOM)),
        "remaining_connections": REMAINING,
        "limitations": [
            "The QH.1-3 source connection is a 100 A power loop; it is not part of this signal-level increment.",
            "Native DRC ran (see native_drc): no physical error, but 224 connection errors remain on "
            "board-level nets that are not routed yet and the PCB/schematic netlist does not match; "
            "ERC has not been run.",
            "No netlist connectivity check beyond endpoints and coverage; the editor's ratsnest must still confirm.",
            "Bottom-layer runs pass under layer-1 SMD pads by design; the native DRC accepted that geometry.",
            "Magnetics still have 24 provisional pads and T1-T4/CT have no physical footprint.",
            "This does not change the NOT_FOR_FAB gate.",
        ],
        "sha256": {n: _sha(HERE / n) for n in
                   ["driver_route_readback.json", "driver_route_plan.json", "driver_route.js"]},
    }
    (HERE / "driver_route_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"lines": len(lines), "vias": len(readback_vias),
                      "coverage_problems": line_problems, "via_problems": via_problems,
                      "placement_drift": drift, "counts_unchanged": counts_ok}, indent=2))
    return 0 if (counts_ok and not line_problems and not via_problems and not drift) else 1


if __name__ == "__main__":
    raise SystemExit(main())

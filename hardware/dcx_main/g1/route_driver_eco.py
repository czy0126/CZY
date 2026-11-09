"""Plan the G1 driver-ECO short-loop copper and check it offline before creating it.

The placement candidate is accepted (``driver_eco_report.json``).  This module
turns the next roadmap step -- real copper for the primary gate loops, the
high-side bootstrap, and workable supply returns -- into explicit segments,
checks them against every pad read back from the native board, and emits the
LCEDA invocation body that creates exactly those segments.

Only layer-1 copper is planned: ``pcb_PrimitiveLine.create`` refuses the other
layers, so a connection that would have to cross another net has no legal
one-layer path and is listed in :data:`REMAINING` instead of being drawn
through a pad.
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
CLEARANCE = 0.15  # mm hard floor before creation; the report prints real margins

#: net -> width (mm) and one or more polylines (mm, Y down).  Branches are
#: separate polylines that meet on a junction; consecutive points are one segment.
PLAN: dict[str, dict] = {
    "GH_DRV": {"width": 0.25, "paths": [[(52.499, 62.499), (51.0, 62.499),
                                         (49.174, 60.673), (49.174, 57.501)]]},
    "GH": {"width": 0.2, "paths": [
        [(50.681, 57.501), (50.681, 56.3), (48.247, 56.3), (48.247, 55.001)],
        [(50.681, 56.3), (49.05, 56.3), (49.05, 53.6), (49.268, 53.332),
         (49.268, 52.751), (49.903, 52.751)]]},
    "GL_DRV": {"width": 0.25, "paths": [[(55.499, 61.001), (57.0, 61.001),
                                         (58.174, 59.827), (58.174, 57.501)]]},
    "GL": {"width": 0.2, "paths": [
        [(59.680, 57.501), (59.680, 56.3), (57.247, 56.3), (57.247, 55.001)],
        [(59.680, 56.3), (58.05, 56.3), (58.05, 53.6), (58.268, 53.332),
         (58.268, 52.751), (58.903, 52.751)]]},
    "HB": {"width": 0.3, "paths": [[(52.499, 61.999), (51.8, 61.999),
                                    (50.3, 60.499), (50.3, 60.0)]]},
}

#: Connections the placement makes impossible on one copper layer, with the wall.
REMAINING = [
    {"net": "SW", "endpoints": ["U2.5", "C5.2"],
     "blocker": "U2.3->C5.1 (HB) crosses the only channel left of the pin column; "
                "the HB and SW pads are interleaved (U2.3 above U2.5, C5.1 right of C5.2)."},
    {"net": "SW", "endpoints": ["C5.2", "R18.2", "QH.1-3"],
     "blocker": "the GH wall (R4.2->R18.1 and the x=49.05 drop to QH.4) seals the corridor "
                "between R18 and the QH gate pins."},
    {"net": "HB", "endpoints": ["D_BT.1", "C5.1"],
     "blocker": "D_BT sits left of the GH_DRV wall (x=49.174 from y=60.673 to 57.501); "
                "the direct path crosses it.  Moving D_BT right of that wall is the cheap fix."},
    {"net": "VCC12", "endpoints": ["D_BT.2", "U2.1"],
     "blocker": "same GH_DRV wall; also C5.1 occupies y=59.55..60.45 on any low detour."},
    {"net": "VCC12", "endpoints": ["U2.1", "C103.1", "C104.1"],
     "blocker": "the run must cross the PGND return corridor at the same pins; "
                "needs a pour or a second layer."},
    {"net": "PGND", "endpoints": ["U2.9", "R19.2", "C103.2", "C104.2"],
     "blocker": "crosses the VCC12 drop to C103 at x=56.299 and the GL horizontal at y=56.3."},
]


def segments(plan: dict[str, dict]) -> list[dict]:
    """Flatten a plan into the individual straight segments."""
    out = []
    for net, spec in plan.items():
        for pts in spec["paths"]:
            for a, b in zip(pts, pts[1:]):
                out.append({"net": net, "width": spec["width"], "a": a, "b": b})
    return out


def load_pads(readback: Path) -> list[dict]:
    """Pads with their true net and rotated bounding box, in board mm (Y down)."""
    value = json.loads(readback.read_text(encoding="utf-8"))["value"]
    pads = []
    for p in value["pads"]:
        if not p.get("Net"):
            continue
        x0, y0, x1, y1 = g.pad_bbox_mm(p)
        pads.append({"ref": p.get("ref"), "pin": str(p.get("PadNumber")),
                     "net": p["Net"], "bbox": (x0, y0, x1, y1),
                     "x": (x0 + x1) / 2, "y": (y0 + y1) / 2})
    return pads


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


def find_conflicts(pads: list[dict], segs: list[dict], clearance: float = CLEARANCE) -> list[dict]:
    """Foreign-pad clearance plus net-to-net trace spacing on one layer."""
    out = []
    for s in segs:
        for p in pads:
            if p["net"] == s["net"]:
                continue
            need = s["width"] / 2 + clearance
            d = _segment_rect(s["a"], s["b"], p["bbox"])
            if d < need - 1e-9:
                out.append({"kind": "pad", "net": s["net"], "other": f"{p['ref']}.{p['pin']}",
                            "other_net": p["net"], "distance_mm": round(d, 4),
                            "needed_mm": round(need, 4)})
    for s1, s2 in itertools.combinations(segs, 2):
        if s1["net"] == s2["net"]:
            continue
        need = (s1["width"] + s2["width"]) / 2 + clearance
        d = _segment_segment(s1["a"], s1["b"], s2["a"], s2["b"])
        if d < need - 1e-9:
            out.append({"kind": "trace", "net": s1["net"], "other": s2["net"],
                        "distance_mm": round(d, 4), "needed_mm": round(need, 4)})
    return out


def margins(pads: list[dict], segs: list[dict]) -> list[dict]:
    """Per-net tightest clearance actually available, for the report."""
    rows = []
    for net in sorted({s["net"] for s in segs}):
        mine = [s for s in segs if s["net"] == net]
        best = None
        for s in mine:
            for p in pads:
                if p["net"] == net:
                    continue
                d = _segment_rect(s["a"], s["b"], p["bbox"]) - s["width"] / 2
                if best is None or d < best:
                    best = d
            for s2 in segs:
                if s2["net"] == net:
                    continue
                d = _segment_segment(s["a"], s["b"], s2["a"], s2["b"]) - (s["width"] + s2["width"]) / 2
                if best is None or d < best:
                    best = d
        rows.append({"net": net, "min_clearance_mm": round(best, 3) if best is not None else None})
    return rows


def endpoint_problems(pads: list[dict], path: dict, same_net: tuple = (), tol: float = 0.02) -> list[str]:
    """First/last point of each polyline must land on a same-net pad or a same-net junction."""
    problems = []
    for label, pt in (("start", path["points"][0]), ("end", path["points"][-1])):
        on_pad = any(p["net"] == path["net"]
                     and p["bbox"][0] - tol <= pt[0] <= p["bbox"][2] + tol
                     and p["bbox"][1] - tol <= pt[1] <= p["bbox"][3] + tol for p in pads)
        on_trace = any(s["net"] == path["net"] and _point_segment(pt[0], pt[1], s["a"], s["b"]) <= tol
                       for s in same_net)
        if not (on_pad or on_trace):
            problems.append(f"{path['net']} {label} {pt} is not on a pad of the same net")
    return problems


def check_plan(pads: list[dict], plan: dict[str, dict], clearance: float = CLEARANCE) -> list[dict]:
    segs = segments(plan)
    problems = find_conflicts(pads, segs, clearance)
    for net, spec in plan.items():
        for pts in spec["paths"]:
            problems += [{"kind": "endpoint", "net": net, "detail": d}
                         for d in endpoint_problems(pads, {"net": net, "points": pts},
                                                    tuple(s for s in segs if s["net"] == net))]
    return problems


def _mil(x: float, y: float) -> tuple[float, float]:
    return round(x * MIL, 3), round(-y * MIL, 3)


def emit_js(plan: dict[str, dict]) -> str:
    """LCEDA invocation body: open the board, create the layer-1 lines, save."""
    rows = []
    for net, spec in plan.items():
        w = round(spec["width"] * MIL, 3)
        for pts in spec["paths"]:
            mil = [_mil(x, y) for x, y in pts]
            for a, b in zip(mil, mil[1:]):
                rows.append([net, w, a[0], a[1], b[0], b[1]])
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
  const lines = %s;
  const out = { created: [], failed: [] };
  for (const [net, w, x1, y1, x2, y2] of lines) {
    try {
      const l = await eda.pcb_PrimitiveLine.create(net, 1, x1, y1, x2, y2, w, false);
      if (!l) { out.failed.push([net, x1, y1, x2, y2, 'null']); continue; }
      out.created.push([net, x1, y1, x2, y2, w,
                        l.getState_PrimitiveId ? l.getState_PrimitiveId() : null]);
    } catch (e) {
      out.failed.push([net, x1, y1, x2, y2, String(e && e.message || e)]);
    }
  }
  out.total = (await eda.pcb_PrimitiveLine.getAll()).length;
  out.saved = await eda.pcb_Document.save();
  return out;
})();""" % json.dumps(rows)


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


def verify_lines(plan: dict[str, dict], lines_mm: list[dict], tol: float = 0.01) -> list[dict]:
    """Check readback lines cover the plan and every line lies on the plan."""
    planned = segments(plan)
    problems = []
    for p in planned:
        ok, why = _covered(p, lines_mm, tol)
        if not ok:
            problems.append({"kind": "coverage", "net": p["net"], "at": [p["a"], p["b"]], "why": why})
    for s in lines_mm:
        hit = s.get("layer", 1) == 1 and any(
            s["net"] == p["net"] and abs(s["width"] - p["width"]) <= tol
            and all(_point_segment(*pt, p["a"], p["b"]) <= tol for pt in (s["a"], s["b"]))
            for p in planned)
        if not hit:
            problems.append({"kind": "unplanned", "net": s["net"], "at": [s["a"], s["b"]]})
    return problems


def lines_from_readback(readback: Path) -> list[dict]:
    value = json.loads(readback.read_text(encoding="utf-8"))["value"]
    return [{"net": l["net"], "layer": l["layer"], "width": l["width"] / MIL,
             "a": (l["x1"] / MIL, -l["y1"] / MIL), "b": (l["x2"] / MIL, -l["y2"] / MIL)}
            for l in value["lines"]]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--emit-js", action="store_true", help="print the LCEDA body")
    ap.add_argument("--write-plan", action="store_true", help="write driver_route_plan.json")
    ap.add_argument("--check", action="store_true", help="run the offline check")
    ap.add_argument("--verify", action="store_true", help="verify a fresh reopen readback")
    args = ap.parse_args()
    pads = load_pads(HERE / "driver_readback.json")
    problems = check_plan(pads, PLAN)
    if args.emit_js:
        print(emit_js(PLAN))
    if args.verify:
        return verify_and_report()
    if args.check or not (args.emit_js or args.write_plan):
        print(json.dumps({"pads": len(pads), "segments": len(segments(PLAN)),
                          "problems": problems, "margins": margins(pads, segments(PLAN))},
                         ensure_ascii=False, indent=2))
    if args.write_plan:
        payload = {"date": "2026-11-10", "status": "G1_ROUTE_PLAN_NOT_FOR_FAB",
                   "layer": 1, "clearance_floor_mm": CLEARANCE,
                   "plan": PLAN, "segments": segments(PLAN),
                   "margins": margins(pads, segments(PLAN)),
                   "remaining_connections": REMAINING}
        (HERE / "driver_route_plan.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 1 if problems else 0


def _sha(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_and_report() -> int:
    """Turn the fresh-reopen readback into the route increment record."""
    readback_path = HERE / "driver_route_readback.json"
    value = json.loads(readback_path.read_text(encoding="utf-8"))["value"]
    lines = lines_from_readback(readback_path)
    line_problems = verify_lines(PLAN, lines)
    base = json.loads((HERE / "driver_readback.json").read_text(encoding="utf-8"))["value"]
    old = {c["ref"]: (c["X"], c["Y"]) for c in base["components"]}
    drift = [{"ref": c["ref"], "dx_mil": round(c["X"] - old[c["ref"]][0], 4),
              "dy_mil": round(c["Y"] - old[c["ref"]][1], 4)}
             for c in value["components"] if c["ref"] in old
             and (abs(c["X"] - old[c["ref"]][0]) > 1e-6 or abs(c["Y"] - old[c["ref"]][1]) > 1e-6)]
    counts_ok = (len(value["components"]) == 77 and len(value["pads"]) == 299
                 and len(value["nets"]) == 65 and value["polylines"] == 38)
    per_net = {}
    for s in segments(PLAN):
        length = math.hypot(s["b"][0] - s["a"][0], s["b"][1] - s["a"][1])
        per_net[s["net"]] = round(per_net.get(s["net"], 0) + length, 3)
    readback_per_net = {}
    for s in lines:
        length = math.hypot(s["b"][0] - s["a"][0], s["b"][1] - s["a"][1])
        readback_per_net[s["net"]] = round(readback_per_net.get(s["net"], 0) + length, 3)
    report = {
        "date": "2026-11-10", "status": "G1_ROUTE_INCREMENT_NOT_FOR_FAB",
        "hardware_qualified": False, "partial_routing": True, "fully_routed": False,
        "native_drc_passed": False, "erc_passed": False,
        "geometry_evidence": "NATIVE_REOPEN_READBACK",
        "layout_counts": {"components": len(value["components"]), "pads": len(value["pads"]),
                          "nets": len(value["nets"]), "polylines": value["polylines"],
                          "unchanged": counts_ok},
        "lines": {"count": len(lines), "layer": 1,
                  "planned_segments": len(segments(PLAN)),
                  "planned_length_mm_per_net": per_net,
                  "readback_length_mm_per_net": readback_per_net,
                  "coverage_problems": line_problems},
        "placement_drift": drift,
        "nets_routed": sorted(PLAN),
        "remaining_connections": REMAINING,
        "limitations": [
            "One copper layer only; the remaining connections need a pour, a second layer, or a placement change.",
            "No native DRC/ERC export yet; clearances are the offline 0.15 mm floor and are not a DRC result.",
            "No netlist connectivity check beyond endpoints and coverage; the editor's ratsnest/DRC must confirm.",
            "Magnetics still have 24 provisional pads and T1-T4/CT have no physical footprint.",
            "This does not change the NOT_FOR_FAB gate.",
        ],
        "sha256": {n: _sha(HERE / n) for n in
                   ["driver_route_readback.json", "driver_route_plan.json", "driver_route.js"]},
    }
    (HERE / "driver_route_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"lines": len(lines), "coverage_problems": line_problems,
                      "placement_drift": drift, "counts_unchanged": counts_ok}, indent=2))
    return 0 if (counts_ok and not line_problems and not drift) else 1


if __name__ == "__main__":
    raise SystemExit(main())

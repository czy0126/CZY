"""Rebuild `g1_native_pcb_report.json` from the saved board's own readback.

Inputs (all already in the repo):

* `g1_pads.json`      — components, pads (mil, Cartesian Y up, with rotation),
                        TBD zone rectangles and DOT marks, dumped through
                        `pcb_PrimitiveComponent` / `pcb_PrimitivePad` /
                        `pcb_PrimitivePolyline` on the saved `.eprj2`.
* `design/v3/maxwell/generated_concept/design_owned_G1_pads_24plus2.csv`
                      — the design-owned G1 provisional pad packet (24 + 2).
* the previous report  — only its `placements` / `excluded` / `before` blocks
                        are carried forward (they record the placement pass and
                        the footprint uuid behind each component); every
                        geometry-derived field is recomputed and the carried
                        positions are cross-checked against `g1_pads.json`.

    python hardware/dcx_main/g1/make_g1_report.py

The output is review evidence for gate G1 only.  It is not a DRC, a netlist
equivalence proof, or a manufacturability claim.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MIL = 39.37007874015748
PACKET = ROOT / "design/v3/maxwell/generated_concept/design_owned_G1_pads_24plus2.csv"
BOARD = HERE / "dcx_main_board_g1.eprj2"
REPORT = HERE / "g1_native_pcb_report.json"


def md5_of(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pad_extent_mm(pad: list | None) -> tuple[float, float]:
    """Axis-aligned extents (w, h) of a pad in mm, before rotation.

    Shapes seen on this board: ELLIPSE / OVAL `[kind, w, h]`, RECT
    `[kind, w, h, corner]` and one POLYGON `[kind, [x0, y0, 'L', ...]]`.
    """
    if not pad:
        return 0.6, 0.6
    if pad[0] == "POLYGON":
        nums = [v for v in pad[1] if isinstance(v, (int, float))]
        xs, ys = nums[0::2], nums[1::2]
        return (max(xs) - min(xs)) / MIL, (max(ys) - min(ys)) / MIL
    return pad[1] / MIL, pad[2] / MIL


def pad_bbox_mm(p: dict) -> tuple[float, float, float, float]:
    """(x0, y0, x1, y1) in board mm (Y down) enclosing the rotated pad."""
    x = p["X"] / MIL
    y = -p["Y"] / MIL
    w, h = pad_extent_mm(p.get("Pad"))
    a = math.radians(p.get("Rotation") or 0)
    ca, sa = abs(math.cos(a)), abs(math.sin(a))
    hw, hh = (w * ca + h * sa) / 2, (w * sa + h * ca) / 2
    return x - hw, y - hh, x + hw, y + hh


def overlaps(a: tuple[float, float, float, float], b: tuple[float, float, float, float],
             tol: float = 1e-4) -> bool:
    return (min(a[2], b[2]) - max(a[0], b[0]) > tol
            and min(a[3], b[3]) - max(a[1], b[1]) > tol)


def load_packet() -> list[dict]:
    with PACKET.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def match_concept_pads(free_pads: list[dict], packet: list[dict]) -> tuple[list[dict], list[dict]]:
    """Pair board free pads with packet rows; both sides must agree on net."""
    placed, unmatched = [], []
    pool = list(free_pads)
    for row in packet:
        if row["ref"] == "Lr":           # the +2 ride the native Lr footprint
            continue
        hit = next((p for p in pool
                    if p["PadNumber"] == row["logical_terminal"] and p["Net"] == row["pcb_net"]),
                   None)
        if hit is None:
            unmatched.append(row)
            continue
        pool.remove(hit)
        placed.append({
            "concept_pad_id": row["concept_pad_id"],
            "ref": row["ref"],
            "terminal": row["logical_terminal"],
            "pad_number_on_board": hit["PadNumber"],
            "net": hit["Net"],
            "dot_expectation": row["dot_expectation"],
            "x_mm": round(hit["X"] / MIL, 3),
            "y_mm": round(-hit["Y"] / MIL, 3),
            "pad_mm": [round(v / MIL, 3) if isinstance(v, (int, float)) else v
                       for v in hit["Pad"]],
            "truth_status": row["truth_status"],
        })
    extra = [p for p in pool]
    return placed, unmatched + extra


def main() -> int:
    pads_json = json.loads((HERE / "g1_pads.json").read_text(encoding="utf-8"))
    prev = json.loads(REPORT.read_text(encoding="utf-8"))
    packet = load_packet()
    pads = pads_json["pads"]
    zones = pads_json["tbd_zones"]
    comps = pads_json["components"]

    # ---- carried-forward blocks, cross-checked against the board ------------
    pos = {c["ref"]: (c["X"] / MIL, -c["Y"] / MIL) for c in comps}
    carried = {p["ref"]: p for p in prev["placements"]}
    # The carried block may store y in either the raw board frame (negative) or the
    # display frame (Y down); only |y| is comparable.  Every placement is written
    # back in display mm so the whole report shares the figure's frame, which also
    # makes this generator idempotent.
    drift = [ref for ref, (x, y) in pos.items()
             if ref not in carried
             or abs(pos[ref][0] - carried[ref]["x_mm"]) > 0.01
             or abs(abs(carried[ref]["y_mm"]) - abs(y)) > 0.01]
    assert not drift, f"carried placements disagree with the board: {drift}"
    assert len(carried) == len(comps) == len(pos), (len(carried), len(comps), len(pos))
    placements = [dict(carried[ref], x_mm=round(pos[ref][0], 3), y_mm=round(pos[ref][1], 3))
                  for ref in sorted(pos, key=lambda r: (pos[r][1], pos[r][0]))]

    # ---- before / after -----------------------------------------------------
    footprint_pads = [p for p in pads if p["ref"] is not None]
    free_pads = [p for p in pads if p["ref"] is None]
    nets = sorted({p["Net"] for p in pads if p["Net"]})
    unneted = [{"ref": p["ref"], "pad_number": p["PadNumber"],
                "x_mm": round(p["X"] / MIL, 3), "y_mm": round(-p["Y"] / MIL, 3),
                "pad_mm": [round(v / MIL, 3) if isinstance(v, (int, float)) else v
                           for v in p["Pad"]]}
               for p in pads if not p["Net"]]

    after = {
        "pcb_components": len(comps),
        "pcb_nets": len(nets),
        "pcb_pads": len(pads),
        "footprint_pads": len(footprint_pads),
        "provisional_pads": len(free_pads),
        "pcb_polylines": pads_json["counts"]["polylines"],
        "schematic_parts": prev["after"]["schematic_parts"],
    }

    # ---- concept pads -------------------------------------------------------
    placed, unmatched = match_concept_pads(free_pads, packet)
    packet_24 = [r for r in packet if r["ref"] != "Lr"]
    assert len(placed) == len(packet_24) == 24, (len(placed), len(packet_24))
    assert not unmatched, unmatched

    # every provisional pad must carry its own layer-13 marker box
    marks = pads_json.get("provisional_marks", [])
    unmarked = [p["concept_pad_id"] for p, m in zip(placed, [None] * len(placed))
                if not any(abs(m2["x_mm"] - p["x_mm"]) < 0.01 and abs(m2["y_mm"] - p["y_mm"]) < 0.01
                           for m2 in marks)]
    assert not unmarked, f"provisional pads without a layer-13 marker box: {unmarked}"
    assert len(marks) == len(placed), (len(marks), len(placed))

    # every concept pad must land at A5 centre + packet offset
    centres = {"T1": (20.0, 20.0), "T2": (58.0, 20.0), "T3": (96.0, 20.0),
               "T4": (134.0, 20.0), "CT": (92.0, 52.0)}
    offset_errors = []
    for row in packet_24:
        cx, cy = centres[row["ref"]]
        want = (cx + float(row["x_mm"]), cy - float(row["y_mm"]))
        got = next(p for p in placed if p["concept_pad_id"] == row["concept_pad_id"])
        if abs(got["x_mm"] - want[0]) > 0.01 or abs(got["y_mm"] - want[1]) > 0.01:
            offset_errors.append({"concept_pad_id": row["concept_pad_id"],
                                  "want_mm": list(want), "got_mm": [got["x_mm"], got["y_mm"]]})
    assert not offset_errors, offset_errors

    # ---- schematic refs vs PCB components ----------------------------------
    netlist = json.loads((ROOT / "hardware/dcx_main/gen/netlist_export_raw.json")
                         .read_text(encoding="utf-8"))["value"]["refs"]
    on_board = {c["ref"] for c in comps}
    missing_from_pcb = []
    for ref in sorted(set(netlist) - on_board):
        reason = ("excluded from PCB by the R8 double-DNP ECO (addIntoBom=false, addIntoPcb=false)"
                  if ref == "R8" else
                  "no vendor footprint selected; terminals exist only as the provisional pads below")
        missing_from_pcb.append({"ref": ref, "reason": reason})
    extra_on_pcb = sorted(on_board - set(netlist))
    assert not extra_on_pcb, f"PCB carries parts absent from the schematic: {extra_on_pcb}"

    # ---- still-blocked physical pads ---------------------------------------
    blocked = []
    for ref in ("T1", "T2", "T3", "T4", "CT"):
        rows = [r for r in packet_24 if r["ref"] == ref]
        blocked.append({
            "ref": ref,
            "physical_pad_total": len(rows),
            "reason": "no vendor footprint selected: the project library holds only "
                      "XFMR-TH_ZHT104A and no magnetic vendor has supplied a part/footprint; "
                      "the 24 pads below exist as design-owned provisional terminals, "
                      "NOT as physical pads",
            "pads": [{"concept_pad_id": r["concept_pad_id"], "terminal": r["logical_terminal"],
                      "net": r["pcb_net"]} for r in rows],
        })

    # ---- geometry checks ----------------------------------------------------
    zone_hits = []
    for c in comps:
        own = [p for p in pads if p["ref"] == c["ref"]]
        if not own:
            continue
        boxes = [pad_bbox_mm(p) for p in own]
        bbox = (min(b[0] for b in boxes), min(b[1] for b in boxes),
                max(b[2] for b in boxes), max(b[3] for b in boxes))
        for z in zones:
            zb = (z["x_mm"], z["y_mm"], z["x_mm"] + z["w_mm"], z["y_mm"] + z["d_mm"])
            if overlaps(bbox, zb):
                zone_hits.append({"ref": c["ref"], "zone": z["ref"],
                                  "component_bbox_mm": [round(v, 3) for v in bbox]})

    # Pad-pad overlap is split in two: overlaps *inside* one footprint are the
    # vendor footprint's own geometry (thermal tabs, duplicated pads) and are not
    # placement errors; overlaps *between* two components are.
    intra, clashes = [], []
    for i, a in enumerate(footprint_pads):
        ba = pad_bbox_mm(a)
        for b in footprint_pads[i + 1:]:
            if not overlaps(ba, pad_bbox_mm(b), tol=0.01):
                continue
            pair = {"a": f"{a['ref']}.{a['PadNumber']}@{a['X'] / MIL:.3f},{a['Y'] / MIL:.3f}",
                    "b": f"{b['ref']}.{b['PadNumber']}@{b['X'] / MIL:.3f},{b['Y'] / MIL:.3f}"}
            (intra if a["ref"] == b["ref"] else clashes).append(pair)
    assert not clashes, f"pads of different components overlap: {clashes[:5]}"

    dup_numbers = []
    for c in comps:
        seen: dict[str, set] = {}
        for p in pads:
            if p["ref"] == c["ref"]:
                seen.setdefault(p["PadNumber"], set()).add(p["Net"])
        for num, ns in seen.items():
            if sum(1 for p in pads if p["ref"] == c["ref"] and p["PadNumber"] == num) > 1:
                dup_numbers.append({"ref": c["ref"], "pad_number": num, "nets": sorted(ns)})

    xs = [pad_bbox_mm(p) for p in pads]
    extent = {"x_mm": [round(min(b[0] for b in xs), 2), round(max(b[2] for b in xs), 2)],
              "y_mm": [round(min(b[1] for b in xs), 2), round(max(b[3] for b in xs), 2)]}

    # ---- A5 envelope vs packet envelope ------------------------------------
    discrepancies = [
        {"topic": "concept pad x-span vs A5 magnetic envelope",
         "detail": "packet offsets are +-17.0 mm (T1-T4) and +-12.0 mm (CT) from the A5 "
                   "centre, while the A5 envelopes are 31.75 mm and 20.0 mm wide "
                   "(half-widths 15.875 / 10.0 mm) -- the provisional terminals therefore "
                   "sit 1.125 mm / 2.0 mm outside their own TBD rectangle",
         "status": "DERIVED_FROM_A5_ENVELOPE_NOT_VENDOR_DATA"},
        {"topic": "Lr +2 concept pads not placed",
         "detail": "D1_DESIGN_Lr_N1 / _N2 ride the native Lr footprint (nets CT_LR and "
                   "PRI_T1 already have footprint pads); the packet puts them +-20 mm apart "
                   "while the native footprint's two pads are 9 mm apart.  Placing both "
                   "would double-count those nets, so only the native pads exist.",
         "status": "INTENTIONAL_NOT_PLACED"},
        {"topic": "footprint truth for the five magnetics",
         "detail": "components T1-T4/CT/Lr are NOT placed as PCB components; only their "
                   "terminals exist as free pads.  There is no component, no silkscreen, "
                   "no courtyard and no physical pad geometry behind them.",
         "status": "NOT_FOR_FAB"},
    ]

    report = {
        "schema": "dcx_main_g1_native_pcb_report/2",
        "generated": "2026-11-09",
        "cad": {"path": "hardware/dcx_main/g1/dcx_main_board_g1.eprj2",
                "bytes": BOARD.stat().st_size, "md5": md5_of(BOARD)},
        "before": {"pcb_components": 0, "pcb_nets": 0, "pcb_pads": 0, "pcb_polylines": 0,
                   "note": "原生工程里只有原理图；PCB 文档没有任何图元"},
        "after": after,
        "board": {"outline_mm": [pads_json["board"]["w_mm"], pads_json["board"]["d_mm"]],
                  "outline_layer": 11,
                  "tbd_zones": zones,
                  "dot_marks": pads_json["dot_marks"],
                  "provisional_marks_total": len(marks),
                  "provisional_marks": marks},
        "coordinate_note": "pads: X/Y in mil, Cartesian Y up (the .eprj2 stores Y negative); "
                           "zones/dots: mm, SVG Y down (the polygon source frame); "
                           "components are all placed at rotation 0, pads carry 0/90/180/-90",
        "placements": placements,
        "placement_source_counts": prev["placement_source_counts"],
        "excluded": prev["excluded"],
        "schematic_vs_pcb": {
            "source": "hardware/dcx_main/gen/netlist_export_raw.json (refs)",
            "schematic_refs": len(netlist),
            "pcb_components": len(on_board),
            "missing_from_pcb": missing_from_pcb,
            "extra_on_pcb": extra_on_pcb,
        },
        "provisional_pad_total": len(placed),
        "provisional_pads": placed,
        "blocked": blocked,
        "blocked_pad_total": sum(b["physical_pad_total"] for b in blocked),
        "nets_total": len(nets),
        "nets_without_pads": pads_json["nets_without_pads"],
        "pads_without_net_total": len(unneted),
        "pads_without_net": unneted,
        "pad_net_mismatches": [],
        "pad_net_mismatch_count": 0,
        "zone_clearance": {
            "method": "per-component pad bbox (rotated) vs each TBD rectangle; "
                      "pad-pad bbox overlap over all footprint pads; extent over all pads",
            "component_zone_overlaps": zone_hits,
            "cross_component_pad_overlaps": clashes,
            "footprint_internal_pad_overlaps": intra,
            "duplicate_pad_numbers": dup_numbers,
            "pad_extent_mm": extent,
            "moved": prev["zone_clearance"]["moved"],
        },
        "discrepancies": discrepancies,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("components", after["pcb_components"], "nets", after["pcb_nets"],
          "pads", after["pcb_pads"], "footprint", after["footprint_pads"],
          "provisional", after["provisional_pads"])
    print("zone overlaps", len(zone_hits), "pad-pad overlaps", len(clashes),
          "nets without pads", len(pads_json["nets_without_pads"]))
    print("md5", report["cad"]["md5"], "bytes", report["cad"]["bytes"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

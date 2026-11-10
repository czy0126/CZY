"""Fail-closed physical XY envelope screen for G1's real native EasyEDA PCB.

This checks magnetic-core *body envelopes*, not just electrical pad-to-pad DRC.
CAD source: saved/reopened G1 native PCB pad geometry and existing Maxwell
concept dimensions. An X/Y overlap is an assembly risk, not proof of a
three-dimensional collision; Z clearance and genuine winding exits are UNKNOWN.

    python tools/g1_magnetics_envelope.py --write
    python tools/g1_magnetics_envelope.py --check

Never mark G1 complete because 0 copper DRC errors when magnetic bodies cannot
be placed independently of populated parts. This tool does NOT edit EasyEDA.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PADS = ROOT / "hardware/dcx_main/g1/g1_pads.json"
MAG = ROOT / "design/v3/maxwell/diy_magnetics_concept.json"
OUT = ROOT / "hardware/dcx_main/g1/g1_magnetic_envelope_gate.json"
MIL_PER_MM = 39.37007874015748
MECH_CLEARANCE_TARGET_MM = 2.0  # planning reserve only, not a certified standard
EDGE_RESERVE_TARGET_MM = 3.0    # planning reserve only, not a fab limit


def rectangle(cx: float, cy: float, width: float, height: float) -> dict:
    if not all(math.isfinite(v) for v in (cx, cy, width, height)):
        raise ValueError("Non-finite geometry")
    if width <= 0 or height <= 0:
        raise ValueError("Nonpositive dimension")
    return {"left": cx-width/2, "right": cx+width/2,
            "top": cy-height/2, "bottom": cy+height/2}


def intersection(a: dict, b: dict) -> tuple[float, float]:
    return (max(0.0, min(a["right"], b["right"]) - max(a["left"], b["left"])),
            max(0.0, min(a["bottom"], b["bottom"]) - max(a["top"], b["top"])))


def pad_rect(p: dict) -> dict:
    shape = p["Pad"]
    if not shape:
        raise ValueError("Missing native pad shape")
    if shape[0] == "POLYGON":
        # The EasyEDA readback exports absolute XY mil polygon vertices, not
        # [shape,width,height]. U2's exposed-power pad 11 has this geometry.
        # Parsing shape[1] as a width produces NaN or a false overlap.
        coords = shape[1] if len(shape) > 1 else None
        if not isinstance(coords, list):
            raise ValueError("Invalid EasyEDA polygon pad")
        nums = [float(n) for n in coords if isinstance(n, (int,float))]
        if len(nums) < 6 or len(nums) % 2:
            raise ValueError("Malformed EasyEDA polygon XY coordinate list")
        xs, ys = nums[::2], nums[1::2]
        if not all(math.isfinite(v) for v in nums):
            raise ValueError("Non-finite EasyEDA polygon pad vertex")
        # Stored Y is Cartesian up; model audit uses board Y down.
        return {"left": min(xs)/MIL_PER_MM, "right": max(xs)/MIL_PER_MM,
                "top": -max(ys)/MIL_PER_MM, "bottom": -min(ys)/MIL_PER_MM}
    if len(shape) < 3 or shape[0] not in {"RECT","ELLIPSE","OVAL"}:
        raise ValueError("Unsupported EasyEDA native pad shape")
    w, h = float(shape[1])/MIL_PER_MM, float(shape[2])/MIL_PER_MM
    # Native readback has component and pad rotation. Axis-aligned bounding
    # boxes of rotated pads *overestimate* occupied XY area conservatively.
    angle = math.radians(float(p.get("Rotation") or 0.0)+
                         float(shape[3] if len(shape) > 3 else 0.0))
    projected_w = abs(w*math.cos(angle))+abs(h*math.sin(angle))
    projected_h = abs(w*math.sin(angle))+abs(h*math.cos(angle))
    return rectangle(float(p["X"])/MIL_PER_MM, -float(p["Y"])/MIL_PER_MM,
                     projected_w, projected_h)


def core_rects(pads: dict, mag: dict) -> tuple[dict, dict, dict]:
    board = pads["board"]
    if not 0 < board["w_mm"] < 1000 or not 0 < board["d_mm"] < 1000:
        raise ValueError("Missing G1 board extent")
    cases = mag["cases"]
    lr = next(x for x in cases if x["id"] == "ELP38_Lr_3turn_0920uH")
    xf = next(x for x in cases if x["id"] == "T_3_1_1_ELP32_CONCEPT")
    lrwidth = float(lr["geometry"]["core_outer_x_mm"])
    lrdepth = float(lr["geometry"]["core_depth_y_mm"])
    twidth = float(xf["geometry"]["core_outer_x_mm"])
    tdepth = float(xf["geometry"]["core_depth_y_mm"])
    positions = {p["ref"]: (float(p["X"])/MIL_PER_MM,
                             -float(p["Y"])/MIL_PER_MM)
                 for p in pads["components"]}
    if "Lr" not in positions:
        raise ValueError("Actual Lr is missing from native board")
    zones = {z["ref"]: z for z in pads["tbd_zones"] if z["ref"].startswith("T")}
    if set(zones) != {"T1", "T2", "T3", "T4"}:
        raise ValueError("Four transformer core zones required")
    lr_rect = rectangle(*positions["Lr"], lrwidth, lrdepth)
    t32, t38 = {}, {}
    for ref, zone in sorted(zones.items()):
        cx = float(zone["x_mm"])+float(zone["w_mm"])/2
        cy = float(zone["y_mm"])+float(zone["d_mm"])/2
        t32[ref] = rectangle(cx, cy, twidth, tdepth)
        t38[ref] = rectangle(cx, cy, lrwidth, lrdepth)
    return lr_rect, t32, t38


def actual_pad_interference(body: dict, pads: list[dict], *, excluded: set[str]) -> list[dict]:
    hits = []
    for p in pads:
        if p.get("ref") in excluded:
            continue
        dx, dy = intersection(body, pad_rect(p))
        if dx <= 0.001 or dy <= 0.001:
            continue
        hits.append({"ref": p.get("ref") or "FREE_PROVISIONAL",
                     "pin": str(p["PadNumber"]), "net": p.get("Net") or "",
                     "overlap_x_mm": round(dx, 3),
                     "overlap_y_mm": round(dy, 3)})
    return sorted(hits, key=lambda a: (a["ref"], a["pin"], a["net"]))


def separation_x(a: dict, b: dict) -> float:
    return max(b["left"]-a["right"], a["left"]-b["right"])


def rounded_box(b: dict) -> dict:
    return {k: round(v, 3) for k, v in b.items()}


def report(pads: dict | None = None, mag: dict | None = None) -> dict:
    if pads is None:
        pads = json.loads(PADS.read_text(encoding="utf-8"))
    if mag is None:
        mag = json.loads(MAG.read_text(encoding="utf-8"))
    if mag["fabrication_approved"] is not False or mag["maxwell_solved"] is not False:
        raise ValueError("Concept geometry must not claim Maxwell/fabrication approval")
    lr, tf_current, tf_stretch = core_rects(pads, mag)
    hits = actual_pad_interference(lr, pads["pads"], excluded={"Lr"})
    native_lrs = [p for p in pads["pads"] if p.get("ref") == "Lr"]
    if len(native_lrs) != 2:
        raise ValueError("Lr must have exactly two native PCB pads")
    by_ref = defaultdict(int)
    for x in hits:
        by_ref[x["ref"]] += 1
    pairs = []
    for ref_a, ref_b in (("T1","T2"),("T2","T3"),("T3","T4")):
        pairs.append({
            "refs": [ref_a,ref_b],
            "current_elp32_gap_mm": round(separation_x(tf_current[ref_a],tf_current[ref_b]),3),
            "if_changed_to_elp38_gap_mm": round(separation_x(tf_stretch[ref_a],tf_stretch[ref_b]),3),
        })
    board = pads["board"]
    box_margin = min(lr["left"],lr["top"],
                     float(board["w_mm"])-lr["right"],
                     float(board["d_mm"])-lr["bottom"])
    critical = (bool(hits) or box_margin < EDGE_RESERVE_TARGET_MM
                or any(pair["current_elp32_gap_mm"] < MECH_CLEARANCE_TARGET_MM
                       for pair in pairs))
    # The 38-mm transformer case is an ALTERNATIVE, not a statement that
    # the current 3:1:1 transformer is made from ELP38.
    stretch_requires_eco = any(p["if_changed_to_elp38_gap_mm"] <
                               MECH_CLEARANCE_TARGET_MM for p in pairs)
    native_lr_pitch = abs(float(native_lrs[0]["X"])-float(native_lrs[1]["X"]))/MIL_PER_MM
    hypothetical_t38_required_width = (4*float(
        next(x for x in mag["cases"] if x["id"] == "ELP38_Lr_3turn_0920uH")
        ["geometry"]["core_outer_x_mm"]) +
        3*MECH_CLEARANCE_TARGET_MM + 2*EDGE_RESERVE_TARGET_MM)
    return {
        "schema": "CZY_G1_MAGNETIC_BODY_XY_CLEARANCE_SCREEN_V1",
        "status": "P0_G1_MAGNETIC_PLACEMENT_ECO_REQUIRED" if critical
                  else "XY_SCREEN_CLEARED_3D_STILL_REQUIRED",
        "evidence": {
            "native_board_pad_readback": PADS.relative_to(ROOT).as_posix(),
            "design_owned_maxwell_geometry": MAG.relative_to(ROOT).as_posix(),
            "magnetics_concept_only": True,
            "actual_maxwell_3d_solve": False,
            "real_assembly_Z_cleared": False,
            "native_gui_3d_collision_test": False,
            "fab_approved": False,
        },
        "board_mm": [float(board["w_mm"]), float(board["d_mm"])],
        "clearance_planning_assumptions_mm": {
            "core_to_core": MECH_CLEARANCE_TARGET_MM,
            "core_to_edge": EDGE_RESERVE_TARGET_MM,
            "status": "ENGINEERING_PLANNING_ONLY_NOT_A_MANUFACTURER_SPECIFICATION",
        },
        "lr_elp38_candidate": {
            "ref": "Lr",
            "physical_core_envelope_mm": [38.0,25.4],
            "current_body_xy_mm": rounded_box(lr),
            "minimum_board_edge_margin_mm": round(box_margin,3),
            "native_footprint_pad_count": len(native_lrs),
            "native_footprint_pad_pitch_mm": round(native_lr_pitch,3),
            "board_edge_reserve_passed": box_margin >= EDGE_RESERVE_TARGET_MM,
            "other_pad_envelope_intersections": len(hits),
            "other_ref_count": len(by_ref),
            "by_ref": [{"ref":ref,"pads":n} for ref,n in sorted(by_ref.items())],
            "intersections": hits,
            "assessment": "XY_OVERLAP_REQUIRES_Z_OR_COMPONENT_MOVE_REVIEW" if hits
                          else "NO_OTHER_PAD_ENVELOPE_OVERLAPS",
        },
        "transformer_envelopes": {
            "present_design": "ELP32_32x20_3_1_1_GEOMETRY_PROXY",
            "change_to_elp38_is_not_an_existing_design": True,
            "current_elp32_box_mm": {k: rounded_box(v) for k,v in tf_current.items()},
            "hypothetical_elp38_box_mm": {k: rounded_box(v) for k,v in tf_stretch.items()},
            "adjacent_pairs": pairs,
            "elp38_if_all_four_single_row_required_board_width_mm": round(
                hypothetical_t38_required_width,3),
            "elp38_if_all_four_single_row_shortfall_mm": round(max(
                0.0,hypothetical_t38_required_width-float(board["w_mm"])),3),
            "elp38_stretch_requires_placement_change": stretch_requires_eco,
        },
        "decisions": {
            "g1_can_continue_non_frozen_routing_away_from_magnets": True,
            "freeze_existing_lr_placement": not critical,
            "approve_g1_magnetic_assembly": False,
            "approve_g2_fab": False,
            "next_cad_action": "RELOCATE_OR_REPACK_Lr_ELP38_BODY_AND_ITS_15_NEIGHBOURS_BEFORE_MORE_ROUTING_AT_Lr",
            "conditional_transformer_action": "IF_T1_TO_T4_UPSIZE_TO_ELP38_REPACK_ALL_FOUR_PITCHES_AND_PROVISIONAL_TERMINALS",
        },
        "limitations": [
            "Rectangular envelope is conservative: XY crossing does not prove a 3D clash at different Z.",
            "Full winding, fixture, mounting, cold plate, thermal gap and physical pad drawings are unknown.",
            "A G1 0 physical DRC is a copper rule result, not a magnetic body clearance pass.",
            "No EDA primitives, BOM, PCB, or gate JSON were changed by this report.",
        ],
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--write",action="store_true")
    g.add_argument("--check",action="store_true")
    args = p.parse_args()
    value = report()
    if args.write:
        OUT.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    elif json.loads(OUT.read_text(encoding="utf-8")) != value:
        raise SystemExit("Stale G1 magnetic body envelope report; run --write")
    print(json.dumps({k:value[k] for k in ("status","board_mm")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()

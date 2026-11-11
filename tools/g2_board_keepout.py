"""PCB-native land, trace and via keepout for G2 trial screw centres.

All lengths returned here are mm. Pads in EasyEDA readback have mil position
and dimensions, but PCB X/Y stores Cartesian-up Y; schematic assembly uses
down-Y. AABB for rotated pads is conservative. No access to internal zones,
component courtyards, soldermask or live mechanical connector body. This
check may REJECT a hole but cannot qualify a hole for actual fabrication.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/"hardware/dcx_main/g1/g1_100a_output_interface.json"
READBACK=ROOT/"hardware/dcx_main/g1/lr_signal_review_readback.json"
BOARD=ROOT/"hardware/dcx_main/g1/dcx_main_board_g1_signal_stubs.eprj2"
EXPECTED_BOARD_SHA256="17fbae57bebdab6e0e18b6e4ddd177da98e25ca646bcb71d5e482a3b8db7b37e"
MIL_TO_MM=.0254
M3_TRIAL_DIAMETER_MM=3.4
MIN_KNOWN_COPPER_EDGE_GAP_MM=.75  # screen, not validated process minimum


def read_source() -> dict:
    report=json.loads(REPORT.read_text(encoding="utf-8"))
    candidate=report["candidate"]
    if (candidate["path"]!=BOARD.relative_to(ROOT).as_posix()
            or candidate["sha256"]!=EXPECTED_BOARD_SHA256):
        raise ValueError("Unexpected active G1 native CAD identity in report")
    if hashlib.sha256(BOARD.read_bytes()).hexdigest()!=EXPECTED_BOARD_SHA256:
        raise ValueError("Actual native G1 .eprj2 SHA mismatch; recapture current PCB")
    if hashlib.sha256(READBACK.read_bytes()).hexdigest()!=candidate["readback_sha256"]:
        raise ValueError("G2 input changed: G1 saved/reopened native readback SHA mismatch")
    d=json.loads(READBACK.read_text(encoding="utf-8"))
    if d.get("ok") is not True:
        raise ValueError("G1 native readback was not successful")
    value=d["value"]
    if (len(value["components"]),len(value["pads"]),len(value["lines"]),
            len(value["vias"])) != (77,299,107,18):
        raise ValueError("G1 board version changed: review new actual native pads/lines")
    return value


def distance_to_box(pt,box):
    x,y=pt
    x0,y0,x1,y1=box
    return math.hypot(max(x0-x,0.,x-x1),max(y0-y,0.,y-y1))


def pad_bbox(p):
    shape=p["Pad"]
    x=float(p["X"])*MIL_TO_MM
    y=-float(p["Y"])*MIL_TO_MM
    if shape[0]=="POLYGON":
        xy=[v for v in shape[1] if isinstance(v,(int,float))]
        if not xy or len(xy)%2:raise ValueError("Malformed polygon pad")
        return (min(xy[0::2])*MIL_TO_MM,-max(xy[1::2])*MIL_TO_MM,
                max(xy[0::2])*MIL_TO_MM,-min(xy[1::2])*MIL_TO_MM)
    if shape[0] not in ("RECT","OVAL","ELLIPSE"):
        raise ValueError("Unsupported pad geometry in native G1: "+str(shape[0]))
    w,h=float(shape[1])*MIL_TO_MM,float(shape[2])*MIL_TO_MM
    a=math.radians(float(p.get("Rotation",0)))
    hx=(abs(w*math.cos(a))+abs(h*math.sin(a)))/2
    hy=(abs(w*math.sin(a))+abs(h*math.cos(a)))/2
    return (x-hx,y-hy,x+hx,y+hy)


def segment_distance(pt,a,b):
    ax,ay=a;bx,by=b;x,y=pt
    vx,vy=bx-ax,by-ay
    den=vx*vx+vy*vy
    k=max(0.,min(1.,((x-ax)*vx+(y-ay)*vy)/den)) if den>0 else 0.
    return math.hypot(x-(ax+k*vx),y-(ay+k*vy))


def native_copper_hits(pt,readback=None):
    if readback is None:readback=read_source()
    hits=[]
    for p in readback["pads"]:
        hits.append({
            "kind":"pad","ref":str(p.get("ref") or "ANONYMOUS"),
            "net":str(p.get("Net") or ""),"pin":str(p.get("PadNumber") or ""),
            "distance_to_copper_mm":distance_to_box(pt,pad_bbox(p))})
    for l in readback["lines"]:
        a=(float(l["x1"])*MIL_TO_MM,-float(l["y1"])*MIL_TO_MM)
        b=(float(l["x2"])*MIL_TO_MM,-float(l["y2"])*MIL_TO_MM)
        hits.append({"kind":"trace","ref":l["id"],"net":str(l["net"]),"pin":"",
                     "distance_to_copper_mm":max(0.,segment_distance(pt,a,b)
                                                     -float(l["width"])*MIL_TO_MM/2)})
    for via in readback["vias"]:
        hits.append({"kind":"via","ref":via["id"],"net":str(via["net"]),"pin":"",
                     "distance_to_copper_mm":max(0.,math.hypot(
                          pt[0]-float(via["x"])*MIL_TO_MM,
                          pt[1]+float(via["y"])*MIL_TO_MM)
                          -float(via["diameter"])*MIL_TO_MM/2)})
    hits.sort(key=lambda a:a["distance_to_copper_mm"])
    return hits


def audit_trial_hole(pt,readback=None):
    """Checks only *visible* G1 native copper, no PCB drill authorization."""
    if readback is None:readback=read_source()
    hits=native_copper_hits(pt,readback)
    nearest=hits[0]
    gap=nearest["distance_to_copper_mm"]-M3_TRIAL_DIAMETER_MM/2
    return {
        "centre_mm":[round(float(pt[0]),4),round(float(pt[1]),4)],
        "diameter_mm":M3_TRIAL_DIAMETER_MM,
        "known_copper_gap_mm":round(gap,4),
        "required_known_copper_gap_mm":MIN_KNOWN_COPPER_EDGE_GAP_MM,
        "nearest_known_conductor":{
            k:nearest[k] for k in ("kind","ref","net","pin")},
        "passes_visible_native_copper_clearance_only":
            gap>=MIN_KNOWN_COPPER_EDGE_GAP_MM,
        "internal_layers_zones_footprints_and_insulation_qualified":False,
        "mechanical_mating_qualified":False,
        "fab_drill_approved":False,
    }


def report() -> dict:
    native=read_source()
    original={"VOUT":(112.9995,52.2351),"PGND":(61.3994,52.2351)}
    # Examples only, do not CUT or export to fabrication DXF/STEP:
    relocated={"VOUT":(118.5,52.2351),"PGND":(62.4,52.2351)}
    before={n:audit_trial_hole(pt,native) for n,pt in original.items()}
    after={n:audit_trial_hole(pt,native) for n,pt in relocated.items()}
    if before["VOUT"]["passes_visible_native_copper_clearance_only"]:
        raise ValueError("Prior J_IN pad collision no longer detected: source drift")
    if not all(x["passes_visible_native_copper_clearance_only"] for x in after.values()):
        raise ValueError("Provisional alternate-hole keepout geometry changed")
    return {
        "status":"HOLELESS_BUSBAR_EXPORT_REQUIRED_NOT_FOR_FAB",
        "source_board":"dcx_main_board_g1_signal_stubs.eprj2",
        "prior_unsafe_m3_trial_centres":before,
        "alternate_positions_for_further_engineering_ONLY":after,
        "m3_holes_cut_into_step_or_dxf":False,
        "pads_checked":len(native["pads"]),
        "existing_tracks_checked":len(native["lines"]),
        "existing_vias_checked":len(native["vias"]),
        "other_potential_overlaps":["J_IN connector physical outline",
             "QL MOSFET body/courtyard","inner-layer copper/planes",
             "cold-plate clamp and bolt head","required drilled-hole edge clearance"],
        "fabrication_approved":False,
    }

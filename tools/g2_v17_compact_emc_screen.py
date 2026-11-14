"""High-density, EMC-first V17 floorplan screening from the V15 native pads.

This is an independently source-locked placement concept, not a new EasyEDA
board. It screens 149 device positions/419 associated pads, all 12 magnet
slots, a complete (approximate) four-core mechanical body clearance, the
output bus throat, and target area. No simulated EMI or completed routing.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from collections import defaultdict

from shapely.geometry import box
from shapely.ops import unary_union

import g2_v16_floorplan_screen as base

G = base.G
OUT = G / "g2_v17_compact_emc_first_screen_LOCKED_NOT_FOR_FAB.json"
SVG = G / "g2_v17_compact_emc_first_screen_LOCKED_NOT_FOR_FAB.svg"
WIDTH = 155.0
HEIGHT = 113.0
CORE_Y = 33.0
CORE_BODY_X_MM = 31.75 + 2 * .65
CORE_BODY_Y_MM = 20.35 + 2 * .4
CORE_TO_COMPONENT_PAD_MIN_MM = 1.5
CAP_COURTYARD_HALF_Y_MM = 2.35  # trial: 4.3mm OEM body + 0.2mm margin each side
CAP_COURTYARD_HALF_X_MM = 3.85
EDGE_CLEARANCE_MM = 2.0
THROAT = (66., 78., 86., 111.)  # x0,y0,x1,y1


def layout(native):
    xy0, _ = base.layout(native)
    xy = {}
    for ref, (x, y) in xy0.items():
        if ref.startswith("CHB"):
            yy = round(y - 17.6, 3)
        elif ref == "J_OUT":
            yy = 100.0
        elif ref == "Cout":
            yy = 72.0
        elif ref in {f"R{k}" for k in range(20,28)}:
            yy = 66.
        elif ref in {f"R{k}" for k in range(28,36)}:
            # Relocate eight SR drain-sense series resistors on the DRIVER
            # side of each FET, opposite the 66mm gate-row. The previous
            # y=68mm locations forced 11-14mm SEC sense detours around the
            # PGND/source pad row and needlessly lengthened VD_B stubs.
            # y=54.5mm passed native pad and proxy assembly clearance
            # screens; actual DRC and switch-node coupling remain required.
            yy = 54.5
        elif ref == "J_IN":
            yy = 8.
        elif y < 30.:
            yy = round(y - 7.,3)
        elif 50. <= y <= 85.:
            yy = round(y - 8.,3)
        else:
            raise ValueError("Unmapped dense V17 placement " + ref + " " + str(y))
        xy[ref] = (x, yy)
    # Gate resistors, HF bypass and sense RC are not a rigid translating cell.
    # Their original pad-bbox courtyard trials show eight <0.5mm interactions;
    # deliberately reposition the relevant parts before any native routing.
    xy.update({
        "Cin":(51.5,13.5),"U2":(54.,18.),
        "R4":(47.,14.),"R5":(60.,14.),
        "R18":(43.,12.),"R19":(66.,11.),
        "D_BT":(40.,18.),"R3":(89.,15.),"C101":(49.,19.8),
        # Shorten primary supply return without placing the connector
        # inside the half-bridge switching pair.
        "J_IN":(68.,7.),
        "C105":(25.,52.),"C106":(63.,52.),
        "C107":(101.,52.),"C108":(139.,52.),
    })
    return xy


def chassis_screen(native, positions, pad_records, slot_model):
    slot_rects = []
    hit_slots = []
    for row in slot_model["slots"]:
        slot = box(row["x_min_mm"], row["y_min_mm"]+13.,
                   row["x_max_mm"], row["y_max_mm"]+13.).buffer(.5)
        slot_rects.append({"id":row["id"],"bounds_mm":[round(z,3) for z in slot.bounds]})
        for item in pad_records:
            # 12 means all-copper pad; layer 2 is on bottom but holes are physical.
            if item["layer"] in (1,2,12) and slot.intersects(item["geom"]):
                hit_slots.append((row["id"],item["ref"],item["net"]))
    body_collisions = []
    core_body = {}
    for k,cx in enumerate(base.CORE_X):
        rectangle = box(cx-CORE_BODY_X_MM/2, CORE_Y-CORE_BODY_Y_MM/2,
                        cx+CORE_BODY_X_MM/2, CORE_Y+CORE_BODY_Y_MM/2)
        core_body["T"+str(k+1)] = [round(v,3) for v in rectangle.bounds]
        for item in pad_records:
            distance = rectangle.distance(item["geom"])
            if distance < CORE_TO_COMPONENT_PAD_MIN_MM:
                body_collisions.append((f"T{k+1}", item["ref"],round(distance,3)))
    body_collisions.sort()
    caps = []
    edge = []
    for ref, (x,y) in positions.items():
        if not ref.startswith("CHB"):continue
        court = box(x-CAP_COURTYARD_HALF_X_MM,y-CAP_COURTYARD_HALF_Y_MM,
                    x+CAP_COURTYARD_HALF_X_MM,y+CAP_COURTYARD_HALF_Y_MM)
        if court.intersects(box(*THROAT)):
            # throat tuple is x0,y0,x1,y1
            caps.append(ref)
        if (court.bounds[0] < EDGE_CLEARANCE_MM or
            court.bounds[2] > WIDTH - EDGE_CLEARANCE_MM or
            court.bounds[1] < EDGE_CLEARANCE_MM or
            court.bounds[3] > HEIGHT - EDGE_CLEARANCE_MM):
            edge.append(ref)
    return slot_rects,sorted(set(hit_slots)),core_body,body_collisions,caps,edge


def package_proxy_screen(pads, minimum_separation_mm=.5):
    """Pad-envelope + 0.45mm trial (NOT OEM body or approved courtyard)."""
    by_ref=defaultdict(list)
    by_layers=defaultdict(set)
    for pad in pads:
        by_ref[pad["ref"]].append(pad["geom"])
        by_layers[pad["ref"]].add(pad["layer"])
    env={ref:unary_union(gs).envelope.buffer(.45, cap_style="square")
         for ref,gs in by_ref.items()}
    bad=[]
    refs=sorted(env)
    for i,ref in enumerate(refs):
        for other in refs[i+1:]:
            if ref.startswith("CHB") and other.startswith("CHB"):
                continue  # OEM bank envelope+pitch checked in chassis_screen
            # Layer12 is full-through. Bottom-only C7..C10 must not be
            # called top-side conflicts unless a physical through part.
            if not (12 in by_layers[ref] or 12 in by_layers[other]
                    or by_layers[ref]&by_layers[other]):
                continue
            clearance=env[ref].distance(env[other])
            if clearance<minimum_separation_mm:
                bad.append((round(clearance,3),ref,other))
    return sorted(bad)


def generate():
    native,slot_model = base.load()
    xy = layout(native)
    comp = {x["ref"]:x for x in native["components"]}
    if len(xy)!=149 or set(xy)!=set(comp):raise ValueError("Missing native devices.")
    records = base.transferred_pad_records(native,xy)
    failures, count = base.copper_screen(records)
    slots,slot_bad,core,body_bad,corridor_bad,edge_bad = chassis_screen(native,xy,records,slot_model)
    body_proxy_fail=package_proxy_screen(records)
    cap_count = sum(x.startswith("CHB") for x in xy)
    cin_vin = base.net_min_distance(records,"Cin","VIN_P","QH","VIN_P")
    cin_gnd = base.net_min_distance(records,"Cin","PGND","QL","PGND")
    if cap_count!=72:raise ValueError("Capacitor parity lost.")
    old_h = 131.
    density = 200./(WIDTH*HEIGHT*16./1_000_000)/1000.
    return {
        "schema":"D1_V17_TIGHT_EMC_LAYOUT_NO_NATIVE_COPPER_V1",
        "source_v15_native_sha256":base.sha(base.NATIVE),
        "source_v15_pad_readback_sha256":base.sha(base.READ),
        "source_v14_ferrite_slot_DFM_sha256":base.sha(base.SLOTS),
        "manufacturing_status":"CONCEPT_ONLY_NOT_FOR_FAB",
        "board_envelope_candidate_mm":[WIDTH,HEIGHT,16.],
        "board_area_candidate_mm2":WIDTH*HEIGHT,
        "old_v15_board_envelope_mm":[WIDTH,old_h,16.],
        "old_nominal_envelope_density_kW_L":round(200./(WIDTH*old_h*16./1_000_000)/1000,3),
        "candidate_nominal_envelope_density_kW_L":round(density,3),
        "relative_geometric_density_increase_pct":round((old_h/HEIGHT-1.)*100.,2),
        "height_change_mm":HEIGHT-old_h,
        "magnet_centres_mm":[[x,CORE_Y] for x in base.CORE_X],
        "core_full_body_outer_dimension_screen_mm":[CORE_BODY_X_MM,CORE_BODY_Y_MM],
        "core_to_other_pad_min_clearance_mm":CORE_TO_COMPONENT_PAD_MIN_MM,
        "core_full_body_bboxes_mm":core,
        "core_body_to_component_pad_failures":body_bad,
        "new_true_npth_slot_list_with_keepouts_mm":slots,
        "slot_to_pad_conflicts":slot_bad,
        "real_native_associated_pads_checked":len(records),
        "real_native_components_placed":len(xy),
        "pad_net_clearance_min_mm":base.MIN_NET_CLEARANCE_MM,
        "cross_net_pad_clearance_fail_count":count,
        "cross_net_pad_clearance_fail_examples":failures,
        "trial_nonbank_courtyard_pad_envelope_margin_mm":.45,
        "trial_nonbank_courtyard_min_separation_mm":.5,
        "trial_nonbank_courtyard_pad_envelope_conflicts":body_proxy_fail,
        "chb_cap_count":cap_count,
        "cap_courtyard_trial_mm":[2*CAP_COURTYARD_HALF_X_MM,2*CAP_COURTYARD_HALF_Y_MM],
        "board_edge_cap_courtyard_min_mm":EDGE_CLEARANCE_MM,
        "output_throat_xyxy_mm":list(THROAT),
        "cap_envelope_in_output_throat":corridor_bad,
        "cap_envelope_too_close_to_board_edge":edge_bad,
        "input_loop_pad_distance_proxy_mm":round(cin_vin+cin_gnd,3),
        "sr_to_magnet_slot_end_mm":round(60.-2.821-44.,3),
        "output_terminal_xy_mm":list(xy["J_OUT"]),
        "placements_mm":{ref:[round(a,3),round(b,3)] for ref,(a,b) in sorted(xy.items())},
        "NOT_TESTED":[
            "Thermal, overmolded core profile and actual component courtyard full 3D fit",
            "Actual native 12-layer copper winding and power/return paired busbar",
            "Schematic pad association and DRC 112 old errors reconciliation",
            "CISPR 32 emissions, EFT/surge and IEC 61000-4-x tests",
            "Switch-node parasitic extracted L/C, transformer leakage, SR source Kelvin continuity",
            "48V actual input bypass/capacitors, genuine resonant capacitor RMS, 100A connector",
            "Current sharing and power/ground copper joint/via current density and FEM",
            "Coldplate 16mm/3LPM and backside components clearance"
        ],
        "native_eprj2_written":False,"native_routed":False,
        "emc_compliant_verified":False,
        "released_to_fab":False
    }


def picture(d):
    xy=d["placements_mm"]
    height=d["board_envelope_candidate_mm"][1]
    out=[f'<svg xmlns="http://www.w3.org/2000/svg" width="930" height="678" viewBox="0 0 155 113">',
         f'<rect width="155" height="{height}" fill="#f4f7fa" stroke="#283746" stroke-width=".5"/>']
    for y0,y1,col in [(0,22,"#e6edf8"),(22,44,"#ede7f6"),(44,73,"#e5f5f6"),(73,113,"#e7f1ea")]:
        out.append(f'<rect y="{y0}" width="155" height="{y1-y0}" fill="{col}"/>')
    for i,cx in enumerate(base.CORE_X):
        x0,y0,x1,y1=d["core_full_body_bboxes_mm"]["T"+str(i+1)]
        out.append(f'<rect x="{x0}" y="{y0}" width="{x1-x0}" height="{y1-y0}" fill="#d7cce9" stroke="#5e477c" stroke-width=".35"/>')
        out.append(f'<text x="{cx}" y="34" text-anchor="middle" font-size="2.8" font-family="Arial" fill="#48315a">T{i+1}</text>')
    for ref in ("QH","QL","Cin","Cr","Lr","U1","U2","J_IN"):
        x,y=xy[ref]
        out.append(f'<rect x="{x-2.5}" y="{y-2.2}" width="5" height="4.4" fill="#b6ccf1" stroke="#345b85" stroke-width=".2"/>')
        out.append(f'<text x="{x}" y="{y+.5}" font-family="Arial" font-size="1.65" text-anchor="middle">{ref}</text>')
    for i in range(4):
        for ref in (f"SR{i+1}A",f"SR{i+1}B"):
            x,y=xy[ref]
            out.append(f'<rect x="{x-3.75}" y="{y-3.2}" width="7.5" height="6.4" fill="#6ab7bd" stroke="#22747d" stroke-width=".2"/>')
            out.append(f'<text x="{x}" y="{y+.5}" font-family="Arial" font-size="1.65" text-anchor="middle">{ref}</text>')
        x,y=xy[f"U{i+3}"]
        out.append(f'<rect x="{x-2.5}" y="{y-2.6}" width="5" height="5.2" fill="#a1dade" stroke="#267076" stroke-width=".2"/>')
    for k in range(1,73):
        x,y=xy[f"CHB{k:02d}"]
        out.append(f'<rect x="{x-3.85}" y="{y-2.35}" width="7.7" height="4.7" rx=".35" fill="#a9cdac" stroke="#639369" stroke-width=".15"/>')
    x0,y0,x1,y1=d["output_throat_xyxy_mm"]
    out.append(f'<rect x="{x0}" y="{y0}" width="{x1-x0}" height="{y1-y0}" fill="#f9fafb" stroke="#a07737" stroke-width=".5" stroke-dasharray="1.2 1"/>')
    x,y=xy["J_OUT"]
    out.append(f'<rect x="{x-3}" y="{y-2.5}" width="6" height="5" fill="#f0c585" stroke="#ba7615" stroke-width=".2"/>')
    out.append(f'<text x="{x}" y="{y+.6}" font-family="Arial" text-anchor="middle" font-size="1.8">OUT</text>')
    out.append('<text x="2" y="4" font-family="Arial" font-size="3.3" fill="#1b3d64">V17 COMPACT EMC-FIRST CONCEPT / NOT NATIVE PCB</text>')
    out.append('<text x="2" y="111.8" font-family="Arial" font-size="2" fill="#982929">Pad & core-body screen ONLY; no validated DRC, 3D stackup or EMI measurement</text>')
    out.append('</svg>')
    return "\n".join(out)+"\n"


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--write",action="store_true")
    ap.add_argument("--check",action="store_true")
    args=ap.parse_args()
    data=generate()
    content=json.dumps(data,ensure_ascii=False,indent=2)+"\n"
    drawing=picture(data)
    if args.write:
        OUT.write_text(content,encoding="utf-8",newline="\n")
        SVG.write_text(drawing,encoding="utf-8",newline="\n")
    if args.check:
        if OUT.read_text("utf8") != content or SVG.read_text("utf8")!=drawing:
            raise ValueError("V17 result drift")
    print(json.dumps({
        "board_mm":data["board_envelope_candidate_mm"],
        "density_kW_L":data["candidate_nominal_envelope_density_kW_L"],
        "density_increase_pct":data["relative_geometric_density_increase_pct"],
        "pad_conflicts":data["cross_net_pad_clearance_fail_count"],
        "slot_conflicts":len(data["slot_to_pad_conflicts"]),
        "body_conflicts":len(data["core_body_to_component_pad_failures"]),
        "trial_courtyard_conflicts":len(data["trial_nonbank_courtyard_pad_envelope_conflicts"]),
        "cap_throat":data["cap_envelope_in_output_throat"],
        "cap_edge":data["cap_envelope_too_close_to_board_edge"]
    },ensure_ascii=True))


if __name__=="__main__":
    main()

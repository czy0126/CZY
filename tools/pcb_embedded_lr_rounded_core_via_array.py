"""KiCad 10 actual PCB candidate with R0.8 milled ELP slots and 4 PTH/bridge.

A square-cornered rectangle on Edge.Cuts is a physical routing fabrication
risk. This alternative EXPANDS each nominal ferrite leg cutout by the fillet
radius, then OUTSHIFTS the Lr copper loops by the same offset; this protects
old core fitting and conductor clearance simultaneously.

Native CAD is independent from both pre-existing immutable original winding
boards and from the actual EasyEDA power stage. Do not confuse 0 DRC with
vendor slot capability, N97 100C L(I), insulation or current sharing.

    python tools/pcb_embedded_lr_rounded_core_via_array.py --write
    python tools/pcb_embedded_lr_rounded_core_via_array.py --check
    python tools/pcb_embedded_lr_rounded_core_via_array.py --drc
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import subprocess
from pathlib import Path

import pcb_embedded_lr as N
import pcb_embedded_lr_4via_trial as V

ROOT=N.ROOT
CONF=ROOT/"design/v3/maxwell/pcb_embedded_lr_3turn_rounded_slots_4via_trial.json"
OUT=N.OUT
PCB=OUT/"ELP38_Lr_3turn_PCB_EMBEDDED_ROUNDED_SLOTS_4VIAS_DFM_NOT_FOR_FAB.kicad_pcb"
REPORT=OUT/"ELP38_Lr_3turn_PCB_EMBEDDED_ROUNDED_SLOTS_4VIAS_DFM_NOT_FOR_FAB.json"
DRC=OUT/"ELP38_Lr_3turn_PCB_EMBEDDED_ROUNDED_SLOTS_4VIAS_DFM_NOT_FOR_FAB.drc.txt"

def source():
    oldtrial,_,oldroutes,oldslots,oldports,_=N.design()
    original_config=N.CONFIG
    try:
        N.CONFIG=CONF
        trial,case,routes,slots,ports,report=N.design()
        board=N._kicad(trial,routes,slots,ports)
    finally:
        N.CONFIG=original_config
    assert trial["case_id"]==oldtrial["case_id"]=="ELP38_Lr_3turn_0920uH"
    r=trial["board"]["slot_tool_corner_radius_mm"]
    assert r>=.5
    assert math.isclose(trial["board"]["core_slot_extra_each_side_mm"]-
                        oldtrial["board"]["core_slot_extra_each_side_mm"],r,abs_tol=1e-9)
    assert len(slots)==len(oldslots)==3
    for old,new in zip(oldslots,slots):
        assert all(abs(a-b)<1e-8 for a,b in zip(new,
                    (old[0]-r,old[1]-r,old[2]+r,old[3]+r)))
        assert new[2]-new[0]>2*r and new[3]-new[1]>2*r
    assert len(ports)==4 and ports==oldports
    return trial,routes,slots,ports,board,oldslots

def rounded_rect(rect,r,slot_id):
    x0,y0,x1,y1=rect
    sqr=math.sqrt(2)
    def P(x,y):
        return f"{N.fmt(x)} {N.fmt(y)}"
    # Fillet convex for interior cutout: 4 straight mill-routed sides
    # and 4 real arcs, no fake sharp right-angle interior corners.
    p=[
       (x0+r,y0),(x1-r,y0),(x1,y0+r),(x1,y1-r),
       (x1-r,y1),(x0+r,y1),(x0,y1-r),(x0,y0+r)]
    mid=[
       (x1-r+r/sqr,y0+r-r/sqr),
       (x1-r+r/sqr,y1-r+r/sqr),
       (x0+r-r/sqr,y1-r+r/sqr),
       (x0+r-r/sqr,y0+r-r/sqr)]
    rows=[]
    for i in range(4):
        a=p[2*i];b=p[(2*i+1)%8]
        c=p[(2*i+2)%8]
        rows.append(f'  (gr_line (start {P(*a)}) (end {P(*b)}) '
                    f'(stroke (width 0.05) (type default)) '
                    f'(layer "Edge.Cuts") '
                    f'(uuid "{N._id(f"rounded_slot_line/{slot_id}/{i}")}"))')
        rows.append(f'  (gr_arc (start {P(*b)}) '
                    f'(mid {P(*mid[i])}) (end {P(*c)}) '
                    f'(stroke (width 0.05) (type default)) '
                    f'(layer "Edge.Cuts") '
                    f'(uuid "{N._id(f"rounded_slot_arc/{slot_id}/{i}")}"))')
    return rows

def generate_board():
    trial,routes,slots,ports,base,oldslots=source()
    q=trial["board"]
    radius=q["slot_tool_corner_radius_mm"]
    # Only remove exact 12 *internal cutout* primitives. Never touch
    # Edge.Cuts board OUTLINE loop 0 or any original copper primitive.
    records=base.splitlines()
    keep=[]
    removed=0
    for line in records:
        if any(f'(uuid "{N._id(f"edge/{slot_id}/{j}")}")' in line
               for slot_id in (1,2,3) for j in range(4)):
            removed+=1
            continue
        keep.append(line)
    if removed!=12:raise ValueError("Cannot locate all 12 original internal sharp slot edges")
    assert keep[-1]==")"
    keep.pop()
    for i,rect in enumerate(slots,1):
        keep.extend(rounded_rect(rect,radius,i))
    # The *original* via exists at each transition. Add three new PTHs
    # per group, connecting the PRECEDING turn's pair via a full-width
    # stub to the already-passing FOLLOWING turn's pair.
    bridge_sites=[]
    all_vias=[(p[0],p[1]) for p in ports[1:3]]
    half=q["transition_via_diameter_mm"]/2
    clear=q["copper_to_copper_clearance_mm"]
    width=q["trace_width_mm"]
    for i in (1,2):
        start=ports[i]
        new=[(round(start[0]-V.PITCH_MM*k,5),start[1])
             for k in range(1,V.ADDITIONAL+1)]
        for via in new:
            if N.point_distance_to_segment(via,routes[i][0],routes[i][1])>1e-8:
                raise ValueError("Via is not on following turn's continuous copper")
            for j,third in enumerate(routes):
                if j in (i-1,i):continue
                if min(N.point_distance_to_segment(via,a,b)
                       for a,b in zip(third,third[1:]))<half+width/2+clear:
                    raise ValueError("New PTH electrically bridges unrelated third turn")
            for xy in all_vias:
                if math.dist(via,xy)<2*half+clear:
                    raise ValueError("New via overlaps any earlier transition PTH")
            for j,port in enumerate(ports):
                if j in (1,2):continue
                if math.dist(via,port)<half+q["terminal_pth_diameter_mm"]/2+clear:
                    raise ValueError("New via touches external Lr terminal")
            all_vias.append(via)
        far=new[-1]
        for a,b in zip(routes[i-1][:-2],routes[i-1][1:-1]):
            if N._same_layer_segment_gap(start,far,a,b)<width+clear:
                raise ValueError("New copper spur shorts the preceding winding loop")
        bridge_sites.append((i,start,far,new))
        for layer in N.GROUPS[i-1]:
            keep.append(
                f'  (segment (start {N.fmt(start[0])} {N.fmt(start[1])}) '
                f'(end {N.fmt(far[0])} {N.fmt(far[1])}) '
                f'(width {N.fmt(width)}) (layer "{layer}") (net 1) '
                f'(uuid "{N._id(f"rounded_four_vias/bridge/{i}/{layer}")}"))')
        for k,point in enumerate(new,1):
            keep.append(
                f'  (via (at {N.fmt(point[0])} {N.fmt(point[1])}) '
                f'(size {N.fmt(q["transition_via_diameter_mm"])}) '
                f'(drill {N.fmt(q["transition_via_drill_mm"])}) '
                f'(layers "F.Cu" "B.Cu") (net 1) '
                f'(uuid "{N._id(f"rounded_four_vias/via/{i}/{k}")}"))')
    # New through-holes from bridge1 must remain clear of newly added
    # spur of bridge2 and vice versa. This is essential because all six
    # layers are through-drilled and share one KiCad net.
    for i,start,far,new in bridge_sites:
        for j,start_other,far_other,new_other in bridge_sites:
            if i==j:continue
            for v in [start,*new]:
                dist=N.point_distance_to_segment(v,start_other,far_other)
                if dist<half+width/2+clear:
                    raise ValueError("BRIDGE-BRIDGE UNINTENDED THROUGH SHORT")
    keep.append(")")
    body="\n".join(keep)+"\n"
    if body.count("(gr_arc (start ")!=12 or body.count("(via (at ")!=8:
        raise ValueError("Expected 12 true fillet arcs and eight through-PTH")
    # The 12 original slots were rectangles. The edited slot bounding box
    # EXPANDED by r and its corner circle center is exactly old corner.
    # This ensures the entire old rectangle (including ferrite leg) fits
    # inside the rounded toolpath without touching outshifted copper.
    for old,new in zip(oldslots,slots):
        assert abs((new[0]+radius)-old[0])<1e-7
        assert abs((new[2]-radius)-old[2])<1e-7
    return trial,body,oldslots,slots,bridge_sites

def contents():
    trial,body,oldslots,newslots,bridges=generate_board()
    report={
        "schema":"D1_ELP38_NATIVE_ROUNDED_SLOT_4VIA_EXPERIMENT_V1",
        "status":"REAL_KICAD_PCB_ROUTE_TOOL_FILLETED_3TURN_NOT_FOR_FAB",
        "source_config_lf_sha256":hashlib.sha256(
            CONF.read_bytes().replace(b"\r\n",b"\n")).hexdigest(),
        "native_kicad_sha256_normalized_lf":hashlib.sha256(body.encode()).hexdigest(),
        "parent_two_via_and_four_via_square_corner_boards_preserved":True,
        "core_slot_routing_corner_radius_mm":trial["board"]["slot_tool_corner_radius_mm"],
        "winding_copper_outshift_and_aperture_expansion_mm":
            trial["board"]["slot_tool_corner_radius_mm"],
        "winding_turns":3,"parallel_copper_layers_per_turn":2,
        "three_actual_rounded_ferrite_cutouts":True,
        "original_unchanged_nominal_inner_leg_rectangle_still_fits":True,
        "slot_bounding_before":[list(x) for x in oldslots],
        "slot_bounding_after":[list(x) for x in newslots],
        "native_new_12_slot_arcs":True,
        "turn_transition_bundles":2,
        "pth_per_bundle":4,
        "new_through_vias":6,
        "new_branch_copper_segments":4,
        "physical_turn_topology_rechecked":True,
        "industry_vendor_nominal_corner_machining_guidance":
            "https://jlcpcb.com/capabilities/pcb-capabilities",
        "slot_mill_tool_radius_vendor_approved":False,
        "slot_vs_actual_TDK_ferrite_feasibility_approved":False,
        "ELP38_Window_core_and_partial_copper_DC_safe":False,
        "Lr_100C_N97_L_I_and_200kHz_AC_loss_qualified":False,
        "via_fault_SOA_and_hot_Rac_qualified":False,
        "total_16mm_coldplate_stack_and_mechanical_approved":False,
        "transformer_4x3to1to1_and_CT_integrated":False,
        "fabrication_approved":False,
    }
    return body,json.dumps(report,ensure_ascii=False,indent=2)+"\n"

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    g=parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--write",action="store_true")
    g.add_argument("--check",action="store_true")
    g.add_argument("--drc",action="store_true")
    a=parser.parse_args()
    if a.drc:
        from main_board_mechanical import find_kicad_cli
        cli=find_kicad_cli()
        if not cli or not PCB.is_file():
            raise SystemExit("Missing actual KiCad CLI or generated rounded native CAD")
        job=subprocess.run([str(cli),"pcb","drc","--all-track-errors","-o",str(DRC),str(PCB)],
                           capture_output=True,text=True,encoding="utf-8",
                           errors="replace",timeout=135)
        print(job.stdout[-1200:],job.stderr[-1000:])
        return job.returncode
    board,report=contents()
    if a.write:
        PCB.write_text(board,encoding="utf-8",newline="\n")
        REPORT.write_text(report,encoding="utf-8",newline="\n")
    if a.check:
        if not PCB.is_file() or PCB.read_text(encoding="utf-8")!=board:
            raise SystemExit("Rounded native KiCad board absent/stale")
        if not REPORT.is_file() or REPORT.read_text(encoding="utf-8")!=report:
            raise SystemExit("Rounded native source evidence absent/stale")
    return 0

if __name__=="__main__":
    raise SystemExit(main())

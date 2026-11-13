"""Conservative V17 signal routing plan using projected frozen source pads.

This never routes the 48V half-bridge hot loop, 100A VOUT/PGND,
transformer/coupled winding, or SR commutating SEC_A/B power nets.
It plans a subset of top-copper control traces and rejects any trace
colliding with unlike-net native pads, previously accepted traces or vias.
Native KiCad DRC remains authoritative; no global EMC signoff.
"""
from __future__ import annotations
import json, math, sys
from collections import defaultdict
from pathlib import Path
from shapely.geometry import LineString,Point,box
from shapely.ops import unary_union
import g2_v16_floorplan_screen as base
import g2_v17_compact_emc_screen as layout
import g2_v17_pgnd_power_route_screen as ground
ROOT=Path(__file__).resolve().parents[1]
OUT=base.G/"g2_v17_signal_legal_route_plan_NOT_FOR_FAB.json"
BLOCK_PREFIXES=("SEC","PRI","CT_")
BLOCK={"PGND","VOUT","VIN_P","SW","CR_CT","CT_LR","GH","GL","GH_DRV","GL_DRV","HB","VCC12","VCC12_S"}
WIDTH=.2
MINCLEAR=.25
MARGIN=.01

def close(a,b):return math.dist(a,b)<.02

def path_collision(points,net,obstacles,paths,via_obstacles):
    poly=LineString(points).buffer(WIDTH/2+MINCLEAR+MARGIN,cap_style="flat",join_style="mitre")
    x0,y0,x1,y1=poly.bounds
    if min(x0,y0)<.85 or x1>154.15 or y1>112.15:
        return True
    for other,geom,layer in obstacles:
        if other==net or layer==2:continue
        if poly.intersects(geom):
            return True
    for other,geom in paths:
        if other!=net and poly.intersects(geom.buffer(WIDTH/2+MINCLEAR,cap_style="flat")):
            return True
    for other,pt,rad in via_obstacles:
        if other!=net and poly.intersects(pt.buffer(rad+.02)):
            return True
    return False

def find_path(a,b,net,obs,existing,vias):
    x1,y1=a;x2,y2=b
    if close(a,b):return None
    candidates=[[a,b]]
    for x,y in [(x1,y2),(x2,y1)]:
        candidates.append([a,(x,y),b])
    for offset in (.7,1.3,2.5,4.,6.,9.):
        for sign in [-1,1]:
            x=min(153.5,max(1.5,(x1+x2)/2+sign*offset))
            y=min(111.5,max(1.5,(y1+y2)/2+sign*offset))
            candidates += [[a,(x,y1),(x,y2),b],[a,(x1,y),(x2,y),b]]
    best=None
    dist=math.dist(a,b)
    for candidate in candidates:
        length=sum(math.dist(u,v) for u,v in zip(candidate,candidate[1:]))
        if length>dist*1.55+4:continue
        if any(path_collision([u,v],net,obs,existing,vias) for u,v in zip(candidate,candidate[1:])):continue
        if best is None or length<best[0]:best=(length,candidate)
    return best[1] if best else None

def plan():
    native,slots=base.load()
    xy=layout.layout(native)
    padrecords=base.transferred_pad_records(native,xy)
    original={}
    for pad in padrecords:
        net=pad["net"]
        if not net or net in BLOCK or any(net.startswith(prefix) for prefix in BLOCK_PREFIXES):continue
        if pad["layer"]!=1:continue
        original.setdefault(net,[]).append(pad)
    obstacles=[(p["net"],p["geom"],p["layer"]) for p in padrecords]
    for s in slots["slots"]:
        void=box(s["x_min_mm"],s["y_min_mm"]+13,
                 s["x_max_mm"],s["y_max_mm"]+13).buffer(.6)
        obstacles.append(("",void,1))
    generated_ground=ground.generate()
    vias=[(p["net"],Point(p["x_mm"],p["y_mm"]),.35) for p in generated_ground["planned_via_in_pad_sites"]+
      generated_ground["additional_local_driver_reg_pgnd_and_Cout_stitches"]+
      generated_ground["control_U1_U2_PGND_via_sites"]+
      generated_ground["auxiliary_12V_S_and_12V_via_sites"]]
    # All relocated physical magnet core voids and NPTH slots are no-go.
    core=[]
    for cx in base.CORE_X:
        core.append((None,Point(cx,33).buffer(.2),1))
    paths=[]
    plans=[]
    failed=[]
    for net,items in sorted(original.items(),key=lambda t:(len(t[1]),t[0])):
        endpoints=list({(round(p["geom"].centroid.x,5),round(p["geom"].centroid.y,5)) for p in items})
        if len(endpoints)<2:continue
        connected={endpoints[0]}
        notconnected=set(endpoints[1:])
        while notconnected:
            proposals=sorted((math.dist(a,b),a,b) for a in connected for b in notconnected)
            chosen=None
            for _,a,b in proposals:
                route=find_path(a,b,net,obstacles,paths,vias)
                if route is not None:
                    chosen=(a,b,route)
                    break
            if chosen is None:
                failed.append({"net":net,"still_ungrouped_pad_centres":len(notconnected),"candidate_count":len(endpoints)})
                break
            a,b,route=chosen
            segs=[[list(u),list(v)] for u,v in zip(route,route[1:]) if not close(u,v)]
            for u,v in segs:
                paths.append((net,LineString([u,v])))
            plans.append({"net":net,"layer":"F.Cu","width_mm":WIDTH,
                          "endpoints":[list(a),list(b)],"segments":segs,
                          "path_length_mm":round(sum(math.dist(u,v) for u,v in zip(route,route[1:])),4)})
            connected.add(b);notconnected.remove(b)
    # Local auxiliary-supply Kelvin branches: plane-fed cap sites have
    # independently screened vias. Avoid dragging 12V across a core/slot.
    supply_pairs=[("U3","C109","VCC12_S"),("U4","C110","VCC12_S"),
      ("U5","C111","VCC12_S"),("U6","C112","VCC12_S"),
      ("U2","C101","VCC12"),("D_BT","C101","VCC12")]
    for r1,r2,net in supply_pairs:
        a=next(x for x in padrecords if x["ref"]==r1 and x["net"]==net)
        b=next(x for x in padrecords if x["ref"]==r2 and x["net"]==net)
        p1,p2=a["geom"].centroid.coords[0],b["geom"].centroid.coords[0]
        route=find_path(p1,p2,net,obstacles,paths,vias)
        if route is None:
            failed.append({"net":net,"reason":"supplementary_local_branch_not_legal","pair":[r1,r2]})
            continue
        segs=[[list(u),list(v)] for u,v in zip(route,route[1:]) if not close(u,v)]
        for u,v in segs:
            paths.append((net,LineString([u,v])))
        plans.append({"net":net,"layer":"F.Cu","width_mm":WIDTH,
                      "endpoints":[list(p1),list(p2)],"segments":segs,
                      "path_length_mm":round(sum(math.dist(u,v) for u,v in zip(route,route[1:])),4)})
    output={
        "status":"CONSERVATIVE_CONTROL_SIGNAL_ONLY_NEEDS_NATIVE_DRC_NOT_FOR_FAB",
        "source_V15_sha":base.sha(base.NATIVE),
        "source_V17_sha":base.sha(layout.OUT),
        "excluded_hot_loop_and_power_nets":sorted(BLOCK),
        "routed_signal_edge_count":len(plans),
        "unresolved_net_groups":failed,
        "segments_count":sum(len(p["segments"]) for p in plans),
        "segments":plans,
        "native_drc_verified":False,"fab_release":False
    }
    OUT.write_text(json.dumps(output,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"routes":len(plans),"segments":output["segments_count"],
       "net_count":len(set(p["net"] for p in plans)), "unresolved":len(failed),
       "length":round(sum(p["path_length_mm"] for p in plans),1),
       "unresolved_sample":failed[:16]},ensure_ascii=False))
if __name__=="__main__":plan()

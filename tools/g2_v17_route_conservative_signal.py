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

def find_path(a,b,net,obs,existing,vias,allow_grid=False):
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
    return best[1] if best else (_grid_fallback(a,b,net,obs,existing,vias) if allow_grid else None)


def _grid_fallback(a,b,net,obstacles,paths,vias):
    """Bounded 45-degree A* fallback after cheap candidate bends fail.

    Clearance is screened against actual V15 projected pad geometry plus
    already committed F.Cu traces/vias. This is *not* an escape from DRC:
    only accepted 2D paths may be written, and all physical layer ownership
    stays unchanged. In particular, this must not make a virtual connection
    through a transformer, another net, or an unverified microvia.
    """
    import heapq
    from shapely.prepared import prep

    dist=math.dist(a,b)
    margin=max(6.,min(13.,.38*dist))
    xmin=max(1.3,min(a[0],b[0])-margin)
    xmax=min(153.7,max(a[0],b[0])+margin)
    ymin=max(1.3,min(a[1],b[1])-margin)
    ymax=min(111.7,max(a[1],b[1])+margin)
    # Exact F.Cu segment test: width/2 + stated clearance + numerical
    # margin. Expanding the fixed blockers once avoids per-edge O(Npad).
    trace_keepout=WIDTH/2+MINCLEAR+MARGIN
    inflated=[]
    for other,geom,layer in obstacles:
        if other!=net and layer!=2 and geom.bounds[0]<xmax+1 and geom.bounds[2]>xmin-1 and geom.bounds[1]<ymax+1 and geom.bounds[3]>ymin-1:
            inflated.append(geom.buffer(trace_keepout))
    for other,line in paths:
        if other!=net and line.bounds[0]<xmax+1 and line.bounds[2]>xmin-1 and line.bounds[1]<ymax+1 and line.bounds[3]>ymin-1:
            inflated.append(line.buffer(WIDTH+2*MINCLEAR+MARGIN))
    for other,pt,rad in vias:
        if other!=net and xmin-1<pt.x<xmax+1 and ymin-1<pt.y<ymax+1:
            inflated.append(pt.buffer(rad+.02+trace_keepout))
    blocked=prep(unary_union(inflated)) if inflated else None

    step=.65
    limit=dist*1.72+4.
    offsets=((1,0),(-1,0),(0,1),(0,-1),
             (1,1),(1,-1),(-1,1),(-1,-1))
    def pos(cell):
        return (a[0]+step*cell[0],a[1]+step*cell[1])
    def legal_edge(u,v):
        if not (xmin<=v[0]<=xmax and ymin<=v[1]<=ymax):
            return False
        if not (.86<=v[0]<=154.14 and .86<=v[1]<=112.14):
            return False
        return blocked is None or not blocked.intersects(LineString((u,v)))
    start=(0,0)
    queue=[(dist,0.,start)]
    cost={start:0.}
    previous={}
    expanded=0
    while queue and expanded<18000:
        _,d,cell=heapq.heappop(queue)
        if d>cost.get(cell,float("inf"))+1e-8:
            continue
        u=pos(cell)
        expanded+=1
        if math.dist(u,b)<=step*1.5 and legal_edge(u,b):
            chain=[b,u]
            while cell!=start:
                cell=previous[cell]
                chain.append(pos(cell))
            chain.reverse()
            # Remove collinear and harmless intermediate grid points.
            # Every shortcut must pass the ORIGINAL collision check, not
            # merely the conservatively inflated fast lookup.
            compact=[chain[0]]
            i=0
            while i<len(chain)-1:
                j=len(chain)-1
                while j>i+1 and path_collision([chain[i],chain[j]],net,obstacles,paths,vias):
                    j-=1
                compact.append(chain[j])
                i=j
            if (sum(math.dist(x,y) for x,y in zip(compact,compact[1:]))<=limit
                and all(not path_collision([x,y],net,obstacles,paths,vias)
                        for x,y in zip(compact,compact[1:]))):
                return compact
            continue
        for di,dj in offsets:
            other=(cell[0]+di,cell[1]+dj)
            v=pos(other)
            h=math.dist(v,b)
            nd=d+step*math.hypot(di,dj)
            if nd+h>limit or nd>=cost.get(other,float("inf"))-1e-8:
                continue
            if not legal_edge(u,v):
                continue
            cost[other]=nd
            previous[other]=cell
            heapq.heappush(queue,(nd+h,nd,other))
    return None

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
      generated_ground["auxiliary_12V_S_and_12V_via_sites"]+
      generated_ground["auxiliary_pgnd_return_via_sites"]]
    # All relocated physical magnet core voids and NPTH slots are no-go.
    core=[]
    for cx in base.CORE_X:
        core.append((None,Point(cx,33).buffer(.2),1))
    paths=[]
    plans=[]
    failed=[]
    pending={}
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
                pending[net]=(connected,notconnected,len(endpoints))
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
    # Second pass only: preserve every originally legal short-bend route before
    # exploring longer grid detours. Grid-first ordering can silently steal a
    # fine-pitch SS/OCD corridor and regress already connected nets.
    for net,(connected,notconnected,count) in sorted(pending.items()):
        while notconnected:
            proposals=sorted((math.dist(a,b),a,b) for a in connected for b in notconnected)
            chosen=None
            for _,a,b in proposals:
                route=find_path(a,b,net,obstacles,paths,vias,allow_grid=True)
                if route is not None:
                    chosen=(a,b,route)
                    break
            if chosen is None:
                failed.append({"net":net,"still_ungrouped_pad_centres":len(notconnected),"candidate_count":count})
                break
            a,b,route=chosen
            segs=[[list(u),list(v)] for u,v in zip(route,route[1:]) if not close(u,v)]
            for u,v in segs:
                paths.append((net,LineString([u,v])))
            plans.append({"net":net,"layer":"F.Cu","width_mm":WIDTH,
                          "endpoints":[list(a),list(b)],"segments":segs,
                          "path_length_mm":round(sum(math.dist(u,v) for u,v in zip(route,route[1:])),4)})
            connected.add(b)
            notconnected.remove(b)
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

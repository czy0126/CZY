"""Audit physical same-net copper islands in frozen OEM EasyEDA PCB.

Unlike DRC's error-item count, this builds a rough electrical union graph
from every native pad, actual track and plated through-via. All evidence is
source-locked to saved EasyEDA readback; pad envelope approximation can only
give a screening graph, not prove a manufacturing netlist/clearance release.

Only a reproducible, original 173/1 native DRC source is admissible.
No topology computation can overrule the official native DRC or be a fab gate.

    python hardware/dcx_main/g2/g2_oem_net_islands.py --write
    python hardware/dcx_main/g2/g2_oem_net_islands.py --check
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import sys
from collections import defaultdict, Counter
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/"tools"))
sys.path.insert(0,str(ROOT/"hardware/dcx_main/g1"))
import g2_board_keepout as K
import route_driver_eco as R
import connect_t530_oem_16x5_bipolar as B

BASE=HERE/(B.PREFIX+"_reopen_readback.json")
BASE_BOARD=B.TARGET
BASE_DELTA=B.DELTA
REPORT=HERE/"g2_oem_native_physical_islands_V2_BASELINE_NOT_FOR_FAB.json"
TOL=.015
ALLOW={"VCC12_S","VCC12","GD1","GD2","OC","OCD","OCM","REG1","REG2","REG3","REG4"}

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def sha_lf(path):
    return hashlib.sha256(path.read_bytes().replace(b"\r\n",b"\n")).hexdigest()

def pad_node(q,i):
    box=K.pad_bbox(q)
    layer=int(q["Layer"])
    return {"net":q["Net"],"type":"pad","layers":(1,2) if layer in (0,11,12) else (layer,),
            "box":box,"xy":((box[0]+box[2])/2,(box[1]+box[3])/2),
            "name":(q.get("ref") or "RAW")+"."+str(q["PadNumber"]),
            "index":i}

def line_node(q,i):
    a=(q["x1"]*.0254,-q["y1"]*.0254)
    b=(q["x2"]*.0254,-q["y2"]*.0254)
    return {"net":q["net"],"type":"line","layers":(int(q["layer"]),),
            "a":a,"b":b,"rad":q["width"]*.0254/2,
            "xy":((a[0]+b[0])/2,(a[1]+b[1])/2),"index":i,
            "name":q["id"]}

def via_node(q,i):
    return {"net":q["net"],"type":"via","layers":(1,2),
            "xy":(q["x"]*.0254,-q["y"]*.0254),
            "rad":q["diameter"]*.0254/2,
            "name":q["id"],"index":i}

def geom_distance(a,b):
    t,u=a["type"],b["type"]
    if t=="pad" and u=="pad":
        x0,y0,x1,y1=a["box"];c0,d0,c1,d1=b["box"]
        return math.hypot(max(x0-c1,c0-x1,0),max(y0-d1,d0-y1,0))
    if t=="pad":
        if u=="via":
            return K.distance_to_box(b["xy"],a["box"])-b["rad"]
        return R._segment_rect(b["a"],b["b"],a["box"])-b["rad"]
    if u=="pad":return geom_distance(b,a)
    if t=="via" and u=="via":
        return math.dist(a["xy"],b["xy"])-a["rad"]-b["rad"]
    if t=="via":
        return K.segment_distance(a["xy"],b["a"],b["b"])-a["rad"]-b["rad"]
    if u=="via":
        return geom_distance(b,a)
    return R._segment_segment(a["a"],a["b"],b["a"],b["b"])-a["rad"]-b["rad"]

def islands(native,restrict=None):
    bynet=defaultdict(list)
    for i,p in enumerate(native["pads"]):
        if p["Net"] and (not restrict or p["Net"] in restrict):
            bynet[p["Net"]].append(pad_node(p,i))
    for i,q in enumerate(native["lines"]):
        if q["net"] and (not restrict or q["net"] in restrict):
            bynet[q["net"]].append(line_node(q,i))
    for i,q in enumerate(native["vias"]):
        if q["net"] and (not restrict or q["net"] in restrict):
            bynet[q["net"]].append(via_node(q,i))
    output={}
    for name,nodes in sorted(bynet.items()):
        n=len(nodes)
        parent=list(range(n))
        def root(i):
            while i!=parent[i]:
                parent[i]=parent[parent[i]]
                i=parent[i]
            return i
        def union(i,j):
            a=root(i);b=root(j)
            if a!=b:parent[max(a,b)]=min(a,b)
        for i,a in enumerate(nodes):
            for j in range(i+1,n):
                b=nodes[j]
                if set(a["layers"]).isdisjoint(b["layers"]):continue
                if geom_distance(a,b)<=TOL:union(i,j)
        groups=defaultdict(list)
        for i,p in enumerate(nodes):groups[root(i)].append(p)
        ordered=sorted(groups.values(),
            key=lambda group:(-len(group),min(p["xy"] for p in group)))
        # The island ID is a property of the physical copper, not a
        # guessed connectivity index or page-specific DRC error number.
        summary=[]
        for group in ordered:
            pads=[x for x in group if x["type"]=="pad"]
            summary.append({
                "pads":[q["name"] for q in sorted(pads,key=lambda r:r["name"])],
                "copper_tracks":sum(q["type"]=="line" for q in group),
                "vias":sum(q["type"]=="via" for q in group),
                "all_objects":len(group),
                "anchor_mm":[round(v,3) for v in min(q["xy"] for q in group)],
                "identity_tag":hashlib.sha256(
                    "|".join(sorted(q["type"]+":"+q["name"] for q in group)).encode()).hexdigest()[:14],
            })
        output[name]={"island_count_geometry_screen":len(summary),
                      "native_pad_count":sum(x["type"]=="pad" for x in nodes),
                      "all_objects":n,"islands":summary}
    return output

def load(path):
    data=json.loads(path.read_text(encoding="utf-8"))
    if data.get("ok") is not True or not isinstance(data.get("value"),dict):
        raise ValueError("Native saved and reopened PCB readback unavailable")
    return data["value"]

def report():
    delta=json.loads(BASE_DELTA.read_text(encoding="utf-8"))
    if sha(BASE_BOARD)!=delta["candidate_sha256"]:
        raise ValueError("Baseline OEM physical PCB differs from verified real native DRC")
    a=load(BASE)
    if tuple(len(a[k]) for k in ("components","pads","lines","vias","nets"))!=(77,443,398,90,65):
        raise ValueError("Native baseline OEM 16x5 altered")
    if delta["actual_native_drc"].get("Connection Error")!=173 or delta["actual_native_drc"].get("Netlist Error")!=1:
        raise ValueError("Accepted baseline DRC mismatch")
    outcome=islands(a,ALLOW)
    pairs=[("VCC12_S","C111.1","C112.1"),("OCM","R17.2","C11.2")]
    checks=[]
    for net,one,two in pairs:
        partition=outcome[net]["islands"]
        one_ids=[i for i,g in enumerate(partition) if one in g["pads"]]
        two_ids=[i for i,g in enumerate(partition) if two in g["pads"]]
        if len(one_ids)!=1 or len(two_ids)!=1 or one_ids==two_ids:
            raise ValueError("Refusing ineffective duplicate-island link: "+str((net,one,two)))
        checks.append({"net":net,"start":one,"end":two,
                       "physically_distinct_source_copper_islands":True,
                       "native_link_routed_and_DRC_improved":False})
    return {
        "schema":"NATIVE_OEM_G2_COPPER_ISLAND_BASELINE_V2_V1",
        "status":"GENUINE_173_OPEN_NATIVE_CAD_GRAPH_SCREEN_NOT_FOR_FAB",
        "source_native_16x5_eprj2_sha256":sha(BASE_BOARD),
        "source_native_readback_canonical_lf_sha256":sha_lf(BASE),
        "native_drc":delta["actual_native_drc"],
        "independent_topological_screen_not_a_DRC_substitute":True,
        "geometry_pad_bbox_may_overconnect_rotated_and_circular_pads":True,
        "physical_island_candidates_not_native_DRC_fixes":checks,
        "true_72_component_instances_and_schematic_parity":False,
        "100A_or_fabrication_approved":False,
        "per_control_net":outcome,
        "next":"Use actual distinct copper islands for any new physical native routes, require GUI save/re-open and true decreasing native DRC",
    }

def main():
    ap=argparse.ArgumentParser()
    p=ap.add_mutually_exclusive_group(required=True)
    p.add_argument("--write",action="store_true")
    p.add_argument("--check",action="store_true")
    o=ap.parse_args()
    body=json.dumps(report(),ensure_ascii=False,indent=2)+"\n"
    if o.write:REPORT.write_text(body,encoding="utf-8",newline="\n")
    if o.check and (not REPORT.is_file() or REPORT.read_text(encoding="utf-8")!=body):
        raise SystemExit("OEM copper graph stale or native readback missing")
    print(body[:4500])
    return 0

if __name__=="__main__":
    raise SystemExit(main())

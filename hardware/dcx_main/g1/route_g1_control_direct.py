"""Deterministic low-current copper on the REAL saved 132-line, 183-open G1.

One native EasyEDA Pro execution; no beta autoRouting dependency. The six
selected disconnected pad pairs are independently clear of ALL actual 299
pads, 132 existing tracks, 18 vias and 5 frozen magnetic body envelopes.
No 100A rails, magnetics, Kelvin, SR gate or high-side drivers are touched.
This module is a Native-EDA input, not evidence that copper has been written.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/"tools"))
import route_driver_eco as R
import audit_driver_eco as AUDIT
import g1_magnetics_envelope as GEOM
import route_open_connections as OLD

SOURCE=HERE/"dcx_main_board_g1_open_batch.eprj2"
READBACK=HERE/"g1_open_batch_reopen_readback.json"
BASE_DRC=HERE/"g1_open_batch_drc_raw.json"
EVIDENCE=HERE/"g1_open_batch_drc_delta.json"
EXPECTED_SHA="59ec7ab3f8dd17ba76b465e9686bce58647db66b76770a4762c0b7e33e33afb0"
CANDIDATE="dcx_main_board_g1_control_direct.eprj2"
READBACK_OUT=HERE/"g1_control_direct_reopen_readback.json"
REPORT_OUT=HERE/"g1_control_direct_reopen_report.json"
WIDTH=.20
CLEARANCE=R.CLEARANCE

# Use actual copper pad identities, not old fixed coordinates; waypoints are
# local mm offsets referenced to those pads. No previously connected pairs.
# The 132-line DRC shows residual RUN, SS, OC, OCD, OCM disconnects.
# Fewer physical segments/risks than the full beta 5-net autoRouter.
PAIRS=(
  ("RUN","C13","1","R7","1","direct"),
  ("SS","C6","1","U1","4","horizontal_above_C6"),
  ("OC","R16","2","U1","3","horizontal_below_R16"),
  ("OCD","R3","1","D_CT1","3","OCD_lower_corridor"),
  ("OCM","C11","2","C12","2","above_caps"),
  ("OCM","D_CT4","1","R17","2","below_DCT4"),
)
PERMITTED={"RUN","SS","OC","OCD","OCM"}
FORBIDDEN=("PGND","VOUT","VIN_P","SW","CT_LR","CR_CT")
MAX_PATH_LENGTH_MM=65

def sha(path:Path)->str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def source()->dict:
    if not SOURCE.is_file() or sha(SOURCE)!=EXPECTED_SHA:
        raise ValueError("Native active 132-line G1 CAD bytes changed")
    evidence=json.loads(EVIDENCE.read_text(encoding="utf-8"))
    if (evidence.get("candidate_sha256")!=EXPECTED_SHA
            or evidence.get("status")!="ACTUAL_EASYEDA_COPPER_IMPROVED_NOT_FOR_FAB"
            or evidence.get("native_reopen_drc",{}).get("Connection Error")!=183
            or evidence.get("native_reopen_drc",{}).get("Netlist Error")!=1
            or evidence.get("full_board_fabrication_approved") is not False):
        raise ValueError("Source is not the actual accepted 132-line native G1")
    raw=json.loads(READBACK.read_text(encoding="utf-8"))
    if raw.get("ok") is not True or not isinstance(raw.get("value"),dict):
        raise ValueError("Actual saved/reopened native G1 PCB unavailable")
    p=raw["value"]
    if tuple(len(p[k]) for k in ("components","pads","nets","lines","vias"))!=(77,299,65,132,18):
        raise ValueError("Latest G1 native readback counts changed")
    drc=json.loads(BASE_DRC.read_text(encoding="utf-8"))
    counts=OLD.categories(drc)
    if (counts.get("Connection Error"),counts.get("Netlist Error"),
        counts.get("Physical Error",0))!=(183,1,0):
        raise ValueError("Current actual native DRC is not 183/1/0")
    return p

def at(p:dict,ref:str,pin:str,net:str)->tuple[float,float]:
    q=[x for x in p["pads"] if x.get("ref")==ref and str(x.get("PadNumber"))==pin]
    if len(q)!=1 or q[0].get("Net")!=net or q[0].get("Layer")!=1:
        raise ValueError(f"Real native pad {ref}.{pin} / {net} changed")
    return q[0]["X"]/R.MIL,-q[0]["Y"]/R.MIL

def path(a,b,kind):
    x,y=a;u,v=b
    if kind=="direct":return[a,b]
    if kind=="horizontal_above_C6":return[a,(x,y+1.0),(u,y+1.0),b]
    if kind=="horizontal_below_R16":return[a,(x,y+1.0),(u,y+1.0),b]
    if kind=="OCD_lower_corridor":return[a,(x,y+3.6),(u,y+3.6),b]
    if kind=="above_caps":return[a,(x,y-1.0),(u,y-1.0),b]
    if kind=="below_DCT4":return[a,(x,y+1.0),(u,y+1.0),b]
    raise ValueError("Unknown reviewed trace shape: "+str(kind))

def copper()->dict:
    p=source()
    out={}
    if len(PAIRS)!=6 or {x[0] for x in PAIRS}!=PERMITTED:
        raise ValueError("Native direct-route design scope changed")
    for net,ref,pin,ref2,pin2,shape in PAIRS:
        if net not in PERMITTED or net in FORBIDDEN:
            raise ValueError("Unapproved high-current or gate routing")
        a=at(p,ref,pin,net);b=at(p,ref2,pin2,net)
        route=path(a,b,shape)
        if not .5<math.dist(a,b)<MAX_PATH_LENGTH_MM:
            raise ValueError("Real pad displacement outside reviewed signal range")
        if any(math.dist(a,b)<.02 for a,b in zip(route,route[1:])):
            raise ValueError("Degenerate zero-length copper segment")
        out.setdefault(net,{"width":WIDTH,"layer":1,"paths":[]})["paths"].append(route)
    if len(R.segments(out))!=16:
        raise ValueError("Expected 16 controlled native line primitives")
    return out

def vias()->list:
    return []

def issues()->list:
    plan=copper()
    actual=source()
    segs=R.segments(plan)
    pads=R.load_pads(READBACK)
    bad=R.check_plan(pads,plan,clearance=CLEARANCE)
    # The native editor may retain old copper not represented by new path
    # geometries. Scan the real 132 lines and all 18 vias as physical obstacles.
    for s in segs:
        for t in R.lines_from_readback(READBACK):
            if s["net"]==t["net"] or s["layer"]!=t["layer"]:continue
            gap=R._segment_segment(s["a"],s["b"],t["a"],t["b"])-(s["width"]+t["width"])/2
            if gap < CLEARANCE-1e-9:
                bad.append({"kind":"existing-copper","new":s["net"],"old":t["net"],
                            "gap":round(gap,4)})
        for v in R.vias_from_readback(READBACK):
            if s["net"]==v["net"]:continue
            gap=R._point_segment(v["x"],v["y"],s["a"],s["b"])-(s["width"]+v["diameter"])/2
            if gap < CLEARANCE-1e-9:
                bad.append({"kind":"existing-via","net":s["net"],"other":v["net"],
                            "gap":round(gap,4)})
    # Conservatively retain all five preexisting magnetic bodies; no routing
    # through provisional 24 magnetic terminal envelopes.
    base=GEOM.load_current()
    bodies=json.loads(GEOM.MAG.read_text(encoding="utf-8"))
    lr,transformers,_=GEOM.core_rects(base,bodies)
    for s in segs:
        for name,rect in [("Lr",lr),*transformers.items()]:
            box=(rect["left"],rect["top"],rect["right"],rect["bottom"])
            gap=R._segment_rect(s["a"],s["b"],box)-s["width"]/2
            if gap<.5-1e-9:
                bad.append({"kind":"magnetic-body","net":s["net"],"name":name,
                            "gap":round(gap,4)})
    return bad

def report()->dict:
    plan=copper()
    segs=R.segments(plan)
    return {
      "status":"ACTUAL_132LINE_183OPEN_G1_NATIVE_DIRECT_6_PAIRS_PREFLIGHT_NOT_APPLIED",
      "parent":SOURCE.relative_to(ROOT).as_posix(),
      "parent_sha256":sha(SOURCE),
      "native_before_drc":OLD.categories(json.loads(BASE_DRC.read_text(encoding="utf-8"))),
      "candidate":CANDIDATE,
      "nets":sorted(plan),
      "pairs":[{"net":n,"from":f"{r}.{pin}","to":f"{s}.{p}","mode":shape}
               for n,r,pin,s,p,shape in PAIRS],
      "real_pad_pairs":6,"native_line_primitives":len(segs),
      "length_mm":round(sum(math.dist(z["a"],z["b"]) for z in segs),3),
      "new_vias":0,"track_width_mm":WIDTH,"clearance_mm":CLEARANCE,
      "preflight_problems":issues(),
      "native_eda_applied":False,
      "native_drc_improved":False,
      "fabrication_approved":False,
    }

def verify()->dict:
    prior=source()
    raw=json.loads(READBACK_OUT.read_text(encoding="utf-8"))
    if raw.get("ok") is not True or not isinstance(raw.get("value"),dict):
        raise ValueError("No successful native reopen for direct-route candidate")
    new=raw["value"]
    drift=[]
    before={x["ref"]:(x["X"],x["Y"],x["Rotation"]) for x in prior["components"]}
    after={x["ref"]:(x["X"],x["Y"],x["Rotation"]) for x in new["components"]}
    if len(before)!=77 or len(after)!=77 or before!=after:
        drift.append("Component positions/identities changed")
    if sorted(prior["nets"])!=sorted(new["nets"]):
        drift.append("Netlist changed")
    if not AUDIT.pads_match(prior["pads"],{k:v[:2] for k,v in before.items()},
                            new["pads"],{k:v[:2] for k,v in after.items()}):
        drift.append("Actual pad net/identity/geometry changed")
    prior_vias={z["id"]:z for z in prior["vias"]}
    new_vias={z["id"]:z for z in new["vias"]}
    if prior_vias!=new_vias or len(prior_vias)!=18 or len(new_vias)!=18:
        drift.append("Original through vias modified")
    old={z["id"]:z for z in prior["lines"]}
    cur={z["id"]:z for z in new["lines"]}
    for key,z in old.items():
        if key not in cur:
            drift.append("Original copper line missing: "+key)
            continue
        if any(z[k]!=cur[key].get(k) for k in ("net","layer","x1","y1","x2","y2","width")):
            drift.append("Original copper geometry modified: "+key)
    added=[z for key,z in cur.items() if key not in old]
    if not added or any(z.get("net") not in PERMITTED or z.get("layer")!=1 for z in added):
        drift.append("Unauthorized added copper or no real copper created")
    actual_lines=R.lines_from_readback(READBACK_OUT)
    coverage=[]
    for z in R.segments(copper()):
        ok,reasons=R._covered(z,actual_lines,allow_wider=True)
        if not ok:coverage.append({"net":z["net"],"from":z["a"],"to":z["b"],
                                   "reasons":reasons})
    return {
      "status":"REAL_G1_NATIVE_COPPER_DIRECT_REOPEN_NOT_FOR_FAB",
      "layout_counts":{"unchanged":not drift},
      "lines":{"original_count":len(old),"actual_count":len(cur),
               "added_nets":sorted({x["net"] for x in added}),
               "coverage_problems":coverage},
      "vias":{"problems":[] if prior_vias==new_vias else ["via drift"]},
      "placement_drift":drift,
      "native_drc_passed":False,"fabrication_approved":False,
    }

def main()->int:
    import argparse
    ap=argparse.ArgumentParser(description=__doc__)
    modes=ap.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check",action="store_true")
    modes.add_argument("--emit-js",action="store_true")
    a=ap.parse_args()
    check=report()
    if check["preflight_problems"]:
        print(json.dumps(check,ensure_ascii=False,indent=2))
        return 1
    if a.emit_js:
        print(R.emit_js(copper(),[]))
    else:
        print(json.dumps(check,ensure_ascii=False,indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())

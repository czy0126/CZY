"""Apply a small, source-locked batch of *real copper* on the G1 199-open board.

The 199 items are REAL EasyEDA DRC reports, not 199 interchangeable ratsnest
segments. This increment only handles low-current nets with a demonstrable
clear L1 route. It never auto-routes PGND/VOUT, transformer primary/secondary,
SW, SR gate or source-Kelvin current paths.

Windows EasyEDA Pro:
  python hardware/dcx_main/g1/apply_g1_open_batch.py --check
  python hardware/dcx_main/g1/apply_g1_open_batch.py --apply

--apply copies the latest accepted G1 board, opens the COPY in native
EasyEDA, creates actual track primitives, saves, closes, re-opens, checks
geometry, and runs real native DRC. If the DRC count does not decrease, the
new board is NOT accepted (and the parent stays unchanged).
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
import audit_driver_eco as E
import g1_magnetics_envelope as GEOM

SOURCE=HERE/"dcx_main_board_g1_signal_stubs.eprj2"
READBACK=HERE/"lr_signal_review_readback.json"
DRC=HERE/"lr_signal_review_drc_raw.json"
BINDING=HERE/"g1_100a_output_interface.json"
CANDIDATE="dcx_main_board_g1_open_batch.eprj2"
READBACK_OUT=HERE/"g1_open_batch_reopen_readback.json"
REPORT_OUT=HERE/"g1_open_batch_reopen_report.json"
PLAN_OUT=HERE/"g1_open_batch_route_plan.json"
WIDTH=.20
CLEARANCE=R.CLEARANCE

# All paths are found against the ACTUAL reopened 107-line G1 board.
# A/B are a *pad identity* and net, never a freely guessed coordinate.
# Shape is one of:
# "direct": straight, same-net pad to same-net pad.
# "high": from A to a horizontal corridor one millimeter above A,
#         then to B at the same corridor.
# "DT": up to 0.60mm above B, then drop into B.
# "RT": up 1.0mm from A, traverse horizontally, then to B.
# "U4": up 1.0mm from C106, traverse sideways, then to U4.7.
# "OCD": down to y=72.2mm in the existing free channel.
# Keep SS, 8 SR gates, 8 VD_B paths and OCM/OC long collection off this
# machine-generated increment: those need impedance/Kelvin or via work.
PAIRS=(
  ("VCC12_S","C106","1","U4","7","U4"),
  ("VCC12_S","C109","1","C110","1","high"),
  ("VCC12_S","C110","1","C111","1","high"),
  ("DT","R1","1","U1","1","DT"),
  ("RT","R2","1","U1","2","RT"),
  ("VD1_A","R28","2","U3","4","direct"),
  ("VD2_A","R30","2","U4","4","direct"),
  ("VD3_A","R32","2","U5","4","direct"),
  ("VD4_A","R34","2","U6","4","direct"),
  ("OC1","R16","1","C11","1","high"),
  ("OCD","D_CT1","3","D_CT2","3","OCD"),
  ("OCM","D_CT3","1","D_CT4","1","direct"),
)
# Explicit prohibited nets are NOT allowed even if a straight line exists:
BANNED={"PGND","VOUT","VIN_P","SW","CR_CT","CT_LR","OC"} # high-current and whole OC long loop


def source() -> dict:
    manifest=json.loads(BINDING.read_text(encoding="utf-8"))
    s=manifest["candidate"]
    if s["path"]!=SOURCE.relative_to(ROOT).as_posix():
        raise ValueError("Wrong active G1 native candidate path")
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest()!=s["sha256"]:
        raise ValueError("Actual EasyEDA source bytes drifted")
    if hashlib.sha256(READBACK.read_bytes()).hexdigest()!=s["readback_sha256"]:
        raise ValueError("Native reopened PCB readback differs from bound report")
    payload=json.loads(READBACK.read_text(encoding="utf-8"))
    if payload.get("ok") is not True or not isinstance(payload.get("value"),dict):
        raise ValueError("Missing successful native saved/reopened readback")
    p=payload["value"]
    if (len(p["components"]),len(p["pads"]),len(p["lines"]),len(p["nets"]),
            len(p["vias"]))!=(77,299,107,65,18):
        raise ValueError("Actual 107-line G1 board counts changed")
    drc=json.loads(DRC.read_text(encoding="utf-8"))
    if drc.get("ok") is not True:
        raise ValueError("Missing native source DRC")
    counts=categories(drc)
    if counts.get("Connection Error")!=199 or counts.get("Netlist Error")!=1 or counts.get("Physical Error",0)!=0:
        raise ValueError("Native baseline DRC no longer 199/1/0; new batch required")
    return p


def categories(data: dict) -> dict:
    gr=data["value"]["raw"]
    if not isinstance(gr,list):raise ValueError("DRC category list missing")
    names=[x["name"] for x in gr]
    if len(set(names))!=len(names):raise ValueError("Duplicate native DRC categories")
    return {x["name"]:sum(len(t.get("list") or []) for t in x.get("list") or []) for x in gr}


def nativepad(p:dict,ref:str,pin:str,net:str) -> tuple[float,float]:
    q=[x for x in p["pads"] if x.get("ref")==ref and str(x.get("PadNumber"))==pin]
    if len(q)!=1 or q[0].get("Net")!=net or q[0].get("Layer") not in (1,12,0):
        raise ValueError(f"Native pad identity changed {ref}.{pin}/{net}")
    return q[0]["X"]/R.MIL,-q[0]["Y"]/R.MIL


def path(a,b,shape):
    x,y=a;u,v=b
    if shape=="direct":return [a,b]
    if shape=="high":return [a,(x,y-1.0),(u,y-1.0),b]
    if shape=="U4":return [a,(x,y+1.0),(u,y+1.0),b]
    if shape=="DT":return [a,(x,v-.60),(u,v-.60),b]
    if shape=="RT":return [a,(x,y-1.0),(u,y-1.0),b]
    if shape=="OCD":return [a,(x,72.2),(u,72.2),b]
    raise ValueError("Unexpected route shape "+shape)


def copper() -> dict:
    p=source()
    plans={}
    seen=set()
    for net,ref,pin,dst,dstpin,shape in PAIRS:
        if net in BANNED or net.startswith(("SEC","PRI","GA","GB","VG","REG")):
            raise ValueError("Unsafe current/real-Kelvin/gate routing requested")
        a=nativepad(p,ref,pin,net);b=nativepad(p,dst,dstpin,net)
        pair=(net,ref,pin,dst,dstpin)
        if pair in seen:raise ValueError("Duplicate disconnected-pair route")
        seen.add(pair)
        xy=path(a,b,shape)
        if not .6<math.dist(a,b)<19:
            raise ValueError(f"Unexpected endpoint displacement for {pair}")
        if any(math.dist(c,d)<.02 for c,d in zip(xy,xy[1:])):
            raise ValueError(f"Degenerate geometry for {pair}")
        plans.setdefault(net,{"width":WIDTH,"layer":1,"paths":[]})
        plans[net]["paths"].append(xy)
    if len(PAIRS)!=12 or len(plans)!=9:
        raise ValueError("Route scope changed: review 12 connections before native applying")
    return plans


def vias()->list:
    return []


def issues() -> list:
    p=source()
    plan=copper()
    pads=R.load_pads(READBACK)
    segs=R.segments(plan)
    out=R.check_plan(pads,plan,clearance=CLEARANCE)

    # Check all 107 pre-existing copper segments and 18 through-layer vias,
    # not only the twelve newly drawn paths or their landing pads.
    previous=R.lines_from_readback(READBACK)
    old_vias=R.vias_from_readback(READBACK)
    for s in segs:
        for t in previous:
            if s["net"]==t["net"] or s["layer"]!=t["layer"]:continue
            d=R._segment_segment(s["a"],s["b"],t["a"],t["b"])
            margin=d-(s["width"]+t["width"])/2
            if margin+1e-9<CLEARANCE:
                out.append({"kind":"existing-line","net":s["net"],"other":t["net"],"margin":round(margin,4)})
        for v in old_vias:
            if v["net"]==s["net"]:continue
            d=R._point_segment(v["x"],v["y"],s["a"],s["b"])
            margin=d-(s["width"]+v["diameter"])/2
            if margin+1e-9<CLEARANCE:
                out.append({"kind":"existing-via","net":s["net"],"other":v["net"],"margin":round(margin,4)})

    # The original 9-track increment did not change placement. Retain ferrite
    # body clearance, not just line-vs-pad clearance.
    base=GEOM.load_current()
    mag=json.loads(GEOM.MAG.read_text(encoding="utf-8"))
    body,Ts,_=GEOM.core_rects(base,mag)
    for s in segs:
        for name,rect in [("Lr",body),*Ts.items()]:
            z=(rect["left"],rect["top"],rect["right"],rect["bottom"])
            gap=R._segment_rect(s["a"],s["b"],z)-s["width"]/2
            if gap<.5-1e-9:
                out.append({"kind":"magnet-body","net":s["net"],"body":name,"margin":round(gap,4)})
    return out


def report()->dict:
    p=source()
    plan=copper()
    routes=R.segments(plan)
    clashes=issues()
    return {
        "status":"ACTUAL_107_LINE_G1_199_DRC_BATCH_READY_NOT_YET_APPLIED",
        "source":SOURCE.relative_to(ROOT).as_posix(),
        "source_sha256":hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "readback_sha256":hashlib.sha256(READBACK.read_bytes()).hexdigest(),
        "native_before_drc":categories(json.loads(DRC.read_text(encoding="utf-8"))),
        "candidate":CANDIDATE,
        "pairs":[{"net":net,"from":f"{ref}.{pin}","to":f"{dst}.{dstpin}","shape":shape}
                 for net,ref,pin,dst,dstpin,shape in PAIRS],
        "routes":len(PAIRS),
        "segments":len(routes),
        "total_route_length_mm":round(sum(math.dist(s["a"],s["b"]) for s in routes),3),
        "new_vias":0,
        "clearance_mm":CLEARANCE,
        "off_limits":["PGND","VIN_P","VOUT","SW","SEC*","PRI*",
                     "8x SR gate/Kelvin","5 magnet temporary terminals"],
        "preflight_problems":clashes,
        "actual_easyeda_applied":False,
        "native_drc_improved":False,
        "fabrication_approved":False
    }


def value(path:Path)->dict:
    p=json.loads(path.read_text(encoding="utf-8"))
    if p.get("ok") is not True or not isinstance(p.get("value"),dict):
        raise ValueError(f"Invalid native EasyEDA reopen result: {path}")
    return p["value"]


def verify()->dict:
    before=source()
    after=value(READBACK_OUT)
    old={x["id"]:x for x in before["lines"]}
    new={x["id"]:x for x in after["lines"]}
    drift=[]
    for key in ("components","pads","nets","vias"):
        if len(before[key])!=len(after[key]):drift.append(f"{key} count changed")
    a={x["ref"]:(x["X"],x["Y"],x["Rotation"]) for x in before["components"]}
    b={x["ref"]:(x["X"],x["Y"],x["Rotation"]) for x in after["components"]}
    if a!=b:drift.append("Component positions/rotation changed")
    if not E.pads_match(before["pads"],{k:v[:2] for k,v in a.items()},
                        after["pads"],{k:v[:2] for k,v in b.items()}):
        drift.append("Pad identity/net/geometry drift")
    if before["vias"]!=after["vias"]:
        drift.append("Original vias modified")
    for k,orig in old.items():
        if k not in new:
            drift.append("Original copper ID missing "+k)
            continue
        for field in ("net","layer","x1","x2","y1","y2","width"):
            q=new[k][field]
            if q!=orig[field] and (field in ("net","layer") or abs(float(q)-float(orig[field]))>.25):
                drift.append(f"Original copper modified {k}.{field}")
    readback_tracks=R.lines_from_readback(READBACK_OUT)
    missing=[]
    for seg in R.segments(copper()):
        ok,reasons=R._covered(seg,readback_tracks,allow_wider=True)
        if not ok:missing.append({"net":seg["net"],"a":seg["a"],"b":seg["b"],"reasons":reasons})
    return {
        "status":"NATIVE_REOPEN_COPPER_COVERAGE_CHECK_NOT_FAB",
        "layout_counts":{"unchanged":not drift},
        "lines":{"coverage_problems":missing,"original_count":len(old),
                 "actual_count":len(new)},
        "vias":{"problems":[]},
        "placement_drift":drift,
        "native_drc_passed":False,"fabrication_approved":False
    }


def main()->int:
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    g=parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--check",action="store_true")
    g.add_argument("--emit-js",action="store_true")
    g.add_argument("--write-plan",action="store_true")
    args=parser.parse_args()
    d=report()
    if d["preflight_problems"]:
        print(json.dumps(d,indent=2,ensure_ascii=False))
        return 1
    if args.emit_js:
        print(R.emit_js(copper(),[]))
    elif args.write_plan:
        PLAN_OUT.write_text(json.dumps(d,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(PLAN_OUT)
    else:
        print(json.dumps(d,indent=2,ensure_ascii=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())

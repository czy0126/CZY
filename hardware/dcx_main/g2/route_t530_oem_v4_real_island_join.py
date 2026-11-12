"""Route two proven distinct native-copper islands on REAL 16x5 OEM G2.

Real EasyEDA Pro native PCB, isolated copy, save + reopen + DRC.
KNOWN APP LIMIT: a prior first-batch CLI invocation timed out and was NOT
accepted, despite passing geometric preflight. Never retry against that copy.
No 100A,
SR Kelvin/sense, transformer pins, EMI/output terminals, power or fault
commutation nets routed. Explicitly select only two genuinely disconnected
independent low-energy control connections and test geometry against 443 pads, 398
existing copper lines and 90 vias. Existing G2 OEM source is immutable.

--check  preflight without writing any project
--apply  create one uniquely named native copy and apply at most once
--resume reopen read-only and verify physical copper/DRC; never reapply

PCB is NOT_FOR_FAB, even if this batch clears some connection errors.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import shutil
import sys
import time
from collections import Counter
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/"tools"))
sys.path.insert(0,str(ROOT/"hardware/dcx_main/g1"))
import connect_t530_oem_16x5_bipolar as C
import apply_t530_density_b_v2_native as A
import route_driver_eco as R
import g1_magnetics_envelope as MAG
import g2_oem_net_islands as ISLAND

SOURCE=C.TARGET
TARGET=HERE/"dcx_main_board_g2_T530_OEM_DENSITY_B_V4_DISTINCT_ISLAND_JOINS_NOT_FOR_FAB.eprj2"
PREFIX="g2_t530_oem_v4_island_join"
PLAN=HERE/(PREFIX+"_route_plan.json")
DELTA=HERE/(PREFIX+"_drc_delta.json")
RAW=HERE/(PREFIX+"_drc_raw.json")
REOPEN=HERE/(PREFIX+"_reopen_readback.json")
STUB_WIDTH=.15
CLEAR=.30
# Two independent native copper islands: one driver supply
# orphan and one OC monitor orphan. Never select same-island paths.
# Each route is by named native pad, not guessed freehand coords.
PAIRS=(
    ("VCC12_S","C111","1","C112","1",42.0),
    ("OCM","R17","2","C11","2",63.4),
)
SAFE={"VCC12_S","OCM"}
BANNED={"PGND","VOUT","VIN_P","SW","CT_LR","CR_CT"}

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def dump(tag,obj):
    (HERE/(PREFIX+"_"+tag+".json")).write_text(
        json.dumps(obj,ensure_ascii=False,indent=2)+"\n",
        encoding="utf-8",newline="\n")

def raw_source():
    s=json.loads(C.DELTA.read_text(encoding="utf-8"))
    if not SOURCE.is_file() or sha(SOURCE)!=s["candidate_sha256"]:
        raise ValueError("OEM G2 source doesn't match actual accepted 173-error native board")
    if s["actual_native_drc"].get("Connection Error")!=173:
        raise ValueError("expected original native 173 DRC baseline")
    rd=json.loads((HERE/(C.PREFIX+"_reopen_readback.json")).read_text(encoding="utf-8"))
    if not rd.get("ok"):raise ValueError("OEM native source does not have a successful reopen")
    v=rd["value"]
    if tuple(len(v[k]) for k in ("components","pads","lines","vias","nets"))!=(77,443,398,90,65):
        raise ValueError("Actual native G2 source counts changed unexpectedly")
    drc=json.loads((HERE/(C.PREFIX+"_drc_raw.json")).read_text(encoding="utf-8"))
    cat=A.R.categories(drc)
    if cat.get("Connection Error")!=173 or cat.get("Netlist Error")!=1 or cat.get("Physical Error",0):
        raise ValueError("Native source DRC different from frozen actual readback")
    return v,s

def pad(rows,net,ref,pin):
    a=[q for q in rows if q.get("Net")==net and q.get("ref")==ref and str(q.get("PadNumber"))==pin and int(q.get("Layer"))==1]
    if len(a)!=1:raise ValueError("missing/duplicate native pad: "+str((net,ref,pin)))
    return (a[0]["X"]*.0254,-a[0]["Y"]*.0254)

def track(net,a,b):
    if math.dist(a,b)<.02:raise ValueError("zero length route")
    return C._track(net,1,a,b,STUB_WIDTH)

def plan():
    data,source_report=raw_source()
    routes=[];details=[];problems=[]
    if len(PAIRS)!=2 or any(net not in SAFE or net in BANNED for net,*rest in PAIRS):
        raise ValueError("Unsafe changes in reviewed control-net batch")
    core= MAG.load_current()
    magnet=json.loads(MAG.MAG.read_text(encoding="utf-8"))
    body,tf,_=MAG.core_rects(core,magnet)
    ferrites=[("Lr",body),*tf.items()]
    for idx,(net,aref,apin,bref,bpin,corridor) in enumerate(PAIRS):
        native_islands=ISLAND.islands(data,{net})[net]["islands"]
        src_pad=aref+"."+apin
        dst_pad=bref+"."+bpin
        src_group=[i for i,island in enumerate(native_islands) if src_pad in island["pads"]]
        dst_group=[i for i,island in enumerate(native_islands) if dst_pad in island["pads"]]
        if len(src_group)!=1 or len(dst_group)!=1 or src_group==dst_group:
            raise ValueError("Plan would connect the SAME physical copper island: "+str((net,src_pad,dst_pad)))
        a=pad(data["pads"],net,aref,apin)
        b=pad(data["pads"],net,bref,bpin)
        if not (.5<=math.dist(a,b)<9.):
            raise ValueError("Unexpected real native endpoint distance for "+net)
        points=([a,b] if corridor is None else
                [a,(a[0],corridor),(b[0],corridor),b])
        wires=[]
        for start,end in zip(points,points[1:]):
            q=track(net,start,end)
            hits=C._conflicts_line(q,data)
            problems.extend(f"line{idx}/unlike_{v}" for v in hits)
            # Magnetics-body exclusion, separate from EDA electrical DRC.
            for name,rect in ferrites:
                box=tuple(rect[v] for v in ("left","top","right","bottom"))
                gap=R._segment_rect(start,end,box)-STUB_WIDTH/2
                if gap<.5:
                    problems.append(f"line{idx}/ferrite {name} gap={gap:.3f}")
            wires.append(q)
        details.append({"net":net,"start":f"{aref}.{apin}","end":f"{bref}.{bpin}",
                        "path_mm":[list(x) for x in points],"track_count":len(wires),
                        "verified_distinct_native_copper_islands":True})
        routes.extend(wires)
    # Check *new* unrelated nets against each other, even though they are
    # placed in separate batches and the old-board scan cannot see them.
    for i,one in enumerate(routes):
        for j,two in enumerate(routes[i+1:],i+1):
            if one["net"]==two["net"]:continue
            gap=R._segment_segment(tuple(one["a_mm"]),tuple(one["b_mm"]),
                                   tuple(two["a_mm"]),tuple(two["b_mm"]))
            gap-=(one["width_mm"]+two["width_mm"])/2
            if gap+1e-9<CLEAR:
                problems.append(f"new_crossnet_contact/{i}/{j}/gap={gap:.3f}")
    if len(routes)!=6:
        raise ValueError("Expected 6 selected conductor segments, no hidden scope expansion")
    return {"schema":"D1_G2_REAL_NATIVE_V4_DISTINCT_ISLAND_JOINS_2_LINKS",
            "source_eprj2_sha256":sha(SOURCE),
            "source_native_readback_canonical_lf_sha256":ISLAND.sha_lf(HERE/(C.PREFIX+"_reopen_readback.json")),
            "original_native_drc":source_report["actual_native_drc"],
            "paths":details,"tracks":routes,"preflight_problems":sorted(set(problems)),
            "high_current_nets_untouched":True,"gate_kelvin_and_mag_terminal_nets_untouched":True,
            "true_oem_72_schematic_components_present":False,
            "100A_power_copper_qualified":False,"manufacturing_approved":False}

def open_board(stage):
    obj=A.D.call(A.D.build_open_args(TARGET),timeout_s=110)
    dump(stage+"_open",obj)
    sid=(obj.get("value") or {}).get("sessionId")
    if not sid:return None
    time.sleep(A.D.SETTLE_S)
    ping=A.D.call(A.D.build_ping_args(sid),timeout_s=32)
    dump(stage+"_ping",ping)
    if not ping.get("ok"):
        dump(stage+"_close",A.D.call(A.D.build_close_args(sid)))
        return None
    return sid

def verify(actual,order):
    before,_=raw_source()
    if tuple(len(actual[k]) for k in ("components","pads","nets"))!=(77,443,65):
        raise ValueError("Native old component/pad/net count changed")
    for key in ("components","pads","nets"):
        if Counter(json.dumps(q,sort_keys=True) for q in before[key])!=Counter(
                   json.dumps(q,sort_keys=True) for q in actual[key]):
            raise ValueError("Existing OEM source "+key+" changed")
    if Counter(json.dumps(q,sort_keys=True) for q in before["vias"])!=Counter(
               json.dumps(q,sort_keys=True) for q in actual["vias"]):
        raise ValueError("Source vias changed in control-only batch")
    lost=[]
    for prior in before["lines"]:
        if not C.coverage(prior,actual["lines"]) and not C.physical_copper_covers(
                prior,actual["lines"],full_original_width=True):
            lost.append(prior["id"])
    if lost:raise ValueError("Existing copper area erased on "+str(lost[:4]))
    for wire in order["tracks"]:
        if not C.coverage(wire,actual["lines"]) and not C.physical_copper_covers(
                wire,actual["lines"],full_original_width=False):
            raise ValueError("Native new low-current copper absent "+str(wire))
    return {"components":77,"pads":443,"nets":65,"original_copper_physically_covered":True,
            "new_control_stubs_physically_covered":len(order["tracks"]),
            "existing_90_vias_preserved":True,"manufacturer_approved":False}

def resume():
    order=plan()
    if order["preflight_problems"]:raise ValueError("Unsafe stale route preflight")
    if not PLAN.exists() or json.loads(PLAN.read_text(encoding="utf-8"))!=order:
        raise ValueError("Missing exact source-locked staged routing plan")
    if not TARGET.is_file() or sha(TARGET)==sha(SOURCE):
        raise ValueError("No distinct saved native candidate")
    prior=sha(TARGET)
    sid=open_board("reopen")
    if not sid:return 1
    try:
        rb=A.invoke(sid,A.READ_JS.read_text(encoding="utf-8"))
        dump("reopen_readback",rb)
        if not rb.get("ok"):raise ValueError("Native readback failed")
        receipt=verify(rb["value"],order)
        drc=A.invoke(sid,A.DRC_JS.read_text(encoding="utf-8"))
        dump("drc_raw",drc)
        if not drc.get("ok"):raise ValueError("Native DRC command failed")
    finally:
        dump("reopen_close",A.D.call(A.D.build_close_args(sid)))
    if sha(TARGET)!=prior:raise ValueError("Read-only verification changed actual project")
    before=order["original_native_drc"]
    after=A.R.categories(drc)
    if (after.get("Connection Error",999)>=before["Connection Error"] or
         after.get("Netlist Error",0)>before.get("Netlist Error",0) or
         after.get("Physical Error",0)):
        raise ValueError("No actual DRC connection improvement or unsafe violation")
    data={"status":"REAL_NATIVE_OEM_CONTROL_LINKS_REOPEN_DRC_NOT_FOR_FAB",
          "source_sha256":sha(SOURCE),"candidate_sha256":sha(TARGET),
          "plan_sha256":sha(PLAN),"previous_native_drc":before,
          "actual_native_drc":after,"reopen":receipt,
          "100A_busbar_or_protection_approved":False,"fabrication_approved":False}
    dump("drc_delta",data)
    print(json.dumps(data,indent=2))
    return 0

def apply():
    order=plan()
    if order["preflight_problems"]:
        raise ValueError("Control routes clash with active native CAD: "+str(order["preflight_problems"][:12]))
    if TARGET.exists():raise FileExistsError("No overwrite/reapply of native G2 V4")
    PLAN.write_text(json.dumps(order,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n")
    frozen=sha(SOURCE)
    shutil.copy2(SOURCE,TARGET)
    sid=open_board("apply")
    if not sid:return 1
    saved=False
    try:
        for i in range(0,len(order["tracks"]),9):
            obj=A.invoke(sid,C.js_tracks(order["tracks"][i:i+9]))
            dump("apply_batch_"+str(i//9+1),obj)
            if not obj.get("ok") or not (obj.get("value") or {}).get("all_created"):
                raise RuntimeError("Native partial batch; inspect saved copy, never reapply")
        obj=A.invoke(sid,"return await eda.pcb_Document.save();")
        dump("apply_save",obj)
        saved=bool(obj.get("ok") and obj.get("value") is True)
        if saved:time.sleep(30)
    finally:
        dump("apply_close",A.D.call(A.D.build_close_args(sid)))
    if not saved or sha(SOURCE)!=frozen or sha(TARGET)==frozen:
        raise ValueError("Native V4 save did not persist")
    return resume()

def main():
    a=argparse.ArgumentParser(description=__doc__)
    g=a.add_mutually_exclusive_group(required=True)
    g.add_argument("--check",action="store_true")
    g.add_argument("--apply",action="store_true")
    g.add_argument("--resume",action="store_true")
    arg=a.parse_args()
    if arg.check:
        order=plan()
        print(json.dumps({k:v for k,v in order.items() if k!="tracks"},indent=2))
        return 0 if not order["preflight_problems"] else 1
    return apply() if arg.apply else resume()

if __name__=="__main__":
    raise SystemExit(main())

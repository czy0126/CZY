"""G2 official KEMET Density-B 16x5 local capacitor copper, separate native PCB.

Each of the 32 same-net polarity columns has 1.6mm top-local connections:
112 segments across 72 OEM-dimensioned capacitor lands. This is only local
current collection, NOT 100A main bus, true component instances or fab release.

    python hardware/dcx_main/g2/route_t530_oem_16x5_columns.py --check
    python hardware/dcx_main/g2/route_t530_oem_16x5_columns.py --apply
    python hardware/dcx_main/g2/route_t530_oem_16x5_columns.py --resume

--apply writes a new file exactly once. --resume never writes primitives.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import shutil
import sys
import time
from collections import Counter,defaultdict
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/"tools"))
import cout_t530_72 as C
import g2_board_keepout as K
import apply_t530_density_b_v2_native as A
import plan_t530_72_oem_density_b as P

SOURCE=A.TARGET
TARGET=HERE/"dcx_main_board_g2_T530_OEM_DENSITY_B_V2_LOCAL_COLUMNS_NOT_FOR_FAB.eprj2"
PREFIX="g2_t530_oem_density_b_columns"
PLAN=HERE/(PREFIX+"_plan.json")
DELTA=HERE/(PREFIX+"_drc_delta.json")
WIDTH=1.6
CLEARANCE=0.30
MM_TO_MIL=1/0.0254

def sha(p:Path):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def source():
    if not SOURCE.is_file() or sha(SOURCE)!=json.loads(A.DELTA.read_text(encoding="utf-8"))["candidate_sha256"]:
        raise ValueError("G2 144 pad native source differs from accepted DRC")
    r=json.loads(A.PADS.read_text(encoding="utf-8"))
    if not r.get("ok") or not r.get("value"):
        raise ValueError("Cannot inspect the actually reopened G2 source")
    data=r["value"]
    if (len(data["components"]),len(data["pads"]),len(data["lines"]),
        len(data["vias"]),len(data["nets"]))!=(77,443,149,18,65):
        raise ValueError("Actual G2 native source geometry changed")
    return data

def generate():
    old=source()
    orig=P.make()
    A.review(old,orig)
    groups=defaultdict(list)
    for pad in A.pad_rows(orig):
        groups[(pad["net"],round(pad["centre_mm"][0],4))].append(pad)
    routes=[]
    failures=[]
    for (net,x),lands in sorted(groups.items()):
        lands.sort(key=lambda p:p["centre_mm"][1])
        for one,two in zip(lands,lands[1:]):
            y0=float(one["centre_mm"][1]); y1=float(two["centre_mm"][1])
            if y1-y0<2.7:
                failures.append("pads overlap: "+one["number"]+"/"+two["number"])
            # This conservative rectangle includes clearance around entire
            # segment, including lands, against ALL other-net copper.
            keep=(x-WIDTH/2-CLEARANCE,y0-CLEARANCE,
                  x+WIDTH/2+CLEARANCE,y1+CLEARANCE)
            for pad in old["pads"]:
                if pad["Net"]==net:
                    continue
                if C.touches(keep,K.pad_bbox(pad)):
                    failures.append("pad: "+one["number"]+" / "+str(pad.get("PadNumber")))
            for line in old["lines"]:
                if line["net"]==net or int(line["layer"])!=1:continue
                half=float(line["width"])*.0254/2
                expanded=(keep[0]-half,keep[1]-half,keep[2]+half,keep[3]+half)
                a=(float(line["x1"])*.0254,-float(line["y1"])*.0254)
                b=(float(line["x2"])*.0254,-float(line["y2"])*.0254)
                if C.segment_hits_rectangle(a,b,expanded):
                    failures.append("trace: "+one["number"]+" / "+str(line["id"]))
            for via in old["vias"]:
                if via["net"]==net:continue
                loc=(float(via["x"])*.0254,-float(via["y"])*.0254)
                if K.distance_to_box(loc,keep)<float(via["diameter"])*.0254/2:
                    failures.append("via: "+one["number"]+" / "+str(via["id"]))
            routes.append({"net":net,"start_pad":one["number"],"end_pad":two["number"],
                           "x_mm":x,"y0_mm":y0,"y1_mm":y1,"width_mm":WIDTH,
                           "layer":1})
    if len(routes)!=112 or len(groups)!=32:
        raise ValueError("Expected 32 polarity columns and 112 real local copper segments")
    if len({(r["start_pad"],r["end_pad"]) for r in routes})!=112:
        raise ValueError("Duplicate physical pair")
    return {"status":"REAL_OEM_DENSITY_B_G2_144_LANDS_LOCAL_1P6MM_COPPER_TRIAL",
            "source_board_sha256":sha(SOURCE),
            "source_readback_sha256":sha(A.PADS),
            "source_pad_plan_sha256":sha(P.OUT),
            "segments":routes,
            "count":len(routes),"groups":len(groups),
            "problems":sorted(set(failures)),
            "top_layer_local_cap_copper_only":True,
            "real_high_current_pole_bars_done":False,
            "oem_footprint_approved":False,"fabrication_approved":False}

def dump(s,x):
    (HERE/f"{PREFIX}_{s}.json").write_text(
        json.dumps(x,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n")

def draw_js(routes):
    items=[{"net":q["net"],"x":round(q["x_mm"]*MM_TO_MIL,7),
            "y0":round(-q["y0_mm"]*MM_TO_MIL,7),
            "y1":round(-q["y1_mm"]*MM_TO_MIL,7),
            "w":round(WIDTH*MM_TO_MIL,7)} for q in routes]
    return """return await (async()=>{
      const LINES=%s;
      let board;
      for(let i=0;i<20&&!board;i++){
        const info=await eda.dmt_Project.getCurrentProjectInfo();
        board=info?.data?.find(d=>d?.pcb?.uuid);
        if(!board)await new Promise(r=>setTimeout(r,500));
      }
      if(!board)throw new Error("PCB missing after 10s");
      await eda.dmt_EditorControl.openDocument(board.pcb.uuid);
      await new Promise(r=>setTimeout(r,1000));
      const old=await eda.pcb_PrimitivePad.getAll();
      if(old.length!==443)throw new Error("expected 443 saved OEM/native pads, got "+old.length);
      const out=[];
      for(const x of LINES){
        try{
          const line=await eda.pcb_PrimitiveLine.create(
             x.net,1,x.x,x.y0,x.x,x.y1,x.w,false);
          if(!line)throw new Error("new line is null");
          out.push({net:x.net,ok:true,id:line.getState_PrimitiveId()});
        }catch(e){out.push({net:x.net,ok:false,error:String(e)});break;}
      }
      return {requested:LINES.length,created:out,
        all_created:out.length===LINES.length&&out.every(q=>q.ok)};
    })();""" % json.dumps(items,separators=(",",":"))

def review_readback(native,plan):
    parent=source()
    for k,n in (("components",77),("pads",443),("vias",18),("nets",65)):
        if len(native[k])!=n or Counter(json.dumps(x,sort_keys=True) for x in native[k])!=Counter(
            json.dumps(x,sort_keys=True) for x in parent[k]):
            raise ValueError("Modified parent primitive: "+k)
    old=Counter(json.dumps(x,sort_keys=True) for x in parent["lines"])
    now=Counter(json.dumps(x,sort_keys=True) for x in native["lines"])
    # Native may split/merge at intersections, but it must retain all original copper exactly.
    if old-now:
        raise ValueError("Previously accepted source copper disappeared")
    added=list((now-old).elements())
    if len(added)!=len(plan["segments"]):
        raise ValueError(f"Expected {len(plan['segments'])} actual new copper, found {len(added)}")
    points=set()
    for wire in added:
        line=json.loads(wire)
        if line["layer"]!=1 or round(line["width"]*.0254,3)!=WIDTH:
            raise ValueError("Non-top layer or wrong copper width")
        pts=((round(line["x1"]*.0254,3),round(-line["y1"]*.0254,3)),
             (round(line["x2"]*.0254,3),round(-line["y2"]*.0254,3)))
        points.add((line["net"],tuple(sorted(pts))))
    expected={(q["net"],tuple(sorted(((round(q["x_mm"],3),round(q["y0_mm"],3)),
                                     (round(q["x_mm"],3),round(q["y1_mm"],3))))))
              for q in plan["segments"]}
    if points!=expected:
        raise ValueError(f"Native 112 new copper mismatch: missing={list(expected-points)[:4]}")
    return {"old_149_tracks_preserved":True,"new_actual_top_copper_segments":len(added),
            "real_pad_count":443,"component_count":77,
            "all_112_real_pad_pairs_covered":True}

def open_board(label):
    session=A.D.call(A.D.build_open_args(TARGET),timeout_s=90)
    dump(label+"_open",session)
    sid=(session.get("value") or {}).get("sessionId")
    if not sid:return None
    time.sleep(A.D.SETTLE_S)
    ping=A.D.call(A.D.build_ping_args(sid),timeout_s=30)
    dump(label+"_ping",ping)
    if not ping.get("ok"):
        dump(label+"_close",A.D.call(A.D.build_close_args(sid)))
        return None
    return sid

def resume():
    plan=generate()
    if plan["problems"]:raise ValueError("Unsafe new routing geometry")
    if not TARGET.is_file() or sha(TARGET)==sha(SOURCE):
        raise RuntimeError("No distinct native saved candidate; do NOT re-apply uncertain copper")
    s=open_board("reopen")
    if not s:
        print("Native reopen pending/failed; candidate preserved, no duplicate apply")
        return 1
    try:
        rd=A.invoke(s,A.READ_JS.read_text(encoding="utf-8"))
        dump("reopen_readback",rd)
        if not rd.get("ok"):return 1
        audit=review_readback(rd["value"],plan)
        drc=A.invoke(s,A.DRC_JS.read_text(encoding="utf-8"))
        dump("drc_raw",drc)
        if not drc.get("ok"):return 1
    finally:
        dump("reopen_close",A.D.call(A.D.build_close_args(s)))
    cat=A.R.categories(drc)
    before=A.R.categories(json.loads((HERE/(A.PREFIX+"_drc_raw.json")).read_text(encoding="utf-8")))
    if cat.get("Connection Error",999)>=before["Connection Error"]:
        raise RuntimeError("Real G2 copper failed to reduce opens")
    if cat.get("Netlist Error",0)>before.get("Netlist Error",0) or cat.get("Physical Error",0)>0:
        raise RuntimeError("New G2 collector copper caused extra physical/netlist DRC")
    summary={"status":"REAL_G2_OEM_DENSITY_B_LOCAL_COLUMN_NATIVE_REOPEN_DRC_NOT_FOR_FAB",
      "parent_sha256":sha(SOURCE),"candidate_sha256":sha(TARGET),
      "plan_sha256":sha(PLAN),"previous_native_drc":before,"actual_native_drc":cat,
      "readback":audit,"both_pole_bar_connected":False,
      "true_oem_cout_component_instances":False,"manufacturing_approved":False}
    dump("drc_delta",summary)
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    return 0

def apply():
    plan=generate()
    if plan["problems"]:raise ValueError("G2 local 112 copper paths have collisions: "+repr(plan["problems"][:5]))
    if TARGET.exists():raise FileExistsError("Saved candidate exists; use --resume only")
    PLAN.write_text(json.dumps(plan,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n")
    original=sha(SOURCE)
    shutil.copy2(SOURCE,TARGET)
    sid=open_board("apply")
    if not sid:
        print("EasyEDA could not open copied source; no copper created")
        return 1
    saved=False
    try:
        for i in range(0,len(plan["segments"]),18):
            r=A.invoke(sid,draw_js(plan["segments"][i:i+18]))
            dump("apply_batch_"+str(i//18+1),r)
            v=r.get("value") or {}
            if not r.get("ok") or not v.get("all_created"):
                print("Native copper partial/uncertain; no save and no repeat without inspection")
                return 1
        ack=A.invoke(sid,"return await eda.pcb_Document.save();")
        dump("apply_save",ack)
        saved=bool(ack.get("ok") and ack.get("value") is True)
        if not saved:return 1
        time.sleep(30)
    finally:
        dump("apply_close",A.D.call(A.D.build_close_args(sid)))
    if sha(SOURCE)!=original or not saved or sha(TARGET)==original:
        raise RuntimeError("Native G2 save or frozen parent integrity failure")
    return resume()

def main():
    p=argparse.ArgumentParser()
    g=p.add_mutually_exclusive_group(required=True)
    g.add_argument("--check",action="store_true")
    g.add_argument("--apply",action="store_true")
    g.add_argument("--resume",action="store_true")
    v=p.parse_args()
    if v.check:
        print(json.dumps({k:v for k,v in generate().items() if k!="segments"},indent=2))
        return 0 if not generate()["problems"] else 1
    return apply() if v.apply else resume()

if __name__=="__main__":
    raise SystemExit(main())

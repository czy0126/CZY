"""Physically join both polarities of the 72-cap G2 trial board.

Top L1 PGND: 18 column drops + 17 cross-column links.
Bottom L2 VOUT: 17 horizontal links + 18 through vias to actual L1
positive column copper.  All primitives are grounded in 257-track native
reopen evidence, and screened against actual old copper/pads/vias.

THIS IS ELECTRICAL CONNECTIVITY ONLY.  The 1.6mm tracks and single via per
VOUT column are NOT 100A-qualified; zero DRC doesn't certify ampacity,
thermal performance, OEM land pattern, terminals or 16mm assembly.

python hardware/dcx_main/g2/connect_t530_both_poles.py --check
python hardware/dcx_main/g2/connect_t530_both_poles.py --apply
python hardware/dcx_main/g2/connect_t530_both_poles.py --resume

One-shot only. A saved candidate MUST be resumed (never re-applied).
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
import cout_t530_72 as C
import g2_board_keepout as K
import route_t530_bank_columns as B
import apply_t530_72_native as A
import plan_t530_72_native as P

SOURCE=B.TARGET
TARGET=HERE/"dcx_main_board_g2_t530_72_BIPOLAR_ARRAY_NOT_FOR_FAB.eprj2"
PREFIX="g2_t530_bipolar"
PLAN=HERE/(PREFIX+"_plan.json")
DELTA=HERE/(PREFIX+"_drc_delta.json")
TOP=1
BOTTOM=2
TRACK_MM=1.6
EDGE_PGND_Y=127.5
VOUT_CROSSOVER_Y=102.2
VIA_DRILL_MM=0.4
VIA_OUTER_MM=1.1
CLEARANCE=0.30
MIL=1/.0254

def sha(p:Path)->str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

def dump(s,v):
    (HERE/(PREFIX+"_"+s+".json")).write_text(
        json.dumps(v,ensure_ascii=False,indent=2)+"\n",
        encoding="utf-8",newline="\n")

def parent():
    receipt=json.loads(B.DELTA.read_text(encoding="utf-8"))
    if not SOURCE.is_file() or sha(SOURCE)!=receipt["candidate_sha256"]:
        raise ValueError("257 native line G2 source SHA drift")
    r=json.loads((HERE/"g2_t530_collector_reopen_readback.json").read_text(encoding="utf-8"))
    if not r.get("ok"):raise ValueError("Native G2 parent readback missing")
    d=r["value"]
    if (len(d["components"]),len(d["pads"]),len(d["lines"]),len(d["vias"]),len(d["nets"]))!=(77,443,257,18,65):
        raise ValueError("Unexpected real native G2 parent counts")
    return d

def original_pads():
    d=P.make()
    if d["problems"]:raise ValueError("Earlier OEM provisional pad trial drift")
    return A.pad_rows(d)

def route_rows()->dict:
    d=parent()
    pads=original_pads()
    cols={}
    for net in ("PGND","VOUT"):
        cols[net]=sorted(set(round(p["centre_mm"][0],4) for p in pads if p["net"]==net))
    if len(cols["PGND"])!=18 or len(cols["VOUT"])!=18:
        raise ValueError("Expected precisely 18 real capacitor columns per net")
    tracks=[]
    for x in cols["PGND"]:
        last=max(p["centre_mm"][1] for p in pads
                 if p["net"]=="PGND" and abs(p["centre_mm"][0]-x)<1e-5)
        tracks.append({"net":"PGND","layer":TOP,"width_mm":TRACK_MM,
                       "a_mm":[x,last],"b_mm":[x,EDGE_PGND_Y]})
    for x,y in zip(cols["PGND"],cols["PGND"][1:]):
        tracks.append({"net":"PGND","layer":TOP,"width_mm":TRACK_MM,
                       "a_mm":[x,EDGE_PGND_Y],"b_mm":[y,EDGE_PGND_Y]})
    for x,y in zip(cols["VOUT"],cols["VOUT"][1:]):
        tracks.append({"net":"VOUT","layer":BOTTOM,"width_mm":TRACK_MM,
                       "a_mm":[x,VOUT_CROSSOVER_Y],"b_mm":[y,VOUT_CROSSOVER_Y]})
    vias=[{"net":"VOUT","xy_mm":[x,VOUT_CROSSOVER_Y],"hole_mm":VIA_DRILL_MM,
           "diameter_mm":VIA_OUTER_MM} for x in cols["VOUT"]]
    issues=[]
    # Screen every proposed actual L1/L2 track against all old other-net
    # solder lands, routed copper and through-via annular rings.
    for k,q in enumerate(tracks):
        x0,y0=q["a_mm"];x1,y1=q["b_mm"]
        t=q["width_mm"]/2+CLEARANCE
        rect=(min(x0,x1)-t,min(y0,y1)-t,max(x0,x1)+t,max(y0,y1)+t)
        for pad in d["pads"]:
            if pad["Net"]!=q["net"] and int(pad["Layer"]) in (q["layer"],12,0):
                if C.touches(rect,K.pad_bbox(pad)):
                    issues.append("track %d hits other-net pad %s.%s"%(k,pad.get("ref"),pad["PadNumber"]))
        for old in d["lines"]:
            if old["net"]==q["net"] or int(old["layer"])!=q["layer"]:
                continue
            half=old["width"]*.0254/2
            grow=(rect[0]-half,rect[1]-half,rect[2]+half,rect[3]+half)
            if C.segment_hits_rectangle((old["x1"]*.0254,-old["y1"]*.0254),
                                        (old["x2"]*.0254,-old["y2"]*.0254),grow):
                issues.append("track %d hits other-net line %s"%(k,old["id"]))
        for via in d["vias"]:
            if via["net"]!=q["net"] and K.distance_to_box(
                (via["x"]*.0254,-via["y"]*.0254),rect)<via["diameter"]*.0254/2:
                issues.append("track %d hits other-net via %s"%(k,via["id"]))
    for k,q in enumerate(vias):
        x,y=q["xy_mm"];r=q["diameter_mm"]/2+CLEARANCE
        for pad in d["pads"]:
            if pad["Net"]!=q["net"] and K.distance_to_box((x,y),K.pad_bbox(pad))<r:
                issues.append("via %d hits other-net pad %s"%(k,pad["PadNumber"]))
        for old in d["lines"]:
            if old["net"]==q["net"]:continue
            ax,ay=old["x1"]*.0254,-old["y1"]*.0254
            bx,by=old["x2"]*.0254,-old["y2"]*.0254
            dx,dy=bx-ax,by-ay
            t=max(0,min(1,((x-ax)*dx+(y-ay)*dy)/(dx*dx+dy*dy))) if dx*dx+dy*dy else 0
            if math.hypot(x-ax-t*dx,y-ay-t*dy)<r+old["width"]*.0254/2:
                issues.append("via %d hits other-net line %s"%(k,old["id"]))
        for old in d["vias"]:
            if (old["net"]!=q["net"] and math.dist(
                (x,y),(old["x"]*.0254,-old["y"]*.0254)) <
                r+old["diameter"]*.0254/2):
                issues.append("via %d hits other-net via %s"%(k,old["id"]))
        if not any(old["net"]=="VOUT" and int(old["layer"])==1 and
                   _on_segment((x,y),old) for old in d["lines"]):
            issues.append("via %d is not on real L1 VOUT collector copper"%(k))
    if len(tracks)!=52 or len(vias)!=18:
        raise ValueError("Expected 52 copper links and 18 actual new vias")
    return {
       "schema":"G2_T530_DUAL_LAYER_BOTH_POLARITIES_CONNECTIVITY_V1",
       "status":"COLLECT_72_PROVISIONAL_CAP_LANDS_BOTH_POLARITIES_NOT_FOR_FAB",
       "source_sha256":sha(SOURCE),
       "previous_native_connection_errors":227,
       "tracks":tracks,"vias":vias,
       "problems":sorted(set(issues)),
       "pad_land_oem_approved":False,
       "line_width_100a_qualified":False,
       "via_thermal_100a_qualified":False,
       "two_pole_100a_busbar_qualified":False,
       "true_terminal_contact_qualified":False,
       "manufacturing_approved":False
    }

def _on_segment(p,ln,tol=.03):
    ax,ay=ln["x1"]*.0254,-ln["y1"]*.0254
    bx,by=ln["x2"]*.0254,-ln["y2"]*.0254
    dx,dy=bx-ax,by-ay;dist=dx*dx+dy*dy
    if not dist:return math.dist(p,(ax,ay))<tol
    t=((p[0]-ax)*dx+(p[1]-ay)*dy)/dist
    return -.01<=t<=1.01 and math.dist(p,(ax+t*dx,ay+t*dy))<tol

def js_tracks(rows):
    items=[[q["net"],q["layer"],round(q["width_mm"]*MIL,6),
            round(q["a_mm"][0]*MIL,6),round(-q["a_mm"][1]*MIL,6),
            round(q["b_mm"][0]*MIL,6),round(-q["b_mm"][1]*MIL,6)]
           for q in rows]
    return """return await (async()=>{
      const info=await eda.dmt_Project.getCurrentProjectInfo();
      const board=info?.data?.find(x=>x?.pcb?.uuid);
      if(!board)throw new Error("PCB document missing");
      await eda.dmt_EditorControl.openDocument(board.pcb.uuid);
      const layers=await eda.pcb_Layer.getTheNumberOfCopperLayers();
      if(layers<2)throw new Error("Requires at least two copper layers");
      const R=%s;let out=[];
      for(const x of R){
        try {
          const l=await eda.pcb_PrimitiveLine.create(
            x[0],x[1],x[3],x[4],x[5],x[6],x[2],false);
          if(!l)throw new Error("null primitive");
          out.push({ok:true,net:x[0],id:l.getState_PrimitiveId()});
        } catch(e) {out.push({ok:false,error:String(e)});break;}
      }
      return {requested:R.length,created:out,all_created:
        out.length===R.length&&out.every(x=>x.ok),layers};
    })();""" % json.dumps(items,separators=(",",":"))

def js_vias(rows):
    items=[[v["net"],round(v["xy_mm"][0]*MIL,6),
             round(-v["xy_mm"][1]*MIL,6),round(v["hole_mm"]*MIL,6),
             round(v["diameter_mm"]*MIL,6)] for v in rows]
    return """return await (async()=>{
      const info=await eda.dmt_Project.getCurrentProjectInfo();
      const board=info?.data?.find(x=>x?.pcb?.uuid);
      if(!board)throw new Error("PCB document missing");
      await eda.dmt_EditorControl.openDocument(board.pcb.uuid);
      const R=%s;let out=[];
      for(const x of R){
        try{
          const v=await eda.pcb_PrimitiveVia.create(
            x[0],x[1],x[2],x[3],x[4],0,null);
          if(!v)throw new Error("null via");
          out.push({ok:true,id:v.getState_PrimitiveId()});
        }catch(e){out.push({ok:false,error:String(e)});break;}
      }
      return {requested:R.length,created:out,all_created:
        out.length===R.length&&out.every(x=>x.ok)};
    })();""" % json.dumps(items,separators=(",",":"))

def coverage(q,lines,tol=.04):
    # Coverage of each original or planned physical straight interval.
    net,layer=q["net"],int(q["layer"])
    if "a_mm" in q:
        a=q["a_mm"];b=q["b_mm"]
    else:
        a=[q["x1"]*.0254,-q["y1"]*.0254]
        b=[q["x2"]*.0254,-q["y2"]*.0254]
    vx,vy=b[0]-a[0],b[1]-a[1]
    length=math.hypot(vx,vy)
    if length<.01:return True
    vx/=length;vy/=length;intervals=[]
    for ln in lines:
        if ln["net"]!=net or int(ln["layer"])!=layer:continue
        u=(ln["x1"]*.0254,-ln["y1"]*.0254)
        v=(ln["x2"]*.0254,-ln["y2"]*.0254)
        off1=abs(vx*(u[1]-a[1])-vy*(u[0]-a[0]))
        off2=abs(vx*(v[1]-a[1])-vy*(v[0]-a[0]))
        if max(off1,off2)>tol:continue
        t0=(u[0]-a[0])*vx+(u[1]-a[1])*vy
        t1=(v[0]-a[0])*vx+(v[1]-a[1])*vy
        intervals.append((min(t0,t1),max(t0,t1)))
    start=0
    for u,v in sorted(intervals):
        if u>start+tol:break
        start=max(start,v)
        if start>=length-tol:return True
    return False

def verify_readback(d,plan):
    old=parent()
    for field,n in (("components",77),("pads",443),("nets",65)):
        if len(d[field])!=n or Counter(json.dumps(x,sort_keys=True)
                 for x in old[field])!=Counter(json.dumps(x,sort_keys=True)
                 for x in d[field]):
            raise ValueError("Native G2 changed old schematic/pads/nets: "+field)
    for ln in old["lines"]:
        if not coverage(ln,d["lines"]):
            raise ValueError("Original accepted 257 copper track no longer covered: "+ln["id"])
    for q in plan["tracks"]:
        if not coverage(q,d["lines"]):
            raise ValueError("New bipolar conductor does not physically cover plan: "+repr(q))
    if len(d["vias"])!=18+len(plan["vias"]):
        raise ValueError("Native G2 via count wrong")
    oldvia=Counter(json.dumps(x,sort_keys=True) for x in old["vias"])
    newvia=Counter(json.dumps(x,sort_keys=True) for x in d["vias"])
    if oldvia-newvia:raise ValueError("Old native 18 vias deleted/changed")
    added=[json.loads(k) for k in (newvia-oldvia).elements()]
    for v in plan["vias"]:
        matches=[w for w in added if w["net"]==v["net"]
                 and math.dist((w["x"]*.0254,-w["y"]*.0254),v["xy_mm"])<.01
                 and abs(w["diameter"]*.0254-v["diameter_mm"])<.03
                 and abs(w["hole"]*.0254-v["hole_mm"])<.03]
        if len(matches)!=1:raise ValueError("Real new native via missing "+repr(v))
    return {"old_257_real_copper_lines_covered":True,
            "all_52_new_bipolar_tracks_covered":True,
            "new_bottom_vout_through_vias":len(added),
            "original_77_components_443_pads_65_nets_preserved":True,
            "fabrication_approved":False}

def open_board(label):
    d=A.D.call(A.D.build_open_args(TARGET),timeout_s=110)
    dump(label+"_open",d)
    sid=(d.get("value") or {}).get("sessionId")
    if not sid:return None
    time.sleep(A.D.SETTLE_S)
    q=A.D.call(A.D.build_ping_args(sid),timeout_s=45)
    dump(label+"_ping",q)
    if not q.get("ok"):
        dump(label+"_close",A.D.call(A.D.build_close_args(sid)))
        return None
    return sid

def resume():
    plan=route_rows()
    if plan["problems"]:raise ValueError("Unsafe geometry")
    if not TARGET.is_file() or sha(TARGET)==sha(SOURCE):
        raise ValueError("No distinct native bipolar candidate; refusing double-apply")
    if not PLAN.is_file() or json.loads(PLAN.read_text(encoding="utf-8"))!=plan:
        raise ValueError("Saved route plan missing or changed")
    target_sha=sha(TARGET)
    sid=open_board("reopen")
    if not sid:
        print("Native reopen unavailable; candidate saved, never re-apply")
        return 1
    try:
        rb=A.invoke(sid,A.READ_JS.read_text(encoding="utf-8"))
        dump("reopen_readback",rb)
        if not rb.get("ok"):return 1
        audit=verify_readback(rb["value"],plan)
        drc=A.invoke(sid,A.DRC_JS.read_text(encoding="utf-8"))
        dump("drc_raw",drc)
        if not drc.get("ok"):return 1
    finally:
        dump("reopen_close",A.D.call(A.D.build_close_args(sid)))
    if target_sha!=sha(TARGET):raise ValueError("Read-only reopen changed CAD bytes")
    cat=A.R.categories(drc)
    base=A.R.categories(json.loads((HERE/"g2_t530_collector_drc_raw.json").read_text(encoding="utf-8")))
    if cat.get("Connection Error",999)>=base["Connection Error"]:
        raise RuntimeError("No native G2 connection improvement")
    if cat.get("Netlist Error",0)>base.get("Netlist Error",0) or cat.get("Physical Error",0)>0:
        raise RuntimeError("Introduced new native netlist/physical DRC errors")
    d={"status":"REAL_G2_BIPOLAR_ARRAY_NETS_SAVED_REOPENED_DRC_NOT_100A_QUALIFIED",
       "parent_sha256":sha(SOURCE),"candidate_sha256":sha(TARGET),
       "plan_sha256":sha(PLAN),"previous_drc":base,"actual_drc":cat,
       "native_readback":audit,"both_polarity_cap_array_electrically_joined":True,
       "oem_package_added_as_real_components":False,
       "100a_current_carrying_and_contacts_qualified":False,
       "manufacturer_height_thermal_and_hot_esr_qualified":False,
       "fabrication_approved":False}
    dump("drc_delta",d)
    print(json.dumps(d,ensure_ascii=False,indent=2))
    return 0

def apply():
    plan=route_rows()
    if plan["problems"]:raise ValueError("Unsafe proposed G2 copper: "+repr(plan["problems"][:8]))
    if TARGET.exists():raise FileExistsError("Bipolar G2 target exists; ONLY --resume")
    PLAN.write_text(json.dumps(plan,ensure_ascii=False,indent=2)+"\n",
                    encoding="utf-8",newline="\n")
    source_sha=sha(SOURCE)
    shutil.copy2(SOURCE,TARGET)
    sid=open_board("apply")
    if not sid:return 1
    saved=False
    try:
        for index in range(0,len(plan["tracks"]),13):
            d=A.invoke(sid,js_tracks(plan["tracks"][index:index+13]))
            dump("apply_tracks_"+str(index//13+1),d)
            if not d.get("ok") or not (d.get("value") or {}).get("all_created"):
                print("Native track batch failed; refuse repeat without readback",repr(d)[:1200])
                return 1
        for index in range(0,len(plan["vias"]),9):
            d=A.invoke(sid,js_vias(plan["vias"][index:index+9]))
            dump("apply_vias_"+str(index//9+1),d)
            if not d.get("ok") or not (d.get("value") or {}).get("all_created"):
                print("Native via batch failed; refuse repeat without readback",repr(d)[:1200])
                return 1
        ack=A.invoke(sid,"return await eda.pcb_Document.save();")
        dump("apply_save",ack)
        saved=bool(ack.get("ok") and ack.get("value") is True)
        if saved:time.sleep(30)
    finally:
        dump("apply_close",A.D.call(A.D.build_close_args(sid)))
    if not saved or sha(SOURCE)!=source_sha or sha(TARGET)==source_sha:
        raise RuntimeError("G2 native save/source SHA failure")
    return resume()

def main():
    ap=argparse.ArgumentParser()
    group=ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--check",action="store_true")
    group.add_argument("--apply",action="store_true")
    group.add_argument("--resume",action="store_true")
    args=ap.parse_args()
    if args.check:
        d=route_rows()
        print(json.dumps({k:v for k,v in d.items() if k not in ("tracks","vias")},indent=2))
        return int(bool(d["problems"]))
    return apply() if args.apply else resume()

if __name__=="__main__":
    raise SystemExit(main())

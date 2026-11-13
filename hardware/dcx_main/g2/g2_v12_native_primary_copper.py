"""Native G2 V12 primary resonant-path copper from saved independent V11.

CR_CT: Cr.2 -> CT raw PRI_A, 1.2 mm TOP copper, 8.32 mm.
PRI_T1: Lr.2 -> T1 raw PRI_A, 3.0 mm TOP copper, 27.99 mm.
Both are primary resonant ~9A RMS, NOT 100A output paths. Terminal geometry
and OEM magnetics still unqualified. No original V11/V10/V9 GUI changes.

Run once only:
    python hardware/dcx_main/g2/g2_v12_native_primary_copper.py --plan
    python hardware/dcx_main/g2/g2_v12_native_primary_copper.py --apply
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
import time
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"hardware/dcx_main/g1"),str(HERE)]
import g2_board_keepout as K
import route_driver_eco as GEOM
import g2_oem_net_islands as ISLAND
import route_open_connections as ROUTE
import g2_v11_eight_sr_gate_escape as V11

D=V11.V9.D
SOURCE=V11.TARGET
SOURCE_SHA="d90ca22079ad7245e8c3904eb8369da58c705ae39b56574bf7843dad34cad89b"
SOURCE_READBACK=HERE/"g2_v11_independent_native_full_readback_NOT_FOR_FAB.json"
SOURCE_REOPEN=HERE/"g2_v11_independent_native_reopen_verified_NOT_FOR_FAB.json"
TARGET=HERE/"dcx_main_board_g2_V12_NATIVE_PRIMARY_RESONANT_LINKS_NOT_FOR_FAB.eprj2"
PLAN=HERE/"g2_v12_native_primary_copper_plan_NOT_FOR_FAB.json"
ATTEMPT=HERE/"g2_v12_primary_copper_attempt_once_NOT_FOR_FAB.json"
APPLIED=HERE/"g2_v12_primary_copper_native_applied_NOT_FOR_FAB.json"
LIVE_DRC=HERE/"g2_v12_primary_copper_native_live_drc_NOT_FOR_FAB.json"
M=.0254
CLEAR_MM=.18
EXPECT={"components":149,"pads":443,"lines":465,"vias":93,"nets":65}


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write_once(path,record):
    if path.exists():raise FileExistsError("Never replay or replace previous native evidence: "+str(path))
    path.write_text(json.dumps(record,indent=2,ensure_ascii=False)+"\n",encoding="utf8",newline="\n")


def source():
    if sha(SOURCE)!=SOURCE_SHA or sha(V11.SOURCE)!=V11.SOURCE_SHA:
        raise ValueError("Source V11/V10 independently saved CAD hash drift")
    receipt=json.loads(SOURCE_REOPEN.read_text("utf8"))
    doc=json.loads(SOURCE_READBACK.read_text("utf8"))
    if (receipt["status"]!="V11_INDEPENDENT_NATIVE_GUI_REOPEN_AND_DRC_PASSED_NOT_FOR_FAB" or
        receipt["saved_V11_native_sha256"]!=SOURCE_SHA or
        receipt["real_native_DRC"]!={"Connection Error":149,"Netlist Error":1} or
        doc["source_native_sha256"]!=SOURCE_SHA or
        doc["native_counts"]!=EXPECT):
        raise ValueError("Native V11 independent readback/DRC not authenticated")
    return doc["real_native_data"]


def pin(p,net,ref,number):
    matches=[x for x in p["pads"] if x["Net"]==net and
             x.get("ref")==ref and str(x["PadNumber"])==number and int(x["Layer"])==1]
    if len(matches)!=1:raise ValueError("G2 P1 raw magnetic pad/part lost "+net+" "+str(ref)+"."+number)
    return matches[0]


def xy(p):
    return [round(p["X"]*M,5),round(-p["Y"]*M,5)]


def plan():
    native=source()
    plans=[]
    for net,from_ref,from_no,to_ref,to_no,width in (
         ("CR_CT","Cr","2",None,"PRI_A",1.2),
         ("PRI_T1","Lr","2",None,"PRI_A",3.0)):
        a=pin(native,net,from_ref,from_no)
        b=pin(native,net,to_ref,to_no)
        x,y=xy(a),xy(b)
        if not (6<math.dist(x,y)<30):raise ValueError("Unexpected primary current path length")
        plans.append({"net":net,"layer":1,"start_designator":from_ref,
             "start_pin":from_no,"end_designator":to_ref or "RAW_MAGNETIC_TERMINAL",
             "end_pin":to_no,"a_mm":x,"b_mm":y,"width_mm":width,
             "length_mm":round(math.dist(x,y),5)})
    issues=[]
    for i,s in enumerate(plans):
        a,b=s["a_mm"],s["b_mm"]
        required=s["width_mm"]/2+CLEAR_MM
        for p in native["pads"]:
            if p["Net"]==s["net"] or int(p["Layer"]) not in (0,1,11,12):
                continue
            edge=GEOM._segment_rect(a,b,K.pad_bbox(p))
            if edge+1e-6<required:
                issues.append((i,"pad",(p.get("ref") or "RAW")+"."+str(p["PadNumber"]),p["Net"],round(edge-required,5)))
        for q in native["lines"]:
            if q["net"]==s["net"] or int(q["layer"])!=1:continue
            c=(q["x1"]*M,-q["y1"]*M);d=(q["x2"]*M,-q["y2"]*M)
            gap=GEOM._segment_segment(a,b,c,d)-q["width"]*M/2-required
            if gap<-.0001:issues.append((i,"line",q["id"],q["net"],round(gap,5)))
        for q in native["vias"]:
            if q["net"]==s["net"]:continue
            c=(q["x"]*M,-q["y"]*M)
            gap=K.segment_distance(c,a,b)-q["diameter"]*M/2-required
            if gap<-.0001:issues.append((i,"via",q["id"],q["net"],round(gap,5)))
        for t in plans[:i]:
            if GEOM._segment_segment(a,b,t["a_mm"],t["b_mm"]) < (s["width_mm"]+t["width_mm"])/2+CLEAR_MM:
                issues.append((i,"new copper","other",t["net"],-1))
        for pt in (a,b):
            if not (2<=pt[0]<=153 and 2<=pt[1]<=129):
                issues.append((i,"edge",pt,"board",0))
    if issues:raise ValueError("New primary copper violates native unlike-net spacing "+str(issues[:8]))
    before=ISLAND.islands(native,{"CR_CT","PRI_T1"})
    sim=dict(native)
    sim["lines"]=native["lines"]+[{"id":"V12_SIMULATED_"+x["net"],"net":x["net"],
             "layer":1,"x1":x["a_mm"][0]/M,"y1":-x["a_mm"][1]/M,
             "x2":x["b_mm"][0]/M,"y2":-x["b_mm"][1]/M,
             "width":x["width_mm"]/M} for x in plans]
    after=ISLAND.islands(sim,{"CR_CT","PRI_T1"})
    pre={x:y["island_count_geometry_screen"] for x,y in before.items()}
    post={x:y["island_count_geometry_screen"] for x,y in after.items()}
    if pre!={"CR_CT":2,"PRI_T1":2} or post!={"CR_CT":1,"PRI_T1":1}:
        raise ValueError("Actual primary net did not reduce from 2 islands to 1")
    # Rough uniform copper resistance only, 70um nominal and 100C rho model.
    rho_20=1.724e-8
    temp_factor=1+.00393*(100-20)
    for route in plans:
        length=route["length_mm"]*.001
        area=route["width_mm"]*.001*70e-6
        route["upper_uniform_copper_R_100C_mOhm"]=round(rho_20*temp_factor*length/area*1000,5)
        route["9p45A_RMS_100C_straight_trace_model_W"]=round(
           rho_20*temp_factor*length/area*9.45014**2,5)
        route["unverified_copper_thickness_um"]=70
    return {"schema":"G2_V12_GENUINE_NATIVE_PRIMARY_RESONANT_COPPER_PILOT_V1",
        "source_V11_native_sha256":SOURCE_SHA,"source_native_counts":EXPECT,
        "native_DRC_before":{"Connection Error":149,"Netlist Error":1},
        "new_top_primary_net_tracks":plans,"physical_preflight_issues":issues,
        "source_native_islands":pre,"proposed_native_islands":post,
        "source_magnetics_bare_pads_instead_of_approved_devices":True,
        "not_an_output_100A_bus":True,"N97_100C_LI_current_safety_qualified":False,
        "manufacturer_DFM_approved":False,"fabrication_approved":False}


def js_apply(uuid,plan):
    segs=[[x["net"],1,x["a_mm"][0]/M,-x["a_mm"][1]/M,
          x["b_mm"][0]/M,-x["b_mm"][1]/M,x["width_mm"]/M]
          for x in plan["new_top_primary_net_tracks"]]
    return """return await(async()=>{
      const p=await eda.dmt_Project.getCurrentProjectInfo();
      if(p?.friendlyName!==%s)throw Error("Wrong original project; refuse V12");
      await eda.dmt_EditorControl.openDocument(%s);
      if((await eda.pcb_PrimitiveComponent.getAll()).length!==149 ||
         (await eda.pcb_PrimitivePad.getAll()).length!==443 ||
         (await eda.pcb_PrimitiveVia.getAll()).length!==93 ||
         (await eda.pcb_PrimitiveLine.getAll()).length!==465)
        throw Error("Saved native V11 component/line inventory not exact");
      const requests=%s,created=[];
      for(const q of requests){
        try{const x=await eda.pcb_PrimitiveLine.create(...q,false);
          if(!x)throw Error("native copper line null");
          created.push({ok:true,id:x.getState_PrimitiveId()});}
        catch(e){created.push({ok:false,error:String(e)});break;}
      }
      return {requested:requests.length,created,all_created:
        created.length===requests.length&&created.every(x=>x.ok),
        new_line_count:(await eda.pcb_PrimitiveLine.getAll()).length};
    })();"""%(json.dumps(TARGET.stem),json.dumps(uuid),json.dumps(segs,separators=(",",":")))


def required(resp,what):
    if resp.get("ok") is not True:
        raise RuntimeError(what+": "+str(resp.get("error")))
    return resp["value"]


def invoke(sid,code,timeout=59000):
    return D.call(D.build_invoke_args(sid,code,timeout),timeout_s=75)


def apply():
    if any(x.exists() for x in (ATTEMPT,APPLIED,TARGET,LIVE_DRC)):
        raise FileExistsError("V12 one-shot attempt exists, preserve; never replay")
    p=plan()
    if not PLAN.exists() or json.loads(PLAN.read_text("utf8"))!=p:
        raise ValueError("V12 source locked preflight missing")
    shutil.copy2(SOURCE,TARGET)
    if sha(TARGET)!=SOURCE_SHA:raise ValueError("V11->V12 original native clone not exact")
    old=required(D.call([str(D.LEDA),"session","list"],timeout_s=22),"GUI inventory before")
    users={x["sessionId"] for x in old if x.get("status")=="alive" and x.get("headless") is False}
    write_once(ATTEMPT,{"source_sha":SOURCE_SHA,"original_visible_GUI":sorted(users),
            "requested_native_new_lines":2,"one_shot":True,"fabrication_approved":False})
    sid=None
    try:
        args=D.build_open_args(TARGET)
        if args[-2:]!=["--headless","true"]:raise RuntimeError("Unexpected native GUI protocol")
        args[-1]="false"
        opened=required(D.call(args,timeout_s=120),"open independent V12 target")
        sid=opened["sessionId"]
        time.sleep(D.SETTLE_S+3)
        required(D.call(D.build_ping_args(sid),timeout_s=20),"V12 renderer ping")
        info=required(invoke(sid,"return await(async()=>{const p=await eda.dmt_Project.getCurrentProjectInfo();return{name:p?.friendlyName,pcb:p?.data?.find(x=>x?.pcb?.uuid)?.pcb?.uuid};})();",18000),"native V12 project")
        if info["name"]!=TARGET.stem or not info["pcb"]:raise RuntimeError("Wrong PCB document")
        wrote=required(invoke(sid,js_apply(info["pcb"],p)),"native V12 two actual power traces")
        write_once(APPLIED,{"session_id":sid,"native_reply":wrote,
            "source_sha":SOURCE_SHA,"fabrication_approved":False})
        if not wrote["all_created"] or wrote["new_line_count"]<467:
            raise RuntimeError("V12 native edits only partially applied. Do not retry.")
        drc=invoke(sid,"return await eda.pcb_Drc.check(true,false,true);")
        counts=ROUTE.categories(drc)
        write_once(LIVE_DRC,{"source_sha":SOURCE_SHA,"native_categories":counts,
            "raw_native_response":drc,"session_id":sid,"fabrication_approved":False})
        if (counts.get("Connection Error",999)>=149 or counts.get("Netlist Error",999)>1 or
            any(v for k,v in counts.items() if k not in ("Connection Error","Netlist Error"))):
            raise RuntimeError("New primary copper failed real native DRC. Do not save or repeat.")
        saved=required(invoke(sid,"return await eda.pcb_Document.save();",30000),"V12 native save")
        if saved is not True:raise RuntimeError("V12 native save did not acknowledge true")
        time.sleep(27)
        after=required(D.call([str(D.LEDA),"session","list"],timeout_s=22),"GUI after")
        now={x["sessionId"] for x in after if x.get("status")=="alive" and x.get("headless") is False}
        if sha(TARGET)==SOURCE_SHA or sha(SOURCE)!=SOURCE_SHA or not users.issubset(now):
            raise RuntimeError("Native V12 save absent or previous user GUI/source changed")
        print(json.dumps({"status":"REAL_NATIVE_V12_TWO_PRIMARY_LINKS_SAVED_NOT_FOR_FAB",
            "candidate_sha256":sha(TARGET),"source_V11_sha256":SOURCE_SHA,
            "native_DRC":counts,"line_count_runtime":wrote["new_line_count"],
            "native_gui_session_id":sid,"original_user_GUIs_preserved":True,
            "fabrication_approved":False},ensure_ascii=False,indent=2))
        return 0
    except Exception as e:
        print(json.dumps({"status":"NATIVE_V12_NOT_VERIFIED_NOT_FOR_FAB",
            "error":str(e),"own_GUI_kept_if_alive":sid,"no_blind_retry":True}))
        return 1


def main():
    p=argparse.ArgumentParser()
    z=p.add_mutually_exclusive_group(required=True)
    z.add_argument("--plan",action="store_true")
    z.add_argument("--apply",action="store_true")
    a=p.parse_args()
    if a.plan:
        d=plan()
        body=json.dumps(d,ensure_ascii=False,indent=2)+"\n"
        if PLAN.exists() and PLAN.read_text("utf8")!=body:
            raise ValueError("Do not rewrite old V12 plan")
        if not PLAN.exists():PLAN.write_text(body,encoding="utf8",newline="\n")
        print(json.dumps({"source":SOURCE_SHA,"routes":d["new_top_primary_net_tracks"],
          "islands_before":d["source_native_islands"],
          "islands_after":d["proposed_native_islands"],
          "physical_issues":d["physical_preflight_issues"],"fabrication_approved":False},
          ensure_ascii=False,indent=2))
        return 0
    return apply()
if __name__=="__main__":
    raise SystemExit(main())

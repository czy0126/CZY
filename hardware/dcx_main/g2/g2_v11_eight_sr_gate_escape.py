"""Real EasyEDA V11: reroute eight SR PGND drops to clear GA/GB escape.

Source = SHA-frozen SAVED, independently reopened V10. No editing V9/V10.
One-shot own V11 visible GUI. Every net is named from native pad readback.
Local top-copper geometry checked against real pads/tracks/vias and new copper.
PCB is a research candidate ONLY, still NOT_FOR_FAB due magnetics/100A/D0.

python hardware/dcx_main/g2/g2_v11_eight_sr_gate_escape.py --plan
python hardware/dcx_main/g2/g2_v11_eight_sr_gate_escape.py --apply
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

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"hardware/dcx_main/g1"),str(HERE)]
import g2_board_keepout as K
import g2_oem_net_islands as IS
import route_driver_eco as GEOM
import g2_v9_real_t530_components as V9

SOURCE=HERE/"dcx_main_board_g2_V10_NATIVE_SR_POWER_STRAPS_NOT_FOR_FAB.eprj2"
SOURCE_SHA="8dede88bf7b3cea52ff6f752b6ca573f7a3b9e7c7a3f665ca071dae8376f8c0c"
NATIVE=HERE/"g2_v10_native_power_straps_live_readback_NOT_FOR_FAB.json"
REOPEN=HERE/"g2_v10_independent_native_reopen_v2_verified_NOT_FOR_FAB.json"
TARGET=HERE/"dcx_main_board_g2_V11_NATIVE_SR_GATE_ESCAPE_NOT_FOR_FAB.eprj2"
PLAN=HERE/"g2_v11_eight_sr_gate_escape_plan_NOT_FOR_FAB.json"
ATTEMPT=HERE/"g2_v11_native_gate_escape_attempt_NOT_FOR_FAB.json"
APPLIED=HERE/"g2_v11_native_gate_escape_applied_NOT_FOR_FAB.json"
M=.0254
CLEAR_MM=.18
SIGNAL_WIDTH_MM=.15
GROUND_WIDTH_MM=1.
CROSS_Y_MM=83.89
EXPECTED={"components":149,"pads":443,"lines":435,"vias":93,"nets":65}


def sha(p:Path)->str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def once(p:Path,v:dict)->None:
    if p.exists():raise FileExistsError(f"Do not overwrite an earlier live native attempt: {p}")
    p.write_text(json.dumps(v,indent=2,ensure_ascii=False)+"\n",encoding="utf8",newline="\n")


def frozen():
    if sha(SOURCE)!=SOURCE_SHA:
        raise ValueError("Original separately validated V10 native source SHA drift")
    n=json.loads(NATIVE.read_text("utf8"))
    a=json.loads(REOPEN.read_text("utf8"))
    if n.get("candidate_sha256")!=SOURCE_SHA or n.get("status")!="ACTUAL_SAVED_V10_NATIVE_PCB_READBACK_NOT_FOR_FAB":
        raise ValueError("V10 real native pad/line readback not source bound")
    if (a.get("candidate_sha256")!=SOURCE_SHA or
        a.get("status")!="INDEPENDENT_V10_NATIVE_REOPEN_WITH_DRC_PASSED_NOT_FOR_FAB" or
        a.get("native_drc")!={"Connection Error":165,"Netlist Error":1} or
        not a.get("candidate_file_unchanged") or
        not a.get("original_gui_sessions_all_preserved")):
        raise ValueError("V10 separate independent GUI reopen not proven")
    native=n["native_readback"]
    if {k:len(native[k]) for k in EXPECTED}!=EXPECTED:
        raise ValueError("V10 native PCB element counts drift")
    return native


def pxy(p):
    return [round(p["X"]*M,5),round(-p["Y"]*M,5)]


def eligible_pads(native,ref,pin,net):
    items=[p for p in native["pads"] if p.get("ref")==ref
           and str(p.get("PadNumber"))==str(pin) and p["Net"]==net]
    if len(items)!=1 or int(items[0]["Layer"])!=1:
        raise ValueError("Native top pad missing/ambiguous "+f"{ref}.{pin}/{net}")
    return items[0]


def plan():
    native=frozen()
    remove=[];replace=[];escape=[]
    for i in range(1,5):
        for side in "AB":
            sr=f"SR{i}{side}"
            ref=f"R{18+i*2}" if side=="A" else f"R{19+i*2}"
            net=f"G{side}{i}"
            a=eligible_pads(native,ref,"2",net)
            b=eligible_pads(native,sr,"4",net)
            x,y=pxy(a);x2,y2=pxy(b)
            if not (4.5<math.dist((x,y),(x2,y2))<6.2 and abs(y2-84.82)<.01):
                raise ValueError("SR gate resistor geometry drift "+net)
            old=[l for l in native["lines"] if l["net"]=="PGND"
                 and int(l["layer"])==1
                 and abs(l["width"]*M-GROUND_WIDTH_MM)<.01
                 and abs(l["x1"]*M-(x2-2.504))<.08
                 and abs(l["x1"]-l["x2"])<.01
                 and abs(-l["y1"]*M-84.47)<.01
                 and abs(-l["y2"]*M-94)<.01]
            if len(old)!=1:
                raise ValueError("No one-to-one real old SR PGND vertical drop for "+net)
            line=old[0]
            remove.append(line["id"])
            nx=round(line["x1"]*M-.5,5)
            # Terminate inside actual native PGND rect pad2 (not an imagined land).
            ground_pads=[p for p in native["pads"] if p.get("ref")==sr
                         and str(p.get("PadNumber"))=="2" and p["Net"]=="PGND"]
            if len(ground_pads)!=1:
                raise ValueError("Cannot anchor relocated PGND to native source "+sr)
            if K.distance_to_box((nx,85.1),K.pad_bbox(ground_pads[0]))>=GROUND_WIDTH_MM/2-.20:
                raise ValueError("Relocated PGND drop lacks overlap with real source pad")
            replace.append({"ref":sr,"for_gate_net":net,"old_id":line["id"],
                     "new_net":"PGND","layer":1,
                     "old_start_xy_mm":[round(line["x1"]*M,5),round(-line["y1"]*M,5)],
                     "new_start_xy_mm":[nx,85.1],
                     "new_end_xy_mm":[nx,94.],
                     "width_mm":GROUND_WIDTH_MM})
            points=[[x,y],[x,CROSS_Y_MM],[x2,CROSS_Y_MM],[x2,y2]]
            for k,(start,end) in enumerate(zip(points,points[1:]),1):
                escape.append({"ref":sr,"gate_net":net,"segment":k,
                    "net":net,"layer":1,"a_mm":start,"b_mm":end,"width_mm":SIGNAL_WIDTH_MM})
    if len(remove)!=8 or len(set(remove))!=8 or len(replace)!=8 or len(escape)!=24:
        raise ValueError("Expected exactly 8 replaced grounded drops and 24 gate escapes")
    final_lines=[l for l in native["lines"] if l["id"] not in remove]
    all_new=[{"ref":x["ref"],"net":"PGND","layer":1,
              "a_mm":x["new_start_xy_mm"],"b_mm":x["new_end_xy_mm"],
              "width_mm":x["width_mm"]} for x in replace]+escape
    conflicts=[]
    for i,s in enumerate(all_new):
        a,b=s["a_mm"],s["b_mm"];req=s["width_mm"]/2+CLEAR_MM
        for p in native["pads"]:
            if p["Net"]==s["net"] or int(p["Layer"]) not in (0,1,11,12):continue
            dist=GEOM._segment_rect(a,b,K.pad_bbox(p))
            if dist+1e-6<req:
                conflicts.append([i,"pad",(p.get("ref") or "RAW")+"."+str(p["PadNumber"]),p["Net"],round(dist-req,5)])
        for line in final_lines:
            if line["net"]==s["net"] or int(line["layer"])!=1:continue
            c=(line["x1"]*M,-line["y1"]*M);d=(line["x2"]*M,-line["y2"]*M)
            gap=GEOM._segment_segment(a,b,c,d)-req-line["width"]*M/2
            if gap<-.0001:conflicts.append([i,"line",line["id"],line["net"],round(gap,5)])
        for via in native["vias"]:
            if via["net"]==s["net"]:continue
            c=(via["x"]*M,-via["y"]*M)
            gap=K.segment_distance(c,a,b)-req-via["diameter"]*M/2
            if gap<-.0001:conflicts.append([i,"via",via["id"],via["net"],round(gap,5)])
        for j,t in enumerate(all_new[:i]):
            if t["net"]==s["net"]:continue
            gap=GEOM._segment_segment(a,b,t["a_mm"],t["b_mm"])-req-t["width_mm"]/2
            if gap<-.0001:conflicts.append([i,"new_line",j,t["net"],round(gap,5)])
        for pt in (a,b):
            if not (2<=pt[0]<=153 and 2<=pt[1]<=129):
                conflicts.append([i,"edge",pt,"board",0])
    if conflicts:
        raise ValueError("Cannot apply power-ground reroute; unlike-net copper conflicts "+str(conflicts[:8]))

    # These 32 2D lines are only a proposed native PCB ECO until the editor
    # creates them and native DRC confirms no additional physical errors.
    simulated=dict(native)
    simulated["lines"]=final_lines+[{
       "id":f"V11_SIMULATED_{j:02d}","net":s["net"],"layer":s["layer"],
       "x1":s["a_mm"][0]/M,"y1":-s["a_mm"][1]/M,
       "x2":s["b_mm"][0]/M,"y2":-s["b_mm"][1]/M,
       "width":s["width_mm"]/M} for j,s in enumerate(all_new)]
    before=IS.islands(native,{"PGND"}|{f"G{x}{i}" for x in "AB" for i in range(1,5)})
    after=IS.islands(simulated,{"PGND"}|{f"G{x}{i}" for x in "AB" for i in range(1,5)})
    before_counts={k:v["island_count_geometry_screen"] for k,v in before.items()}
    after_counts={k:v["island_count_geometry_screen"] for k,v in after.items()}
    # An edited ground spine must never disconnect a power pin.
    if after_counts["PGND"]>before_counts["PGND"]:
        raise ValueError("Ground power island count worsened")
    if not all(before_counts[n]==2 and after_counts[n]==1 for n in
               (f"G{x}{i}" for x in "AB" for i in range(1,5))):
        raise ValueError("Eight gate networks did not truly join their isolated pads")
    return {
       "schema":"G2_V11_NATIVE_EIGHT_SR_GATE_ESCAPE_AND_GROUND_SPINE_PLAN_V1",
       "source_V10_native_sha256":SOURCE_SHA,
       "source_V10_native_counts":EXPECTED,
       "source_V10_native_DRC":{"Connection Error":165,"Netlist Error":1},
       "geometry_screen_clearance_mm":CLEAR_MM,
       "gate_trace_width_mm":SIGNAL_WIDTH_MM,
       "ground_spine_width_mm":GROUND_WIDTH_MM,
       "real_old_ground_spine_to_delete_ids":remove,
       "relocated_ground_spines":replace,
       "gate_escape_traces":escape,
       "native_new_lines":all_new,
       "geometric_issues":conflicts,
       "before_real_native_islands":before_counts,
       "after_simulated_islands":after_counts,
       "preserves_original_V9_V10_and_all_GUI_sessions":True,
       "released_for_100A":False,
       "vendor_magnetics_footprint_signed":False,
       "fabrication_approved":False
    }


def js_apply(pcb_uuid,proposal):
    wires=[[s["net"],s["layer"],s["a_mm"][0]/M,-s["a_mm"][1]/M,
            s["b_mm"][0]/M,-s["b_mm"][1]/M,s["width_mm"]/M] for s in proposal["native_new_lines"]]
    return """return await(async()=>{
      const p=await eda.dmt_Project.getCurrentProjectInfo();
      if(p?.friendlyName!==%s)throw Error("Wrong V11 native GUI");
      await eda.dmt_EditorControl.openDocument(%s);
      const c=await eda.pcb_PrimitiveComponent.getAll();
      const pads=await eda.pcb_PrimitivePad.getAll();
      const vias=await eda.pcb_PrimitiveVia.getAll();
      const old=await eda.pcb_PrimitiveLine.getAll();
      if(c.length!==149||pads.length!==443||vias.length!==93||old.length!==435)
         throw Error("V10 native base geometry drift");
      const remove=%s, set=new Set(old.map(x=>x.getState_PrimitiveId()));
      if(remove.length!==8||new Set(remove).size!==8||remove.some(x=>!set.has(x)))
         throw Error("Real native source 8 PGND tracks do not match source");
      const del=await eda.pcb_PrimitiveLine.delete(remove);
      if(del!==true)throw Error("Native PGND spine delete refused");
      const requests=%s, wrote=[];
      for(const r of requests){
        try{
          const x=await eda.pcb_PrimitiveLine.create(r[0],r[1],r[2],r[3],r[4],r[5],r[6],false);
          if(!x)throw Error("native line creation null");
          wrote.push({ok:true,id:x.getState_PrimitiveId()});
        }catch(e){wrote.push({ok:false,error:String(e)});break;}
      }
      return {deleted:true,deleted_ids:remove,requests:requests.length,
         wrote,all_added:wrote.length===requests.length&&wrote.every(x=>x.ok),
         new_lines:(await eda.pcb_PrimitiveLine.getAll()).length,
         components:c.length,pads:pads.length,vias:vias.length};
    })();"""%(json.dumps(TARGET.stem),json.dumps(pcb_uuid),
                 json.dumps(proposal["real_old_ground_spine_to_delete_ids"]),
                 json.dumps(wires,separators=(",",":")))


def invoke(sid,code,timeout=59000):
    return V9.D.call(V9.D.build_invoke_args(sid,code,timeout),timeout_s=75)


def need(r,description):
    if r.get("ok") is not True:
        raise RuntimeError(f"{description}: {r.get('error')}")
    return r["value"]


def apply():
    if any(p.exists() for p in (ATTEMPT,APPLIED,TARGET)):
        raise FileExistsError("Original one-shot V11 already attempted; do not repeat unknown PCB mutation")
    proposal=plan()
    if not PLAN.is_file() or json.loads(PLAN.read_text("utf8"))!=proposal:
        raise ValueError("V11 source-locked preflight plan missing or stale")
    shutil.copyfile(SOURCE,TARGET)
    if sha(TARGET)!=SOURCE_SHA:raise IOError("V10->V11 binary clone not exact")
    before=need(V9.D.call([str(V9.D.LEDA),"session","list"],timeout_s=20),"GUI inventory before")
    original={x["sessionId"] for x in before if x.get("status")=="alive" and x.get("headless") is False}
    once(ATTEMPT,{"source_V10_sha256":SOURCE_SHA,"V11_binary_original_sha256":sha(TARGET),
           "visible_GUIs_to_preserve":sorted(original),"new_lines_to_apply":32,
           "old_PGND_lines_to_remove":8,"never_retry_unconfirmed_native_calls":True,
           "fabrication_approved":False})
    sid=None
    try:
        args=V9.D.build_open_args(TARGET)
        if args[-2:]!=["--headless","true"]:
            raise RuntimeError("Unexpected GUI opening protocol")
        args[-1]="false"
        opened=need(V9.D.call(args,timeout_s=135),"V11 GUI open")
        sid=opened["sessionId"]
        time.sleep(V9.D.SETTLE_S+3)
        need(V9.D.call(V9.D.build_ping_args(sid),timeout_s=22),"V11 renderer ready")
        info=need(invoke(sid,"return await(async()=>{let p=await eda.dmt_Project.getCurrentProjectInfo();return{name:p?.friendlyName,pcb:p?.data?.find(x=>x?.pcb?.uuid)?.pcb?.uuid};})();",17000),"V11 project")
        if info["name"]!=TARGET.stem or not info["pcb"]:
            raise RuntimeError("V11 project identity mismatch; refuse edit")
        result=need(invoke(sid,js_apply(info["pcb"],proposal)),"V11 PGND/gate native edit")
        once(APPLIED,{"session_id":sid,"source_V10_sha256":SOURCE_SHA,
                      "edit_receipt":result,"fabrication_approved":False})
        # Native editor automatically splits 9 old PGND bus segments into 15
        # at eight relocated spine contacts: 435 - 8 - 9 + 15 + 32 = 465.
        # Exact native IDs and true islands require independent verification.
        if not (result["deleted"] and result["all_added"] and result["new_lines"]==465):
            raise RuntimeError("Native V11 edit incomplete. Preserve GUI state; no blind retries.")
        saved=need(invoke(sid,"return await eda.pcb_Document.save();",30000),"V11 save")
        if saved is not True:raise RuntimeError("Native V11 saved without true acknowledgement")
        time.sleep(27)
        if sha(TARGET)==SOURCE_SHA or sha(SOURCE)!=SOURCE_SHA:
            raise RuntimeError("Native disk save not persisted or V10 parent changed")
        after=need(V9.D.call([str(V9.D.LEDA),"session","list"],timeout_s=22),"GUI inventory after")
        alive={x["sessionId"] for x in after if x.get("status")=="alive" and x.get("headless") is False}
        if not original.issubset(alive):
            raise RuntimeError("Original user EDA sessions unexpectedly affected")
        print(json.dumps({"status":"V11_NATIVE_EIGHT_SR_GATES_SAVED_NOT_FOR_FAB",
               "native_sha256":sha(TARGET),"source_sha256":SOURCE_SHA,
               "native_line_count":465,"native_gui_session":sid,
               "existing_user_gui_preserved":True,"fabrication_approved":False},
               ensure_ascii=False,indent=2))
        return 0
    except Exception as e:
        print(json.dumps({"status":"V11_NATIVE_ECO_NOT_VERIFIED_NOT_FOR_FAB",
              "error":str(e),"own_GUI_kept_if_open":sid,"no_retry":True},ensure_ascii=False))
        return 1


def main():
    p=argparse.ArgumentParser()
    x=p.add_mutually_exclusive_group(required=True)
    x.add_argument("--plan",action="store_true")
    x.add_argument("--apply",action="store_true")
    a=p.parse_args()
    if a.plan:
        doc=plan()
        payload=json.dumps(doc,indent=2,ensure_ascii=False)+"\n"
        if PLAN.exists() and PLAN.read_text("utf8")!=payload:
            raise ValueError("Existing V11 preflight is stale; don't overwrite")
        if not PLAN.exists():PLAN.write_text(payload,encoding="utf8",newline="\n")
        print(json.dumps({"removed":len(doc["real_old_ground_spine_to_delete_ids"]),
           "added":len(doc["native_new_lines"]),"issues":len(doc["geometric_issues"]),
           "islands_before":doc["before_real_native_islands"],
           "islands_after":doc["after_simulated_islands"],
           "fabrication_approved":False},ensure_ascii=False,indent=2))
        return 0
    return apply()
if __name__=="__main__":
    raise SystemExit(main())

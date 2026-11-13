"""One small *real* EasyEDA V14 PCB DRC repair: isolated OC comparator signal.

OC R17.1 -> C12.1 are disconnected in 149/1 native DRC. Use a short
bottom-layer route with TWO standard-through 0.4/0.8mm plated vias and
two top-layer stubs. Never fake connection by changing net labels. Derive
component pad centres from 423-pad live native V14 readback. Clearance
preflight includes unlike-net top/bottom pads/tracks and all 90 vias.
Single actual GUI V13 source, target SECOND PCB 8c496410b2877d3c only.
Re-run native DRC before saving; rollback unless improves and Physical==0.

  python tools/g2_v14_fix_OC_short_via.py --plan
  python tools/g2_v14_fix_OC_short_via.py --apply
"""
from __future__ import annotations
import argparse,hashlib,json,sys,shutil,math
from pathlib import Path
from shapely.geometry import Point,LineString,box
ROOT=Path(__file__).resolve().parents[1]
G=ROOT/"hardware/dcx_main/g2"
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"hardware/dcx_main/g1"),str(G)]
from g2_board_keepout import pad_bbox
import g2_v9_real_t530_components as V9

ORIG=G/"dcx_main_board_g2_V13_FIVE_MAGNETICS_LOGICAL_LANDING_TRIAL_NOT_FOR_FAB.eprj2"
SNAP=G/"dcx_main_board_g2_V14_EILP32_TWELVE_NPTH_12L_STACK_WIP_NOT_FOR_FAB.eprj2"
BASE=G/"g2_v14_real_native_12slot_routing_baseline_readback_NOT_FOR_FAB.json"
BEFORE=G/"g2_v14_native_PCB_after_12slots_real_DRC_raw_NOT_FOR_FAB.json"
SESSION=G/"g2_v13_GUI_open_unique_attempt_NOT_FOR_FAB.json"
PLAN=G/"g2_v14_OC_isolated_signal_two_via_clearance_plan_NOT_FOR_FAB.json"
RESULT=G/"g2_v14_OC_native_real_DRC_fix_attempt_NOT_FOR_FAB.json"
NEW=G/"dcx_main_board_g2_V14_EILP32_TWELVE_NPTH_OC_FIX_WIP_NOT_FOR_FAB.eprj2"
SAVED=G/"g2_v14_OC_native_PCB_saved_snapshot_NOT_FOR_FAB.json"
SHA="1e76e6865a746a49bea8a9fb87037b0301213faa386f5fdd2d6bdf5550ffbac6"
PCB="8c496410b2877d3c"
PROJECT="dcx_main_board_g2_V13_FIVE_MAGNETICS_LOGICAL_LANDING_TRIAL_NOT_FOR_FAB"
MM=.0254
NET="OC"
WIDTH=.2
HOLE=.4
DIA=.8
CLEARANCE=.2

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def write_once(p,o):
    if p.exists():raise FileExistsError("One-shot operation already recorded: "+str(p))
    p.write_text(json.dumps(o,ensure_ascii=False,indent=2)+"\n",encoding="utf8",newline="\n")

def getplan():
    if sha(SNAP)!=SHA:raise ValueError("Native source immutable V14 DRC baseline changed")
    data=json.loads(BASE.read_text("utf8"))
    if data["board_uuid"]!=PCB:raise ValueError("Wrong saved native PCB")
    n=data["real_native_data"]
    if [len(n[k]) for k in ("components","pads","lines","vias")]!=[149,423,458,90]:
        raise ValueError("V14 12-slot saved copper counts drifted")
    drc=json.loads(BEFORE.read_text("utf8"))
    if drc["categories"]!={"Connection Error":149,"Netlist Error":1}:
        raise ValueError("Baseline native DRC changed")
    def pad(ref,num):
        rows=[q for q in n["pads"] if q["ref"]==ref and q["PadNumber"]==num and q["Net"]==NET and q["Layer"]==1]
        if len(rows)!=1:raise ValueError("One net-matching native pin required "+ref+"."+num)
        q=rows[0];return (round(q["X"]*MM,5),round(-q["Y"]*MM,5))
    a=pad("R17","1");b=pad("C12","1")
    if math.dist(a,b)>9:raise ValueError("Unexpected IC comparator OC length")
    va=(a[0],64.0);vb=(b[0],64.0)
    if math.dist(a,va)>2.5 or math.dist(b,vb)>2.5:raise ValueError("Too long OC via escape")
    routes=[{"layer":1,"from":a,"to":va},
            {"layer":2,"from":va,"to":vb},
            {"layer":1,"from":vb,"to":b}]
    vias=[va,vb]
    # Metal shapes support rotated pads plus all 458 actual native line widths,
    # against both top/bottom and all PTH pads.
    for segment in routes:
        copper=LineString([segment["from"],segment["to"]]).buffer(WIDTH/2,cap_style=2)
        layer=segment["layer"]
        for q in n["pads"]:
            if q["Net"]==NET or q["Layer"] not in (0,12,layer):continue
            if copper.distance(box(*pad_bbox(q)))<CLEARANCE-1e-7:
                raise ValueError("OC route violates pad "+str(q.get("ref"))+"."+str(q["PadNumber"]))
        for q in n["lines"]:
            if q["net"]==NET or q["layer"]!=layer:continue
            t=LineString([(q["x1"]*MM,-q["y1"]*MM),(q["x2"]*MM,-q["y2"]*MM)]).buffer(q["width"]*MM/2)
            if copper.distance(t)<CLEARANCE-1e-7:raise ValueError("OC route violates trace "+q["net"])
        for q in n["vias"]:
            if q["net"]==NET:continue
            t=Point(q["x"]*MM,-q["y"]*MM).buffer(q["diameter"]*MM/2)
            if copper.distance(t)<CLEARANCE-1e-7:raise ValueError("OC route violates via "+q["net"])
    for x,y in vias:
        via=Point(x,y).buffer(DIA/2)
        for q in n["pads"]:
            if q["Net"]==NET:continue
            if via.distance(box(*pad_bbox(q)))<CLEARANCE-1e-7:
                raise ValueError("OC via violates pad "+str(q["Net"]))
        for q in n["lines"]:
            if q["net"]==NET:continue
            trace=LineString([(q["x1"]*MM,-q["y1"]*MM),(q["x2"]*MM,-q["y2"]*MM)]).buffer(q["width"]*MM/2)
            if via.distance(trace)<CLEARANCE-1e-7:
                raise ValueError("OC via violates trace "+q["net"])
        for q in n["vias"]:
            if q["net"]==NET:continue
            actual=Point(q["x"]*MM,-q["y"]*MM).buffer(q["diameter"]*MM/2)
            if via.distance(actual)<CLEARANCE-1e-7:
                raise ValueError("OC via violates existing via "+q["net"])
    return {
      "schema":"D1_V14_OC_REAL_NATIVE_TWO_PTH_AND_THREE_SHORT_SEGMENTS_V1",
      "status":"OC_SIGNAL_TWO_VIA_NATIVE_TRACE_PRECHECK_PASS_NOT_YET_DRAWN",
      "base_native_V14_file_sha256":SHA,
      "native_423pad_readback_sha256":sha(BASE),
      "native_149_1_DRC_readback_sha256":sha(BEFORE),
      "PCB_copy_target_uuid":PCB,"source_original_PCB_untouched":True,
      "net":NET,"pin_endpoints":{"R17.1":a,"C12.1":b},
      "via_diameter_mm":DIA,"via_hole_mm":HOLE,"width_mm":WIDTH,
      "minimum_unlike_net_clearance_mm":CLEARANCE,
      "via_positions_mm":vias,"new_native_segments":routes,
      "uses_actual_top_and_bottom_layers_only":True,
      "native_DRC_must_decrease_without_any_physical_error":True,
      "not_manufacturer_approved":True,"fabrication_approved":False
    }

def apply():
    if RESULT.exists() or SAVED.exists():
        raise FileExistsError("A prior OC repair exists; inspect before any reapply")
    doc=getplan()
    if not PLAN.exists() or json.loads(PLAN.read_text("utf8"))!=json.loads(json.dumps(doc)):
        raise ValueError("OC 149/1 native source plan missing or drifted")
    sid=json.loads(SESSION.read_text("utf8"))["new_session"]
    session=V9.D.call([str(V9.D.LEDA),"session","list"],timeout_s=21)
    if not session.get("ok") or not any(x["sessionId"]==sid and x["status"]=="alive" and x["headless"]==False for x in session["value"]):
        raise RuntimeError("Current original GUI not alive, DO NOT START ANOTHER WINDOW")
    # Create two standard through PTHs, three real copper primitives.
    # Native DRC before and after, stop if new Physical or no Connection decrease.
    js="""return await(async()=>{
      const project=await eda.dmt_Project.getCurrentProjectInfo();
      if(project?.friendlyName!==%s)throw Error('Wrong project');
      await eda.dmt_EditorControl.openDocument(%s);
      const before={pads:(await eda.pcb_PrimitivePad.getAll()).length,
        lines:(await eda.pcb_PrimitiveLine.getAll()).length,
        vias:(await eda.pcb_PrimitiveVia.getAll()).length,
        parts:(await eda.pcb_PrimitiveComponent.getAll()).length};
      if(JSON.stringify(before)!==JSON.stringify({pads:423,lines:458,vias:90,parts:149}))
        throw Error('Do not alter stale PCB: '+JSON.stringify(before));
      const layers=(await eda.pcb_Layer.getAllLayers()).filter(x=>x.type==='SIGNAL'&&x.layerStatus===1);
      if(layers.length!==12)throw Error('12-copper layer V14 not selected');
      const plan=%s;
      const newVia=[],newLines=[];
      const stat=(raw)=>{
        const out={};for(const g of raw){out[g.name]=g.list.reduce((s,i)=>s+(i.list?.length||0),0);}return out;
      };
      try{
        for(const [x,y] of plan.via_positions_mm){
          const q=await eda.pcb_PrimitiveVia.create(plan.net,x/0.0254,-y/0.0254,
              plan.via_hole_mm/0.0254,plan.via_diameter_mm/0.0254);
          if(!q)throw Error('Real PCB via.create returned undefined');
          newVia.push(q.getState_PrimitiveId());
        }
        for(const s of plan.new_native_segments){
          const a=s.from,b=s.to;
          const q=await eda.pcb_PrimitiveLine.create(plan.net,s.layer,a[0]/0.0254,-a[1]/0.0254,
               b[0]/0.0254,-b[1]/0.0254,plan.width_mm/0.0254,false);
          if(!q)throw Error('Real PCB PrimitiveLine.create returned undefined');
          newLines.push(q.getState_PrimitiveId());
        }
        const result=await eda.pcb_Drc.check(true,false,true);
        const categories=stat(result);
        const good=((categories['Connection Error']||0)<=148 &&
                    (categories['Netlist Error']||0)<=1 &&
                    (categories['Physical Error']||0)===0);
        if(!good){
          const delLine=await eda.pcb_PrimitiveLine.delete(newLines);
          const delVia=await eda.pcb_PrimitiveVia.delete(newVia);
          return {status:'REVERTED_NO_NATIVE_DRC_IMPROVEMENT',
                  categories,delLine,delVia,newVia,newLines,
                  saved:false};
        }
        const saved=await eda.pcb_Document.save();
        if(saved!==true)throw Error('Native PCB save not confirmed');
        return {status:'REAL_NATIVE_OC_CONNECTED_DRC_IMPROVED_NOT_FOR_FAB',
                categories,newVia,newLines,saved,
                current_lines:(await eda.pcb_PrimitiveLine.getAll()).length,
                current_vias:(await eda.pcb_PrimitiveVia.getAll()).length};
      }catch(e){
        try{
          if(newLines.length)await eda.pcb_PrimitiveLine.delete(newLines);
          if(newVia.length)await eda.pcb_PrimitiveVia.delete(newVia);
        }catch(r){return {status:'ROLLBACK_ERROR_UNVERIFIED',error:String(e),rollbackError:String(r)}}
        return {status:'REVERTED_NATIVE_EXCEPTION',error:String(e),saved:false};
      }
    })();"""%(json.dumps(PROJECT),json.dumps(PCB),json.dumps(doc,ensure_ascii=False,separators=(",",":")))
    r=V9.D.call(V9.D.build_invoke_args(sid,js,59000),timeout_s=80)
    result=r.get("value") or {}
    good=r.get("ok") and result.get("status")=="REAL_NATIVE_OC_CONNECTED_DRC_IMPROVED_NOT_FOR_FAB"
    write_once(RESULT,{"status":"NATIVE_OC_SIGNAL_REPAIRED_AND_DRC_IMPROVED_NOT_FOR_FAB" if good else "OC_SIGNAL_REPAIRED_NOT_VERIFIED_ROLLED_BACK_OR_STOPPED",
       "api":r,"source_SHA256":SHA,"fabrication_approved":False})
    print(json.dumps({"result":result,"api_error":r.get("error"),"approved":False},ensure_ascii=False,indent=2)[:5000])
    if not good:raise RuntimeError("OC net wiring not accepted; original V14 still preserved")
    if NEW.exists() or SAVED.exists():raise FileExistsError("Do not overwrite accepted OC PCB")
    shutil.copy2(ORIG,NEW)
    write_once(SAVED,{"status":"V14_NATIVE_OC_REPAIRED_SAVED_SNAPSHOT_NOT_FOR_FAB",
       "source_file":NEW.name,"sha256":sha(NEW),
       "current_visible_GUI_session_preserved":True,
       "native_source_no_new_window":True,
       "DRC":result["categories"],"fabrication_approved":False})

def main():
    p=argparse.ArgumentParser()
    t=p.add_mutually_exclusive_group(required=True)
    t.add_argument("--plan",action="store_true")
    t.add_argument("--apply",action="store_true")
    a=p.parse_args()
    if a.plan:
        obj=getplan()
        if PLAN.exists() and json.loads(PLAN.read_text("utf8"))!=obj:
            raise ValueError("Existing OC source-bound route plan changed")
        if not PLAN.exists():write_once(PLAN,obj)
        print(json.dumps({"status":obj["status"],"net":obj["net"],
          "new_copper":len(obj["new_native_segments"]),
          "new_vias":len(obj["via_positions_mm"]),"source_SHA256":SHA}))
    else:apply()
if __name__=="__main__":
    main()

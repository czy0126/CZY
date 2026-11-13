"""V18 EasyEDA *native* T1 SR power-cell and Lr magnetic-core site swap.

Same visible GUI. Never recreate components or change netnames. Source:
V18 after accepted Cin-QH-QL complete top/bottom power loop, DRC 102.
The T1 block of 9 devices + 20 real traces + 2 real PTHs translates
-30mm, Lr inductor moves +30mm into the vacated T1 SR corridor. The
full ELP38 mechanical body at its new position has no stationary PCB pads.

Three stages allow safe recovery if EasyEDA API script times out:
  --components   (10 original native devices)
  --copper       (20 tracks and 2 vias)
  --validate     (native readback + independent DRC + save)

Pre-existing original PCB1, V14, V15 and V17 are never overwritten.
This is NOT a route-complete, EMC-approved or factory-signed 100A PCB.
"""
from __future__ import annotations
import argparse,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
G=ROOT/"hardware/dcx_main/g2"
sys.path[:0]=[str(G),str(ROOT/"hardware/dcx_main/g1")]
import g2_v9_real_t530_components as V9
SESSION_ID="34593c1e-ac5b-47df-b71f-e6c8387a76be"
PCB_UUID="9b212da9a255a2af"
PROJECT_PREFIX="V18_REAL_POWER_UNIT_RELAYOUT_WORKING"
INPUT=G/"g2_v18_actual_native_before_powercell_layout_149parts_READONLY_NOT_FOR_FAB.json"
CIN=G/"g2_v18_Cin_6tracks_2vias_102DRC_saved_provenance_NOT_FOR_FAB.json"
SAVED=G/"dcx_main_board_g2_V18_REAL_POWER_UNIT_RELAYOUT_WORKING_NOT_FOR_FAB.eprj2"
SOURCE_SHA="2a3aa08510cd1b6b354b6b70ae7deb5217dfcdda5eee1c9b0defb996b6b62466"
R1=G/"g2_v18_T1_Lr_10native_components_RELOCATED_ONCE_NOT_FOR_FAB.json"
R2=G/"g2_v18_T1_Lr_20tracks_2vias_NATIVE_MOVE_ONCE_NOT_FOR_FAB.json"
R3=G/"g2_v18_T1_Lr_swap_actual_native_DRC_AND_SAVE_NOT_FOR_FAB.json"
PLAN=G/"g2_v18_T1_Lr_swap_30mm_native_source_plan_NOT_FOR_FAB.json"
REFS=("C105","C7","R20","R21","R28","R29","SR1A","SR1B","U3")
ALLREFS=(*REFS,"Lr")
LOCALNETS={"SEC1_A","SEC1_B","GA1","GB1","VD1_A","REG1","PGND","VCC12_S"}
M=.0254

def load(p):return json.loads(p.read_text("utf8"))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def plan():
    b=load(INPUT)["native"]
    assert tuple(len(b[k]) for k in ("components","pads","lines","vias"))==(149,423,502,104)
    if load(CIN)["native_DRC"]!={"Connection Error":102}:raise ValueError("Must begin from saved real Cin loop")
    comp={q["ref"]:q for q in b["components"]}
    group={r:{"x":comp[r]["X"],"y":comp[r]["Y"],
               "rotation":comp[r]["Rotation"],"dy_mm":30 if r=="Lr" else -30}
           for r in ALLREFS}
    lines=[q for q in b["lines"]
           if 5<min(q["x1"],q["x2"])*M and max(q["x1"],q["x2"])*M<35
           and 64<min(-q["y1"]*M,-q["y2"]*M) and max(-q["y1"]*M,-q["y2"]*M)<92
           and q["net"] in LOCALNETS]
    vias=[q for q in b["vias"] if q["net"] in ("REG1","PGND")
          and 10<q["x"]*M<30 and 74<-q["y"]*M<78]
    if len(lines)!=20 or len(vias)!=2:
        raise ValueError(f"Real T1 local copper selection drift {len(lines)} tracks/{len(vias)} vias")
    return {"schema":"D1_NATIVE_V18_T1_ELP38_LR_REAL_RELAYOUT_10DEVICE_20TRACK_2PTH",
       "source_after_Cin_SHA256":SOURCE_SHA,"board_uuid":PCB_UUID,
       "components":group,
       "lines":[{"id":q["id"],"net":q["net"],"layer":q["layer"],
                  "x1":q["x1"],"y1":q["y1"],"x2":q["x2"],"y2":q["y2"]} for q in lines],
       "vias":[{"id":q["id"],"net":q["net"],"x":q["x"],"y":q["y"]} for q in vias],
       "T1_core_center_mm":[20,20],"T1_SR1A_center_before_mm":[14,82],
       "T1_SR1A_center_after_mm":[14,52],
       "Lr_center_before_mm":[26,49],"Lr_center_after_mm":[26,79],
       "ELP38_body_after_mm":{"xmin":6.95,"xmax":45.05,"ymin":66.3,"ymax":91.7},
       "static_native_pad_mechanical_body_collisions":0,
       "planned_copper_moving_to_different_net_collisions":0,
       "manufacturing_release":False}

def call(js):
    return V9.D.call(V9.D.build_invoke_args(SESSION_ID,js,59000),timeout_s=85)

def baseJS():
    return ("const project=await eda.dmt_Project.getCurrentProjectInfo();"
       "if(!project?.friendlyName?.includes('"+PROJECT_PREFIX+"'))throw Error('Wrong GUI');"
       "await eda.dmt_EditorControl.openDocument('"+PCB_UUID+"');")

def stage1():
    if R1.exists():raise FileExistsError("Native component stage already attempted")
    p=plan()
    if sha(SAVED)!=SOURCE_SHA:raise ValueError("Original saved Cin PCB changed")
    if not PLAN.exists():PLAN.write_text(json.dumps(p,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    elif load(PLAN)!=json.loads(json.dumps(p)):raise ValueError("Existing source-locked T1/Lr plan differs")
    js="return await(async()=>{"+baseJS()+"""
      const plan=__PLAN__;
      const parts=await eda.pcb_PrimitiveComponent.getAll();
      const lines=await eda.pcb_PrimitiveLine.getAll();
      const vias=await eda.pcb_PrimitiveVia.getAll();
      if(parts.length!==149||lines.length!==508||vias.length!==106)
        throw Error('Unexpected accepted post-Cin PCB count');
      const done=[];
      for(const [ref,cfg] of Object.entries(plan.components)){
        const c=parts.find(x=>x.getState_Designator()===ref);
        if(!c||Math.abs(c.getState_X()-cfg.x)>.06||Math.abs(c.getState_Y()-cfg.y)>.06||
           c.getState_Rotation()!==cfg.rotation)
            throw Error('T1 stage1 source mismatch '+ref);
      }
      for(const [ref,cfg] of Object.entries(plan.components)){
        const x=parts.find(x=>x.getState_Designator()===ref);
        const updated=await eda.pcb_PrimitiveComponent.modify(x.getState_PrimitiveId(),{
           x:cfg.x,y:cfg.y-cfg.dy_mm/.0254,rotation:cfg.rotation});
        if(!updated)throw Error('T1/Lr native component move failed '+ref);
        done.push({ref,id:x.getState_PrimitiveId(),newX:updated.getState_X(),newY:updated.getState_Y()});
      }
      return {status:'T1_LR_REAL_NATIVE_TEN_PARTS_MOVED',done,
        lineCount:(await eda.pcb_PrimitiveLine.getAll()).length};
    })();""".replace("__PLAN__",json.dumps(p,ensure_ascii=False,separators=(",",":")))
    r=call(js)
    ok=r.get("ok") and (r.get("value") or {}).get("status")=="T1_LR_REAL_NATIVE_TEN_PARTS_MOVED"
    R1.write_text(json.dumps({"status":"T1_LR_NATIVE_10_PARTS_MOVED_REQUIRES_COPPER" if ok else "T1_LR_COMPONENT_MOVE_UNVERIFIED",
       "native":r,"not_for_fab":True},ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"ok":ok,"status":(r.get("value") or {}).get("status"),
       "parts":len((r.get("value") or {}).get("done",[])),"error":r.get("error")}))
    if not ok:raise RuntimeError("Inspect GUI live state; never repeat phase without verifying")

def stage2():
    if R2.exists():raise FileExistsError("Native copper stage already attempted")
    if load(R1)["status"]!="T1_LR_NATIVE_10_PARTS_MOVED_REQUIRES_COPPER":raise ValueError("Part move never verified")
    p=plan()
    js="return await(async()=>{"+baseJS()+"""
      const cfg=__PLAN__;
      const cs=await eda.pcb_PrimitiveComponent.getAll(),ls=await eda.pcb_PrimitiveLine.getAll(),
            vs=await eda.pcb_PrimitiveVia.getAll();
      if(cs.length!==149||ls.length!==508||vs.length!==106)
        throw Error('Native copper baseline changed');
      for(const [ref,x] of Object.entries(cfg.components)){
        const c=cs.find(q=>q.getState_Designator()===ref);
        if(!c||Math.abs(c.getState_Y()-(x.y-x.dy_mm/.0254))>.09)
          throw Error('T1 stage1 part not at new site '+ref);
      }
      for(const row of cfg.lines){
         const line=ls.find(x=>x.getState_PrimitiveId()===row.id);
         if(!line||line.getState_Net()!==row.net||
             Math.abs(line.getState_StartY()-row.y1)>.1||
             Math.abs(line.getState_EndY()-row.y2)>.1)
            throw Error('Local T1 line drift '+row.id);
      }
      for(const row of cfg.vias){
         const via=vs.find(x=>x.getState_PrimitiveId()===row.id);
         if(!via||via.getState_Net()!==row.net||Math.abs(via.getState_Y()-row.y)>.1)
            throw Error('Local T1 via drift '+row.id);
      }
      const done={lines:[],vias:[]},dy=30/.0254;
      for(const row of cfg.lines){
        const z=await eda.pcb_PrimitiveLine.modify(row.id,{
          startX:row.x1,startY:row.y1+dy,endX:row.x2,endY:row.y2+dy});
        if(!z)throw Error('Native line move failed '+row.id);
        done.lines.push(row.id);
      }
      for(const row of cfg.vias){
        const z=await eda.pcb_PrimitiveVia.modify(row.id,{x:row.x,y:row.y+dy});
        if(!z)throw Error('Native plated via move failed '+row.id);
        done.vias.push(row.id);
      }
      return{status:'T1_NATIVE_TWENTY_TRACKS_TWO_VIAS_MOVED',done,
        parts:(await eda.pcb_PrimitiveComponent.getAll()).length,
        traces:(await eda.pcb_PrimitiveLine.getAll()).length,
        viaCount:(await eda.pcb_PrimitiveVia.getAll()).length};
    })();""".replace("__PLAN__",json.dumps(p,ensure_ascii=False,separators=(",",":")))
    r=call(js)
    ok=r.get("ok") and (r.get("value") or {}).get("status")=="T1_NATIVE_TWENTY_TRACKS_TWO_VIAS_MOVED"
    R2.write_text(json.dumps({"status":"T1_LR_NATIVE_LOCAL_COPPER_RELOCATED_PENDING_DRC" if ok else "T1_LOCAL_COPPER_MOVE_UNVERIFIED",
      "native":r,"not_for_fab":True},ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"ok":ok,"value":r.get("value"),"error":r.get("error")},ensure_ascii=False)[:1800])
    if not ok:raise RuntimeError("Copper move state unverified")

def stage3():
    if R3.exists():raise FileExistsError("T1/Lr validation already attempted")
    if load(R2)["status"]!="T1_LR_NATIVE_LOCAL_COPPER_RELOCATED_PENDING_DRC":
        raise ValueError("T1 local tracks and vias not verified")
    p=plan()
    js="return await(async()=>{"+baseJS()+"""
      const plan=__PLAN__;
      const cs=await eda.pcb_PrimitiveComponent.getAll(),ls=await eda.pcb_PrimitiveLine.getAll(),
            vs=await eda.pcb_PrimitiveVia.getAll();
      if(cs.length!==149||ls.length!==508||vs.length!==106)throw Error('V18 power unit native count drift');
      const moved=[];
      for(const [ref,cfg] of Object.entries(plan.components)){
        const c=cs.find(q=>q.getState_Designator()===ref);
        if(!c||Math.abs(c.getState_Y()-(cfg.y-cfg.dy_mm/.0254))>.1)
          throw Error('Power part movement not persisted '+ref);
        moved.push({ref,x:c.getState_X(),y:c.getState_Y()});
      }
      const dy=30/.0254;
      for(const row of plan.lines){
        const line=ls.find(x=>x.getState_PrimitiveId()===row.id);
        if(!line||Math.abs(line.getState_StartY()-(row.y1+dy))>.1||
             Math.abs(line.getState_EndY()-(row.y2+dy))>.1)
          throw Error('Power-cell trace did not move '+row.id);
      }
      for(const row of plan.vias){
        const v=vs.find(x=>x.getState_PrimitiveId()===row.id);
        if(!v||Math.abs(v.getState_Y()-(row.y+dy))>.1)
          throw Error('Power-cell plated via did not move '+row.id);
      }
      const drc=await eda.pcb_Drc.check(true,false,true);
      const counts=Object.fromEntries(drc.map(g=>[g.name,g.list.reduce((n,z)=>n+(z.list||[]).length,0)]));
      const clearance=(drc.find(g=>g.name==='Clearance Error')?.list||[])
       .flatMap(z=>z.list||[]).slice(0,8).map(z=>({obj1:z.obj1,obj2:z.obj2,details:z.explanation?.errData}));
      const physical=(counts['Clearance Error']||0)+(counts['Physical Error']||0);
      const saved=await eda.pcb_Document.save();
      return{status:'V18_T1_LR_NATIVE_LAYOUT_DRC_MEASURED_AND_SAVED',counts,clearance,physical,
       saved,moved,partCount:cs.length,trackCount:ls.length,viaCount:vs.length,
       notFabApproved:true};
    })();""".replace("__PLAN__",json.dumps(p,ensure_ascii=False,separators=(",",":")))
    r=call(js)
    v=r.get("value") or {}
    ok=r.get("ok") and v.get("saved") is True and v.get("status")=="V18_T1_LR_NATIVE_LAYOUT_DRC_MEASURED_AND_SAVED"
    R3.write_text(json.dumps({"status":"ACTUAL_V18_T1_SR_GROUP_AND_LR_CORE_SITE_SWAPPED_NOT_FOR_FAB" if ok else "T1_LR_NATIVE_DRC_OR_SAVE_UNVERIFIED",
      "native":r,"fabrication_approved":False},ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"ok":ok,"status":v.get("status"),"DRC":v.get("counts"),"physical":v.get("physical"),
       "clearance":v.get("clearance"),"saved":v.get("saved"),"error":r.get("error")},ensure_ascii=False)[:3200])
    if not ok:raise RuntimeError("Native source not accepted")

def main():
    p=argparse.ArgumentParser()
    g=p.add_mutually_exclusive_group(required=True)
    for q in ("components","copper","validate"):g.add_argument("--"+q,action="store_true")
    a=p.parse_args()
    if a.components:stage1()
    elif a.copper:stage2()
    else:stage3()
if __name__=="__main__":main()

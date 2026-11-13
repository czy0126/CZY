"""V15 one-shot native GUI edit recovery AFTER confirmed no previous mutation.

The original all-in-one request timed out in full-board pre-DRC, and its
independent post-timeout readback proved all nine components, GA4 trace and
REG4 via unchanged. Now split native 9-part+18-line+2-via migration from
the separate full DRC. Reject ANY partial prior edit and never replay
when a receipt exists. Work on copied V15 PCB only, not source V14.
"""
from __future__ import annotations
import json,hashlib,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
G=ROOT/"hardware/dcx_main/g2"
sys.path[:0]=[str(G),str(ROOT/"hardware/dcx_main/g1"),str(ROOT/"tools")]
import g2_v9_real_t530_components as V9
from g2_v15_T4_rigid_power_cell_native import build,sha,ACTIVE,V14,V14_SHA,SESS,PROJECT,V15_UUID,PLAN

OLD_ATTEMPT=G/"g2_v15_T4_power_cell_actual_native_move_DRC_NOT_FOR_FAB.json"
REC=G/"g2_v15_T4_9part_18line_2via_native_split_edit_once_NOT_FOR_FAB.json"

def main():
    if REC.exists():raise FileExistsError("Native split operation was already attempted; no replay")
    p=build()
    if json.loads(PLAN.read_text("utf8"))!=json.loads(json.dumps(p)):
        raise ValueError("Saved source-locked V15 plan mismatch")
    a=json.loads(OLD_ATTEMPT.read_text("utf8"))
    if a.get("status")!="NATIVE_V15_T4_OPERATION_UNVERIFIED_STOP_NO_REPLAY":
        raise ValueError("Prior first request did not time out; refuse recovery")
    if a.get("api",{}).get("error",{}).get("code")!="REQUEST_TIMEOUT":
        raise ValueError("Prior failed GUI command is not a timeout; refuse")
    if sha(V14)!=V14_SHA:raise ValueError("Original immutable V14 drift")
    sid=json.loads(SESS.read_text("utf8"))["new_session"]
    active=V9.D.call([str(V9.D.LEDA),"session","list"],timeout_s=22)
    if not active.get("ok") or not any(s["sessionId"]==sid and s["status"]=="alive" and not s["headless"] for s in active["value"]):
        raise RuntimeError("Existing GUI not alive; NO new window")
    js="""return await(async()=>{const project=await eda.dmt_Project.getCurrentProjectInfo();
      if(project?.friendlyName!==%s)throw Error('wrong project');
      await eda.dmt_EditorControl.openDocument(%s);
      const a=%s;
      const before={
        c:await eda.pcb_PrimitiveComponent.getAll(),
        l:await eda.pcb_PrimitiveLine.getAll(),
        v:await eda.pcb_PrimitiveVia.getAll(),
        p:await eda.pcb_PrimitivePad.getAll()};
      if(before.c.length!==149||before.l.length!==484||
          before.v.length!==104||before.p.length!==423)
        throw Error('V15 target native counts are not exact baseline');
      const delta=-a.translation_mm.y/.0254;
      // Guard the complete original native geometry BEFORE ANY modification.
      for(const ref of a.rigid_cell_9_refdes){
        const x=before.c.find(y=>y.getState_Designator()===ref);
        const old=a.original_component_positions_mil[ref];
        if(!x||Math.abs(x.getState_X()-old.X)>.08||
          Math.abs(x.getState_Y()-old.Y)>.08||x.getState_Rotation()!==old.Rotation)
          throw Error('Previous partial move detected: '+ref);
      }
      for(const spec of a.move_18_real_native_line_IDs){
        const x=before.l.find(y=>y.getState_PrimitiveId()===spec.id);
        if(!x||x.getState_Net()!==spec.net||
          Math.abs(x.getState_StartY()-spec.startY)>.08||
          Math.abs(x.getState_EndY()-spec.endY)>.08)
          throw Error('Original signal copper already moved: '+spec.id);
      }
      for(const spec of a.move_2_real_native_via_IDs){
        const x=before.v.find(y=>y.getState_PrimitiveId()===spec.id);
        if(!x||x.getState_Net()!==spec.net||
            Math.abs(x.getState_Y()-spec.y)>.08)
          throw Error('Original via already moved: '+spec.id);
      }
      const changes={components:[],lines:[],vias:[]};
      try {
        for(const ref of a.rigid_cell_9_refdes){
          const x=before.c.find(y=>y.getState_Designator()===ref);
          const old=a.original_component_positions_mil[ref];
          const updated=await eda.pcb_PrimitiveComponent.modify(x.getState_PrimitiveId(),
            {x:old.X,y:old.Y+delta,rotation:old.Rotation});
          if(!updated||Math.abs(updated.getState_Y()-(old.Y+delta))>.08)
            throw Error('PCB component modification failed '+ref);
          changes.components.push(ref);
        }
        for(const spec of a.move_18_real_native_line_IDs){
          const updated=await eda.pcb_PrimitiveLine.modify(spec.id,{
            startX:spec.startX,startY:spec.startY+delta,
            endX:spec.endX,endY:spec.endY+delta});
          if(!updated)throw Error('Real native line.modify failed '+spec.id);
          changes.lines.push({id:spec.id,net:spec.net});
        }
        for(const spec of a.move_2_real_native_via_IDs){
          const updated=await eda.pcb_PrimitiveVia.modify(spec.id,{
            x:spec.x,y:spec.y+delta});
          if(!updated)throw Error('Real native via.modify failed '+spec.id);
          changes.vias.push({id:spec.id,net:spec.net});
        }
        const latest=await eda.pcb_PrimitiveComponent.getAll();
        const verified=a.rigid_cell_9_refdes.map(ref=>{
          const x=latest.find(x=>x.getState_Designator()===ref);
          return{ref,x:x.getState_X(),y:x.getState_Y(),
           layer:x.getState_Layer(),rotation:x.getState_Rotation()};
        });
        if(verified.some(x=>Math.abs(x.y-(a.original_component_positions_mil[x.ref].Y+delta))>.08))
           throw Error('Native moved all 9 but post move component location mismatch');
        const saved=await eda.pcb_Document.save();
        if(saved!==true)throw Error('native PCB save refused');
        return{status:'V15_T4_NATIVE_9COMP_18LINES_2VIAS_REAL_MOVED_AND_SAVED_WIP',
           saved,changes,actualPositions:verified,
           counts:{components:(await eda.pcb_PrimitiveComponent.getAll()).length,
             pads:(await eda.pcb_PrimitivePad.getAll()).length,
             lines:(await eda.pcb_PrimitiveLine.getAll()).length,
             vias:(await eda.pcb_PrimitiveVia.getAll()).length}};
      }catch(e){
        return{status:'V15_T4_NATIVE_PARTIAL_OR_ERROR_DO_NOT_REPEAT',
         error:String(e),completed:changes};
      }
    })();"""%(json.dumps(PROJECT),json.dumps(V15_UUID),json.dumps(p,ensure_ascii=False,separators=(",",":")))
    r=V9.D.call(V9.D.build_invoke_args(sid,js,59000),timeout_s=79)
    v=r.get("value") or {}
    ok=r.get("ok") and v.get("status")=="V15_T4_NATIVE_9COMP_18LINES_2VIAS_REAL_MOVED_AND_SAVED_WIP"
    REC.write_text(json.dumps({"status":"V15_T4_NATIVE_REAL_LAYOUT_SAVED_DRC_STILL_PENDING" if ok else "V15_T4_NATIVE_MOVE_NOT_VERIFIED_NO_REPLAY",
         "native_api":r,"immutable_V14_SHA":V14_SHA,"plan_sha256":sha(PLAN),
         "fabrication_approved":False},ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"api_ok":r.get("ok"),"status":v.get("status"),
       "error":v.get("error") or r.get("error"),"changed":v.get("changes"),
       "counts":v.get("counts"),"positions":v.get("actualPositions")},ensure_ascii=False,indent=2)[:5000])
    if not ok:raise RuntimeError("V15 T4 native layout NOT verified, do not replay")
if __name__=="__main__":main()

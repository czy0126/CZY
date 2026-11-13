"""D1 V15: REAL EasyEDA-native isolated T4 power-cell relocation pilot.

Do not reopen another EasyEDA window. A NEW copied PCB V15 UUID
9b212da9a255a2af already lives in existing GUI beside original V14.
Move 9 T4 SR/driver/4 gate and sense resistors and REG/PGND/VCC12_S decouplers
up 30mm as a *rigid circuit cell*, while translating its 18 associated
native signal copper lines and 2 local vias preserving local continuity.
The VOUT/PGND long bus links are NOT translated -- they need redesign:
the DRC connection count may increase, and the V15 result is NOT_FOR_FAB.

 --plan prints preflight + writes locked plan (no EDA modifications)
 --apply applies once to copied V15 PCB, runs real EDA DRC
 --snapshot saves flushed working SQLite to unique V15 binary after apply
"""
from __future__ import annotations
import argparse,collections,hashlib,json,math,shutil,sys
from pathlib import Path
from shapely.geometry import box,LineString,Point
from shapely.affinity import translate

ROOT=Path(__file__).resolve().parents[1]
G=ROOT/"hardware/dcx_main/g2"
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"hardware/dcx_main/g1"),str(G)]
from g2_board_keepout import pad_bbox
import g2_v9_real_t530_components as V9

V14=G/"dcx_main_board_g2_V14_EILP32_12NPTH_OC_OCM_OCD_REG4_BOTTOM_WIP_NOT_FOR_FAB.eprj2"
ACTIVE=G/"dcx_main_board_g2_V13_FIVE_MAGNETICS_LOGICAL_LANDING_TRIAL_NOT_FOR_FAB.eprj2"
READ=G/"g2_v14_after_REG4_native_full_copper_readback_NOT_FOR_FAB.json"
DFM=G/"g2_v14_through_board_three_leg_slot_DFM_screen_NOT_FOR_FAB.json"
SOURCE_COPY=G/"g2_v15_copy_V14_native_same_gui_once_NOT_FOR_FAB.json"
SOURCE_RENAME=G/"g2_v15_native_rename_readback_once_NOT_FOR_FAB.json"
SESS=G/"g2_v13_GUI_open_unique_attempt_NOT_FOR_FAB.json"
PLAN=G/"g2_v15_T4_eight_SRs_one_power_cell_translation_preflight_NOT_FOR_FAB.json"
RECEIPT=G/"g2_v15_T4_power_cell_actual_native_move_DRC_NOT_FOR_FAB.json"
SNAP=G/"dcx_main_board_g2_V15_T4_POWER_CELL_UP30MM_WIP_NOT_FOR_FAB.eprj2"
SNAP_META=G/"g2_v15_T4_saved_native_snapshot_NOT_FOR_FAB.json"

V14_SHA="7dd77910bcf7ff3fd0e2be1e4194439a22189aaf353f105bbe1280c104e4f6fc"
V15_UUID="9b212da9a255a2af"
ORIG_V14_UUID="8c496410b2877d3c"
PROJECT="dcx_main_board_g2_V13_FIVE_MAGNETICS_LOGICAL_LANDING_TRIAL_NOT_FOR_FAB"
DY_MM=-30.0
M=.0254
GROUP={"U6","C10","C108","SR4A","SR4B","R26","R27","R34","R35"}
ISOLATED={"GA4","GB4","VG4_A","VG4_B","VD4_A","VD4_B","SEC4_A","SEC4_B","REG4"}
CLEARANCE=.19

def sha(f):return hashlib.sha256(f.read_bytes()).hexdigest()
def load(f):return json.loads(f.read_text("utf8"))
def write_once(f,obj):
    if f.exists():raise FileExistsError("Do not overwrite prior native API operation/geometry evidence: "+str(f))
    f.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf8",newline="\n")

def segment_shape(q):
    a=(q["x1"]*M,-q["y1"]*M)
    b=(q["x2"]*M,-q["y2"]*M)
    return LineString([a,b]).buffer(q["width"]*M/2)

def via_shape(q):
    return Point(q["x"]*M,-q["y"]*M).buffer(q["diameter"]*M/2)

def should_move_line(l):
    if l["net"] in ISOLATED:return True
    a=(l["x1"]*M,-l["y1"]*M)
    b=(l["x2"]*M,-l["y2"]*M)
    if l["net"]=="VCC12_S":
        return min(a[0],b[0])>125 and min(a[1],b[1])>=66 and max(a[1],b[1])<=72
    if l["net"]=="PGND":
        return min(a[0],b[0])>130 and min(a[1],b[1])>74 and max(a[1],b[1])<=77
    return False

def should_move_via(v):
    return v["net"]=="REG4" or (v["net"]=="PGND" and v["x"]*M>130 and 74<-v["y"]*M<77)

def build():
    if sha(V14)!=V14_SHA:raise ValueError("V14 verified original source changed")
    copy=load(SOURCE_COPY)["native"]["value"]
    if copy["original_V14"]!=ORIG_V14_UUID or copy["NEW_V15_uuid"]!=V15_UUID:
        raise ValueError("Distinct source PCB V15 copy missing")
    renamed=load(SOURCE_RENAME)["native"]["value"]
    if renamed["newInfo"]["uuid"]!=V15_UUID or renamed["native"]!={
      "components":149,"pads":423,"lines":484,"vias":104}:
        raise ValueError("V15 native inventory drift")
    b=load(READ)["native"]
    if tuple(len(b[k]) for k in ("components","pads","lines","vias"))!=(149,423,484,104):
        raise ValueError("Native readback source changed")
    comp={q["ref"]:q for q in b["components"]}
    if len(GROUP)!=9 or not GROUP.issubset(comp):raise ValueError("Group parts lost")
    lines=[x for x in b["lines"] if should_move_line(x)]
    vias=[x for x in b["vias"] if should_move_via(x)]
    if len(lines)!=18 or len(vias)!=2:
        raise ValueError("Expected 18 local native net lines and two vias")
    if collections.Counter(l["net"] for l in lines)!={
        "SEC4_A":3,"SEC4_B":3,"GA4":3,"GB4":3,
        "REG4":2,"PGND":2,"VCC12_S":1,"VD4_A":1}:
        raise ValueError("Unexpected scope of real T4 signal copper")
    pads=[x for x in b["pads"] if x.get("ref") in GROUP]
    if len(pads)!=40:raise ValueError("Unexpected native T4 cell pin count")
    slots=load(DFM)["slots"]
    keepouts=[box(s["x_min_mm"]-.5,s["y_min_mm"]-.5,
                  s["x_max_mm"]+.5,s["y_max_mm"]+.5) for s in slots]
    # All unlike-net physical copper must be excluded for *static* shapes;
    # all nine cell components and 18 lines/2 vias translate as one unit.
    pstatic=[(p["Net"],p.get("ref"),p["Layer"],box(*pad_bbox(p))) for p in b["pads"] if p.get("ref") not in GROUP]
    lstatic=[(l["net"],l["layer"],segment_shape(l)) for l in b["lines"] if l not in lines]
    vstatic=[(v["net"],via_shape(v)) for v in b["vias"] if v not in vias]
    check_shapes=[]
    for x in pads:
        check_shapes.append((x["Net"],x["Layer"],translate(box(*pad_bbox(x)),0,DY_MM),"MOVED_PAD"))
    for x in lines:
        check_shapes.append((x["net"],x["layer"],translate(segment_shape(x),0,DY_MM),"MOVED_TRACK"))
    for x in vias:
        check_shapes.append((x["net"],0,translate(via_shape(x),0,DY_MM),"MOVED_VIA"))
    crosschecks=0
    for net,layer,metal,kind in check_shapes:
        if metal.bounds[0]<0.5 or metal.bounds[2]>154.5 or metal.bounds[1]<0.5 or metal.bounds[3]>130.5:
            raise ValueError("V15 moved cell exceeds existing board")
        if any(metal.distance(s)<.5 for s in keepouts):
            raise ValueError("V15 moved cell enters T1..4 real core NPTH copper/mechanical keepout")
        for n,ref,l,shape in pstatic:
            if n==net or (layer and l not in (0,12,layer)):continue
            crosschecks+=1
            if metal.distance(shape)<CLEARANCE-1e-7:
                raise ValueError(f"{kind} violates unmoved pad {ref}/{n}")
        for n,l,shape in lstatic:
            if n==net or (layer and l!=layer):continue
            crosschecks+=1
            if metal.distance(shape)<CLEARANCE-1e-7:
                raise ValueError(f"{kind} violates unmoved trace {n}")
        for n,shape in vstatic:
            if n==net:continue
            crosschecks+=1
            if metal.distance(shape)<CLEARANCE-1e-7:
                raise ValueError(f"{kind} violates unmoved via {n}")
    old_center=(128.0,82.0)
    new_center=(128.0,52.0)
    core=(134.0,20.0)
    a=math.dist(old_center,core)
    b_new=math.dist(new_center,core)
    return {
      "schema":"D1_V15_REAL_EASYEDA_T4_RIGID_POWER_UNIT_REPOSITION_V1",
      "source_V14_verified_SHA256":V14_SHA,
      "source_native_149_components_423_pads_484_lines_104_vias_SHA256":sha(READ),
      "original_PCB1_uuid":"2f6fa2d508d3f9a8",
      "original_V14_uuid":ORIG_V14_UUID,"target_distinct_V15_uuid":V15_UUID,
      "source_EI_T4_core_centre_mm":core,
      "translation_mm":{"x":0,"y":DY_MM},
      "rigid_cell_9_refdes":sorted(GROUP),
      "move_true_40_native_pads_by_component":True,
      "move_18_real_native_line_IDs":[{"id":q["id"],"net":q["net"],"layer":q["layer"],
        "startX":q["x1"],"startY":q["y1"],"endX":q["x2"],"endY":q["y2"],"width":q["width"]} for q in lines],
      "move_2_real_native_via_IDs":[{"id":q["id"],"net":q["net"],"x":q["x"],"y":q["y"]} for q in vias],
      "original_component_positions_mil":{r:{"X":comp[r]["X"],"Y":comp[r]["Y"],
           "Rotation":comp[r]["Rotation"]} for r in sorted(GROUP)},
      "T4_to_SR4A_centre_before_mm":round(a,3),
      "T4_to_SR4A_centre_after_mm":round(b_new,3),
      "T4_to_SR4A_centre_reduction_pct":round(100*(1-b_new/a),1),
      "slot_lower_edge_to_SR4A_SEC_pad_before_mm":48.179,
      "slot_lower_edge_to_SR4A_SEC_pad_after_mm":18.179,
      "unlike_net_static_copper_clearance_min_mm":CLEARANCE,
      "unlike_net_static_copper_comparisons":crosschecks,
      "top_and_bottom_components_preserved":True,
      "original_100A_PGND_and_VOUT_straps_must_be_rerouted":True,
      "all_electrical_connections_closed":False,
      "true_vendor_CORE_DOT_PINOUT_validated":False,
      "fabrication_approved":False
    }

def apply():
    if RECEIPT.exists():raise FileExistsError("No duplicate GUI native edits; inspect receipt")
    plan=build()
    if load(PLAN)!=json.loads(json.dumps(plan)):raise ValueError("V15 plan drifted; refuse edits")
    sid=load(SESS)["new_session"]
    st=V9.D.call([str(V9.D.LEDA),"session","list"],timeout_s=22)
    if not st.get("ok") or not any(x["sessionId"]==sid and x["status"]=="alive" and x["headless"] is False for x in st["value"]):
        raise ValueError("Existing EasyEDA GUI not alive. Do not open new window.")
    js="""return await(async()=>{const p=await eda.dmt_Project.getCurrentProjectInfo();
      if(p?.friendlyName!==%s)throw Error('wrong existing GUI project');
      await eda.dmt_EditorControl.openDocument(%s);
      const c=await eda.pcb_PrimitiveComponent.getAll();
      const t=await eda.pcb_PrimitiveLine.getAll();
      const v=await eda.pcb_PrimitiveVia.getAll();
      const pads=await eda.pcb_PrimitivePad.getAll();
      if(c.length!==149||t.length!==484||v.length!==104||pads.length!==423)throw Error('V15 target copy moved previously');
      const cfg=%s;const moved={components:[],lines:[],vias:[]};
      const err0=await eda.pcb_Drc.check(true,false,true);
      const count=raw=>Object.fromEntries(raw.map(z=>[z.name,z.list.reduce((n,q)=>n+(q.list||[]).length,0)]));
      const before=count(err0);
      if((before['Connection Error']||0)!==111||
         (before['Netlist Error']||0)!==0||(before['Physical Error']||0)!==0)
        throw Error('V15 copied source no longer matches verified V14: '+JSON.stringify(before));
      const delta=-cfg.translation_mm.y/.0254;
      try{
      for(const ref of cfg.rigid_cell_9_refdes){
        const x=c.find(x=>x.getState_Designator()===ref);
        const old=cfg.original_component_positions_mil[ref];
        if(!x||Math.abs(x.getState_X()-old.X)>.1||Math.abs(x.getState_Y()-old.Y)>.1||
              x.getState_Rotation()!==old.Rotation)throw Error('V15 component moved already: '+ref);
        const real=await eda.pcb_PrimitiveComponent.modify(x.getState_PrimitiveId(),
                 {x:old.X,y:old.Y+delta,rotation:old.Rotation});
        if(!real||Math.abs(real.getState_Y()-(old.Y+delta))>.05)throw Error('Native power-cell component translate failed '+ref);
        moved.components.push({ref,id:x.getState_PrimitiveId(),fromY:old.Y,toY:real.getState_Y()});
      }
      for(const row of cfg.move_18_real_native_line_IDs){
        const x=t.find(x=>x.getState_PrimitiveId()===row.id);
        if(!x||x.getState_Net()!==row.net||x.getState_Layer()!==row.layer||
          Math.abs(x.getState_StartY()-row.startY)>.15||
          Math.abs(x.getState_EndY()-row.endY)>.15)throw Error('Native line UUID/geometry not original '+row.id);
        const z=await eda.pcb_PrimitiveLine.modify(row.id,
          {startX:row.startX,startY:row.startY+delta,
            endX:row.endX,endY:row.endY+delta});
        if(!z)throw Error('Native copper line modify missing '+row.id);
        moved.lines.push({id:row.id,net:row.net,source_startY:row.startY});
      }
      for(const row of cfg.move_2_real_native_via_IDs){
        const x=v.find(x=>x.getState_PrimitiveId()===row.id);
        if(!x||x.getState_Net()!==row.net||Math.abs(x.getState_Y()-row.y)>.15)
            throw Error('Native target via id mismatch '+row.id);
        const z=await eda.pcb_PrimitiveVia.modify(row.id,{x:row.x,y:row.y+delta});
        if(!z)throw Error('Native local via move failed '+row.id);
        moved.vias.push({id:row.id,net:row.net});
      }
      const afterRaw=await eda.pcb_Drc.check(true,false,true);
      const after=count(afterRaw);
      const actual=await eda.pcb_PrimitiveComponent.getAll();
      const movedParts=cfg.rigid_cell_9_refdes.map(ref=>{const o=actual.find(x=>x.getState_Designator()===ref);
        return{ref,x:o.getState_X(),y:o.getState_Y(),rot:o.getState_Rotation(),layer:o.getState_Layer()};});
      if(movedParts.some(x=>Math.abs(x.y-(cfg.original_component_positions_mil[x.ref].Y+delta))>.08))
        throw Error('Power-cell placement post-EDA readback mismatch');
      if((after['Physical Error']||0)!==0||(after['Netlist Error']||0)!==0)
        throw Error('V15 new manufacturing/short violation; do NOT release: '+JSON.stringify(after));
      const saved=await eda.pcb_Document.save();
      if(saved!==true)throw Error('Native V15 PCB did not save');
      return {status:'NATIVE_V15_T4_REAL_POWER_CELL_MOVED_30MM_AND_LOCAL_COPPER_SAVED_NOT_FOR_FAB',
        before,after,movedParts,modified:moved,save_confirmed:saved,
        counts:{components:(await eda.pcb_PrimitiveComponent.getAll()).length,
         pads:(await eda.pcb_PrimitivePad.getAll()).length,
         lines:(await eda.pcb_PrimitiveLine.getAll()).length,
         vias:(await eda.pcb_PrimitiveVia.getAll()).length}};
      }catch(e){
        return {status:'NATIVE_V15_T4_PARTIAL_UNVERIFIED_NOT_FOR_FAB_DO_NOT_REPLAY',
          error:String(e),modified:moved,original_V14_still_untouched:true};
      }
    })();"""%(json.dumps(PROJECT),json.dumps(V15_UUID),json.dumps(plan,ensure_ascii=False,separators=(",",":")))
    r=V9.D.call(V9.D.build_invoke_args(sid,js,59000),timeout_s=83)
    result=r.get("value") or {}
    passed=r.get("ok") and result.get("status")=="NATIVE_V15_T4_REAL_POWER_CELL_MOVED_30MM_AND_LOCAL_COPPER_SAVED_NOT_FOR_FAB"
    write_once(RECEIPT,{"status":"V15_REAL_T4_POWER_CELL_NATIVE_MODIFIED_SAVED_NOT_FOR_FAB" if passed
        else "NATIVE_V15_T4_OPERATION_UNVERIFIED_STOP_NO_REPLAY",
        "api":r,"plan_sha256":sha(PLAN),"fabrication_approved":False})
    print(json.dumps({"status":result.get("status"),"before":result.get("before"),
         "after":result.get("after"),"nParts":len(result.get("movedParts",[])),
         "modified":{k:len(v) for k,v in result.get("modified",{}).items()},
         "counts":result.get("counts"),"error":result.get("error")},
         ensure_ascii=False,indent=2)[:3800])
    if not passed:raise RuntimeError("V15 native T4 live edit partially/unverified; do not blindly retry")

def snapshot():
    if SNAP.exists() or SNAP_META.exists():raise FileExistsError("Never overwrite saved V15 native source")
    result=load(RECEIPT)
    if result["status"]!="V15_REAL_T4_POWER_CELL_NATIVE_MODIFIED_SAVED_NOT_FOR_FAB":
        raise RuntimeError("Cannot copy unverified native PCB")
    if sha(ACTIVE)==V14_SHA:raise RuntimeError("Live CAD save not yet flushed")
    shutil.copy2(ACTIVE,SNAP)
    import sqlite3
    with sqlite3.connect("file:"+SNAP.resolve().as_posix()+"?mode=ro",uri=True) as db:
        row=db.execute("select structure from project_structures order by id desc limit 1").fetchone()
        assert row
        project=json.loads(row[0])
        if set(project["pcbs"])!={"2f6fa2d508d3f9a8","8c496410b2877d3c",V15_UUID}:
            raise RuntimeError("V15 snapshot missing original PCB1 or source V14")
    write_once(SNAP_META,{"status":"V15_REAL_NATIVE_T4_CELL_9_COMPONENTS_18_LINES_2_VIAS_PERSISTED_WIP",
      "snapshot_filename":SNAP.name,"sha256":sha(SNAP),"size":SNAP.stat().st_size,
      "contains_3_PCBs_in_one_existing_gui":True,"source_original_V14_sha256":V14_SHA,
      "fabrication_approved":False})
    print(json.dumps({"snapshot":SNAP.name,"sha256":sha(SNAP)}))

def main():
    ap=argparse.ArgumentParser()
    a=ap.add_mutually_exclusive_group(required=True)
    for n in ("plan","apply","snapshot"):a.add_argument("--"+n,action="store_true")
    c=ap.parse_args()
    if c.plan:
        obj=build()
        if PLAN.exists() and load(PLAN)!=obj:raise ValueError("Old approved pilot plan changed")
        if not PLAN.exists():write_once(PLAN,obj)
        print(json.dumps({"pilot_cell_refs":obj["rigid_cell_9_refdes"],
          "native_lines":len(obj["move_18_real_native_line_IDs"]),
          "native_vias":len(obj["move_2_real_native_via_IDs"]),
          "T4_to_SR4A_before_mm":obj["T4_to_SR4A_centre_before_mm"],
          "after_mm":obj["T4_to_SR4A_centre_after_mm"],
          "clearance_checks":obj["unlike_net_static_copper_comparisons"]},ensure_ascii=False,indent=2))
    elif c.apply:apply()
    else:snapshot()
if __name__=="__main__":main()

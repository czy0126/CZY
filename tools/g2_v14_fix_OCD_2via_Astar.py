"""D1 V14 OCD overcurrent detector pad-to-pad native routed fix.

Source locked against OC+OCM repaired V14 saved binary, actual DRC=122,
all 423 pads/464 tracks/94 vias. Use same EDA GUI, target only copied V14.
Two PTHs (0.4 drill/0.8 copper) + two top stubs and two bottom route
segments; A*-derived 20.59 mm corridor avoids all unlike-net copper with
>=0.19 mm clearance. Apply once, native DRC gate, snapshot separately after
asynchronous source file flush. This is WIP, not qualified CT noise/D0.
"""
from __future__ import annotations
import argparse,hashlib,json,sys,math,shutil
from pathlib import Path
from shapely.geometry import box,LineString,Point
ROOT=Path(__file__).resolve().parents[1]
G=ROOT/"hardware/dcx_main/g2"
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"hardware/dcx_main/g1"),str(G)]
from g2_board_keepout import pad_bbox
import g2_v9_real_t530_components as V9

SOURCE=G/"dcx_main_board_g2_V14_EILP32_12NPTH_OC_OCM_WIP_NOT_FOR_FAB.eprj2"
LIVE=G/"dcx_main_board_g2_V13_FIVE_MAGNETICS_LOGICAL_LANDING_TRIAL_NOT_FOR_FAB.eprj2"
READ=G/"g2_v14_after_OC_OCM_native_readback_NOT_FOR_FAB.json"
OCM=G/"g2_v14_OCM_native_2via_save_after_DRC_NOT_FOR_FAB.json"
SESS=G/"g2_v13_GUI_open_unique_attempt_NOT_FOR_FAB.json"
RECEIPT=G/"g2_v14_OCD_real_native_signal_fix_DRC_NOT_FOR_FAB.json"
SNAP=G/"dcx_main_board_g2_V14_EILP32_12NPTH_OC_OCM_OCD_WIP_NOT_FOR_FAB.eprj2"
SNAP_META=G/"g2_v14_OCD_saved_native_project_provenance_NOT_FOR_FAB.json"
BASE_SHA="80381f0bb00b781dfc635298020638e3757e9ddc99e2987cd8838c10ee4b0260"
PCB="8c496410b2877d3c"
PROJECT="dcx_main_board_g2_V13_FIVE_MAGNETICS_LOGICAL_LANDING_TRIAL_NOT_FOR_FAB"
M=.0254

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def plan():
    if sha(SOURCE)!=BASE_SHA:raise ValueError("Saved input OC+OCM source SHA drift")
    raw=json.loads(READ.read_text("utf8"))["native"]
    if [len(raw[k]) for k in ("components","pads","lines","vias")]!=[149,423,464,94]:
        raise ValueError("True native WIP PCB geometry changed")
    ok=json.loads(OCM.read_text("utf8"))
    if ok["status"]!="OCM_NATIVE_DRC_DECREASED" or ok["native_result"]["value"]["categories"].get("Connection Error")!=122:
        raise ValueError("Prior OC+OCM native DRC 122 result not authenticated")
    def endpoint(ref,num):
        seq=[q for q in raw["pads"] if q["ref"]==ref and q["PadNumber"]==num and q["Net"]=="OCD"]
        if len(seq)!=1:raise ValueError("Missing uniquely matching detector pad")
        p=seq[0];return (round(p["X"]*M,5),round(-p["Y"]*M,5))
    first=endpoint("D_CT2","3");last=endpoint("R15","1")
    a=(113.,69.5);c=(119.25,69.75);b=(131.25,61.9)
    route=[(1,first,a),(2,a,c),(2,c,b),(1,b,last)]
    vias=[a,b]
    obs={}
    for layer in (1,2):
        obs[layer]=[box(*pad_bbox(p)) for p in raw["pads"] if p["Net"]!="OCD" and p["Layer"] in (0,12,layer)]
        obs[layer]+=[LineString([(q["x1"]*M,-q["y1"]*M),(q["x2"]*M,-q["y2"]*M)]).buffer(q["width"]*M/2)
                     for q in raw["lines"] if q["net"]!="OCD" and q["layer"]==layer]
        obs[layer]+=[Point(q["x"]*M,-q["y"]*M).buffer(q["diameter"]*M/2)
                     for q in raw["vias"] if q["net"]!="OCD"]
    for layer,u,v in route:
        copper=LineString([u,v]).buffer(.1,cap_style=2)
        for oth in obs[layer]:
            if copper.distance(oth)<.18-1e-6:
                raise ValueError("OCD new copper trace intersects existing wrong-net shape")
    allobs=[box(*pad_bbox(q)) for q in raw["pads"] if q["Net"]!="OCD"]
    allobs += [LineString([(q["x1"]*M,-q["y1"]*M),(q["x2"]*M,-q["y2"]*M)]).buffer(q["width"]*M/2)
               for q in raw["lines"] if q["net"]!="OCD"]
    allobs += [Point(q["x"]*M,-q["y"]*M).buffer(q["diameter"]*M/2)
               for q in raw["vias"] if q["net"]!="OCD"]
    for pt in vias:
        circle=Point(*pt).buffer(.4)
        if any(circle.distance(x)<.18-1e-6 for x in allobs):
            raise ValueError("OCD through-via collides with wrong-net existing shape")
    if not math.dist(first,a)<.6 or not math.dist(last,b)<.6:
        raise ValueError("Detector via stub too long")
    return {"source_SHA256":BASE_SHA,"net":"OCD","before_native_DRC_connection_errors":122,
       "native_target_copy_PCB":PCB,"pin_endpoints":{"D_CT2.3":first,"R15.1":last},
       "vias_mm":vias,"via_hole_mm":.4,"via_diameter_mm":.8,"trace_width_mm":.2,
       "paths":[{"layer":l,"start":u,"end":v} for l,u,v in route],
       "source_from_actual_saved_PCB":True,"manufacturer_DFM_approved":False,
       "high_speed_CT_noise_isolation_verified":False,"fabrication_approved":False}

def apply():
    if RECEIPT.exists():raise FileExistsError("Already attempted OCD copper; cannot duplicate")
    args=plan()
    sid=json.loads(SESS.read_text("utf8"))["new_session"]
    sessions=V9.D.call([str(V9.D.LEDA),"session","list"],timeout_s=21)
    if not sessions.get("ok") or not any(q["sessionId"]==sid and q["status"]=="alive" and q["headless"] is False for q in sessions["value"]):
        raise RuntimeError("Do not open another GUI; previous V13 session not available")
    js="""return await(async()=>{const p=await eda.dmt_Project.getCurrentProjectInfo();
      if(p.friendlyName!==%s)throw Error('Wrong live GUI');
      await eda.dmt_EditorControl.openDocument(%s);
      const start={pads:(await eda.pcb_PrimitivePad.getAll()).length,
        lines:(await eda.pcb_PrimitiveLine.getAll()).length,
        vias:(await eda.pcb_PrimitiveVia.getAll()).length,
        comps:(await eda.pcb_PrimitiveComponent.getAll()).length};
      if(JSON.stringify(start)!==JSON.stringify({pads:423,lines:464,vias:94,comps:149}))
        throw Error('Wrong native CAD readback '+JSON.stringify(start));
      const args=%s;const lineIds=[],viaIds=[];
      try{
        for(const v of args.vias_mm){
          const ob=await eda.pcb_PrimitiveVia.create('OCD',v[0]/.0254,-v[1]/.0254,
           args.via_hole_mm/.0254,args.via_diameter_mm/.0254);
          if(!ob)throw Error('OCD via API failed');
          viaIds.push(ob.getState_PrimitiveId());
        }
        for(const r of args.paths){
          const a=r.start,b=r.end;
          const ob=await eda.pcb_PrimitiveLine.create('OCD',r.layer,
            a[0]/.0254,-a[1]/.0254,b[0]/.0254,-b[1]/.0254,
            args.trace_width_mm/.0254,false);
          if(!ob)throw Error('OCD copper API failed');
          lineIds.push(ob.getState_PrimitiveId());
        }
        const native=await eda.pcb_Drc.check(true,false,true);
        const categories=Object.fromEntries(native.map(g=>[g.name,
          g.list.reduce((n,i)=>n+(i.list||[]).length,0)]));
        if((categories['Connection Error']||0)>120 ||
            (categories['Physical Error']||0)>0 ||
            (categories['Netlist Error']||0)>0){
          const undoLines=await eda.pcb_PrimitiveLine.delete(lineIds);
          const undoVias=await eda.pcb_PrimitiveVia.delete(viaIds);
          return {status:'NATIVE_DRC_NOT_IMPROVED_UNDONE',categories,undoLines,undoVias};
        }
        const saved=await eda.pcb_Document.save();
        if(saved!==true)throw Error('OCD native saved=false');
        return {status:'OCD_NATIVE_ROUTE_SAVED_DRC_IMPROVED',categories,saved,
                viaIds,lineIds,linesAfter:(await eda.pcb_PrimitiveLine.getAll()).length,
                viasAfter:(await eda.pcb_PrimitiveVia.getAll()).length};
      }catch(e){
        try{if(lineIds.length)await eda.pcb_PrimitiveLine.delete(lineIds);
          if(viaIds.length)await eda.pcb_PrimitiveVia.delete(viaIds);}catch(_){}
        return {status:'OCD_NATIVE_OPERATION_ROLLBACK_ATTEMPTED',error:String(e)};
      }})();"""%(json.dumps(PROJECT),json.dumps(PCB),json.dumps(args,ensure_ascii=False,separators=(",",":")))
    r=V9.D.call(V9.D.build_invoke_args(sid,js,59000),timeout_s=83)
    data=r.get("value") or {}
    succeeded=r.get("ok") and data.get("status")=="OCD_NATIVE_ROUTE_SAVED_DRC_IMPROVED"
    RECEIPT.write_text(json.dumps({"status":"OCD_DRC_REDUCED_NATIVE_CAD_NOT_FOR_FAB" if succeeded else "OCD_NATIVE_OPERATION_DID_NOT_QUALIFY",
       "native_response":r,"base_sha256":BASE_SHA,"fabrication_approved":False},ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"status":data.get("status"),"DRC":data.get("categories"),
      "vias":data.get("viaIds"),"new_tracks":data.get("lineIds"),
      "error":data.get("error")},ensure_ascii=False,indent=2))
    if not succeeded:raise RuntimeError("OCD DRC did not pass native acceptance check")

def snapshot():
    if SNAP.exists() or SNAP_META.exists():raise FileExistsError("Existing saved OCD snapshot, do not overwrite")
    if not RECEIPT.exists() or json.loads(RECEIPT.read_text("utf8"))["status"]!="OCD_DRC_REDUCED_NATIVE_CAD_NOT_FOR_FAB":
        raise ValueError("Native OCD DRC repair was not verified")
    if sha(LIVE)==BASE_SHA:raise RuntimeError("Native write to project container not flushed; no stale snapshot")
    shutil.copy2(LIVE,SNAP)
    SNAP_META.write_text(json.dumps({"status":"OCM_AND_OCD_SOURCE_PERSISTED_NOT_FOR_FAB",
      "real_saved_native_project":SNAP.name,"sha256":sha(SNAP),
      "source_before":BASE_SHA,"fabrication_approved":False},ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"persisted_native":SNAP.name,"SHA":sha(SNAP)}))

if __name__=="__main__":
    p=argparse.ArgumentParser();q=p.add_mutually_exclusive_group(required=True)
    for opt in ("plan","apply","snapshot"):q.add_argument("--"+opt,action="store_true")
    a=p.parse_args()
    if a.plan:print(json.dumps(plan(),ensure_ascii=False,indent=2))
    elif a.apply:apply()
    else:snapshot()

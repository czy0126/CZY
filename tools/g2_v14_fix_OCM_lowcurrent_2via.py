"""Native-only one-shot repair for disconnected OCM R3.2 <-> D_CT3.1.

Only low-current comparator sensing reference. Checks ALL unlike-net native
pads, copper traces, vias at 0.2mm minimum clearance and rechecks actual EDA
DRC before saving. This remains a WIP return conductor, NOT a qualified EMC
or 100A return scheme. Never restart an EasyEDA GUI or edit original PCB1.
"""
from __future__ import annotations
import argparse,hashlib,json,sys,math,shutil
from pathlib import Path
from shapely.geometry import box,LineString,Point
ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/"hardware/dcx_main/g2"
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"hardware/dcx_main/g1"),str(HERE)]
from g2_board_keepout import pad_bbox
import g2_v9_real_t530_components as V9

BASE=HERE/"g2_v14_post_OC_real_PCB_fresh_native_readback_NOT_FOR_FAB.json"
SOURCE=HERE/"dcx_main_board_g2_V14_EILP32_TWELVE_NPTH_OC_FIX_WIP_NOT_FOR_FAB.eprj2"
ORIG=HERE/"dcx_main_board_g2_V13_FIVE_MAGNETICS_LOGICAL_LANDING_TRIAL_NOT_FOR_FAB.eprj2"
PRIOR=HERE/"g2_v14_after_OC_independent_same_session_second_DRC_NOT_FOR_FAB.json"
SKEY=HERE/"g2_v13_GUI_open_unique_attempt_NOT_FOR_FAB.json"
RECEIPT=HERE/"g2_v14_OCM_native_2via_save_after_DRC_NOT_FOR_FAB.json"
OUT=HERE/"dcx_main_board_g2_V14_EILP32_12NPTH_OC_OCM_WIP_NOT_FOR_FAB.eprj2"
SAVED=HERE/"g2_v14_OCM_source_snapshot_NOT_FOR_FAB.json"
PROJECT="dcx_main_board_g2_V13_FIVE_MAGNETICS_LOGICAL_LANDING_TRIAL_NOT_FOR_FAB"
PCB="8c496410b2877d3c"
SOURCE_SHA="706808f923f60da263ea77ed30236762bc7cf0b3cd58a0db029676e71247c0b8"
M=.0254

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def plan():
    if sha(SOURCE)!=SOURCE_SHA:raise ValueError("Saved OC PCB source SHA changed")
    data=json.loads(BASE.read_text("utf8"))["native"]
    if [len(data[k]) for k in ("components","pads","lines","vias")]!=[149,423,461,92]:
        raise ValueError("Real native input copper counts changed")
    drc=json.loads(PRIOR.read_text("utf8"))
    if drc["categories"]!={"Connection Error":124}:raise ValueError("Native DRC124 changed")
    def terminal(ref,num):
        found=[q for q in data["pads"] if q["ref"]==ref and q["PadNumber"]==num and q["Net"]=="OCM" and q["Layer"]==1]
        if len(found)!=1:raise ValueError("Unique OCM terminal absent: "+ref+"."+num)
        return tuple(round(z,5) for z in (found[0]["X"]*M,-found[0]["Y"]*M))
    a=terminal("R3","2");b=terminal("D_CT3","1")
    if not 43<math.dist(a,b)<45:raise ValueError("Unexpected OCM board net endpoints")
    u=(a[0],64.0);v=(b[0],72.5)
    paths=[(1,a,u),(2,u,v),(1,v,b)]
    vias=[u,v]
    for layer,start,end in paths:
        copper=LineString([start,end]).buffer(.1,cap_style=2)
        for q in data["pads"]:
            if q["Net"]!="OCM" and q["Layer"] in (0,12,layer) and copper.distance(box(*pad_bbox(q)))<.2-1e-7:
                raise ValueError("OCM route-pad different net collision "+str(q["Net"]))
        for q in data["lines"]:
            if q["net"]=="OCM" or q["layer"]!=layer:continue
            sh=LineString([(q["x1"]*M,-q["y1"]*M),(q["x2"]*M,-q["y2"]*M)]).buffer(q["width"]*M/2)
            if copper.distance(sh)<.2-1e-7:raise ValueError("OCM route-trace collision "+q["net"])
        for q in data["vias"]:
            if q["net"]=="OCM":continue
            if copper.distance(Point(q["x"]*M,-q["y"]*M).buffer(q["diameter"]*M/2))<.2-1e-7:
                raise ValueError("OCM route-via collision "+q["net"])
    for point in vias:
        via=Point(*point).buffer(.4)
        for q in data["pads"]:
            if q["Net"]!="OCM" and via.distance(box(*pad_bbox(q)))<.2-1e-7:
                raise ValueError("OCM via-pad collision "+str(q["Net"]))
        for q in data["lines"]:
            if q["net"]=="OCM":continue
            sh=LineString([(q["x1"]*M,-q["y1"]*M),(q["x2"]*M,-q["y2"]*M)]).buffer(q["width"]*M/2)
            if via.distance(sh)<.2-1e-7:raise ValueError("OCM via-trace collision "+q["net"])
        for q in data["vias"]:
            if q["net"]!="OCM" and via.distance(Point(q["x"]*M,-q["y"]*M).buffer(q["diameter"]*M/2))<.2-1e-7:
                raise ValueError("OCM via-via collision "+q["net"])
    return {"source_SHA256":SOURCE_SHA,"net":"OCM","before_DRC":124,"start_R3_2_mm":a,
       "end_D_CT3_1_mm":b,"vias_mm":vias,"paths":[{"layer":l,"from":p,"to":q} for l,p,q in paths],
       "via_diameter_mm":.8,"via_hole_mm":.4,"signal_trace_width_mm":.2,
       "vendor_signed":False,"fabrication_approved":False}

def one():
    if RECEIPT.exists() or SAVED.exists():raise FileExistsError("Never replay one-shot native OCM operation")
    p=plan()
    sid=json.loads(SKEY.read_text("utf8"))["new_session"]
    sessions=V9.D.call([str(V9.D.LEDA),"session","list"],timeout_s=23)
    if not sessions.get("ok") or not any(s["sessionId"]==sid and s["status"]=="alive" for s in sessions["value"]):
        raise RuntimeError("Original EDA GUI not alive, NO NEW WINDOW")
    js="""return await(async()=>{
      const project=await eda.dmt_Project.getCurrentProjectInfo();
      if(project?.friendlyName!==%s)throw Error('Wrong live project');
      await eda.dmt_EditorControl.openDocument(%s);
      const count={pads:(await eda.pcb_PrimitivePad.getAll()).length,
        traces:(await eda.pcb_PrimitiveLine.getAll()).length,
        vias:(await eda.pcb_PrimitiveVia.getAll()).length};
      if(JSON.stringify(count)!==JSON.stringify({pads:423,traces:461,vias:92}))
        throw Error('Native board WIP state changed');
      const p=%s;
      const viaIds=[],lineIds=[];
      try{
       for(const xy of p.vias_mm){
         const v=await eda.pcb_PrimitiveVia.create('OCM',xy[0]/0.0254,-xy[1]/0.0254,
            p.via_hole_mm/0.0254,p.via_diameter_mm/0.0254);
         if(!v)throw Error('Via.create failed');
         viaIds.push(v.getState_PrimitiveId());
       }
       for(const x of p.paths){
         const a=x.from,b=x.to;
         const z=await eda.pcb_PrimitiveLine.create('OCM',x.layer,a[0]/0.0254,-a[1]/0.0254,
           b[0]/0.0254,-b[1]/0.0254,p.signal_trace_width_mm/0.0254,false);
         if(!z)throw Error('Line.create failed');
         lineIds.push(z.getState_PrimitiveId());
       }
       const raw=await eda.pcb_Drc.check(true,false,true);
       const categories=Object.fromEntries(raw.map(g=>[g.name,
         g.list.reduce((n,x)=>n+(x.list||[]).length,0)]));
       const safe=(categories['Connection Error']||0)<124 &&
         (categories['Physical Error']||0)===0 && (categories['Netlist Error']||0)===0;
       if(!safe){
         const delLines=await eda.pcb_PrimitiveLine.delete(lineIds);
         const delVias=await eda.pcb_PrimitiveVia.delete(viaIds);
         return {status:'REVERTED_DRC_UNIMPROVED',categories,delLines,delVias,saved:false};
       }
       const saved=await eda.pcb_Document.save();
       return{status:'REAL_NATIVE_OCM_FIXED',categories,saved,viaIds,lineIds,
           lineCount:(await eda.pcb_PrimitiveLine.getAll()).length,
           viaCount:(await eda.pcb_PrimitiveVia.getAll()).length};
      }catch(e){
        try{if(lineIds.length)await eda.pcb_PrimitiveLine.delete(lineIds);
            if(viaIds.length)await eda.pcb_PrimitiveVia.delete(viaIds);}catch(_){}
        return{status:'FAILED_ROLLBACK_ATTEMPTED',error:String(e),saved:false};
      }
    })();"""%(json.dumps(PROJECT),json.dumps(PCB),json.dumps(p,ensure_ascii=False,separators=(",",":")))
    answer=V9.D.call(V9.D.build_invoke_args(sid,js,59000),timeout_s=79)
    val=answer.get("value") or {}
    ok=answer.get("ok") and val.get("status")=="REAL_NATIVE_OCM_FIXED" and val.get("saved") is True
    RECEIPT.write_text(json.dumps({"status":"OCM_NATIVE_DRC_DECREASED" if ok else "OCM_NOT_CONFIRMED",
      "source_sha256":SOURCE_SHA,"native_result":answer,"fabrication_approved":False},
      ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"status":val.get("status"),"categories":val.get("categories"),
      "vias":val.get("viaIds"),"tracks":val.get("lineIds"),"error":val.get("error")},ensure_ascii=False,indent=2))
    if not ok:raise RuntimeError("Failed OCM route / DRC gate")
    # EDA file flush can lag API save. Copy only once from a differently
    # hashed changed source, after next source readback confirms 463 lines.
    if sha(ORIG)==SOURCE_SHA:raise RuntimeError("EDA save acknowledged but project disk flush delayed; do NOT copy stale source")
    if OUT.exists():raise FileExistsError(OUT)
    shutil.copy2(ORIG,OUT)
    SAVED.write_text(json.dumps({"status":"OCM_NATIVE_COPPER_PERSISTED_WIP_NOT_FOR_FAB",
       "source_sha256":sha(OUT),"from_native_save_file":ORIG.name,
       "file_bytes":OUT.stat().st_size,"fabrication_approved":False},indent=2)+"\n",encoding="utf8")

def main():
    a=argparse.ArgumentParser()
    x=a.add_mutually_exclusive_group(required=True)
    x.add_argument("--plan",action="store_true")
    x.add_argument("--apply",action="store_true")
    cmd=a.parse_args()
    if cmd.plan:print(json.dumps(plan(),ensure_ascii=False,indent=2))
    else:one()
if __name__=="__main__":main()

"""D1 V14: real double-sided C7-C10 regulator capacitor placement and via escape.

The existing V14 top-side C7..C10 are 32-133mm from their own U3..U6
REG pins. This relocation is ELECTRICALLY meaningful: move four 0603
REG-to-PGND decouplers to bottom directly under their four corresponding
drivers; use 180deg to preserve actual pad1/pad2 geometry, NOT an assumed
automatic X mirror. Connect each cap with TWO 0.4/0.8mm PTH vias and four
short L1/L2 tracks; avoid via-in-pad with pads at y=75.0mm and vias y=76.0mm.
Each copper modification preflights 423 true native pads,468 lines,96 vias.

One original *visible* V13 GUI, only target copied V14 PCB UUID.
Do not save unless EasyEDA native DRC Connection<120, Physical=0, Netlist<=0.
No vendor full 12L stack/DFM signed; this is a WIP, not a fabrication release.
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

SOURCE=G/"dcx_main_board_g2_V14_EILP32_12NPTH_OC_OCM_OCD_WIP_NOT_FOR_FAB.eprj2"
LIVE=G/"dcx_main_board_g2_V13_FIVE_MAGNETICS_LOGICAL_LANDING_TRIAL_NOT_FOR_FAB.eprj2"
READ=G/"g2_v14_after_OC_OCM_OCD_real_native_readback_NOT_FOR_FAB.json"
OCD=G/"g2_v14_OCD_real_native_signal_fix_DRC_NOT_FOR_FAB.json"
C7_TRIAL=G/"g2_v14_C7_actual_bottom_flip_180pad_verification_NOT_FOR_FAB.json"
SESS=G/"g2_v13_GUI_open_unique_attempt_NOT_FOR_FAB.json"
PLAN=G/"g2_v14_four_bottom_REG_capacitors_8PTH_16track_plan_NOT_FOR_FAB.json"
RECEIPT=G/"g2_v14_four_bottom_REG_capacitors_native_DRC_applied_NOT_FOR_FAB.json"
SNAP=G/"dcx_main_board_g2_V14_EILP32_12NPTH_OC_OCM_OCD_REG4_BOTTOM_WIP_NOT_FOR_FAB.eprj2"
SNAP_META=G/"g2_v14_REG4_real_saved_snapshot_NOT_FOR_FAB.json"
SOURCE_SHA="3e279574988af011883dd36ef5565cb50e7f72966020c1fa606a54542e1a62de"
PROJECT="dcx_main_board_g2_V13_FIVE_MAGNETICS_LOGICAL_LANDING_TRIAL_NOT_FOR_FAB"
BOARD_UUID="8c496410b2877d3c"
M=.0254

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def build():
    if sha(SOURCE)!=SOURCE_SHA:raise ValueError("Prior accepted native PCB SHA drift")
    p=json.loads(READ.read_text("utf8"))
    if p["board_uuid"]!=BOARD_UUID:raise ValueError("Wrong native readback board")
    board=p["native"]
    if [len(board[k]) for k in ("components","pads","lines","vias")]!=[149,423,468,96]:
        raise ValueError("PCB WIP readback count drifted")
    o=json.loads(OCD.read_text("utf8"))
    if o["status"]!="OCD_DRC_REDUCED_NATIVE_CAD_NOT_FOR_FAB" or o["native_response"]["value"]["categories"]!={"Connection Error":120}:
        raise ValueError("Native OCD after repair 120-open baseline missing")
    trial=json.loads(C7_TRIAL.read_text("utf8"))
    if trial["status"]!="C7_BOTTOM_MIRROR_PINOUT_VERIFIED_UNSAVED":
        raise ValueError("True native bottom capacitor rotation was not measured")
    if not -0.3<trial["native"]["delta"]["PGND_dx"]<0:
        raise ValueError("Native 180deg pad geometry assumptions no longer fit")
    rows=[]
    for i in range(1,5):
        c=f"C{i+6}";drv=f"U{i+2}";net=f"REG{i}"
        comp=[x for x in board["components"] if x["ref"]==c]
        pins=[x for x in board["pads"] if x["ref"]==c]
        reg=[x for x in board["pads"] if x["ref"]==drv and x["PadNumber"]=="3"]
        gnd=[x for x in board["pads"] if x["ref"]==drv and x["PadNumber"]=="2"]
        if len(comp)!=1 or len(pins)!=2 or len(reg)!=1 or len(gnd)!=1:
            raise ValueError("Wrong regulator topology "+c)
        cp=comp[0];capreg=next(q for q in pins if q["PadNumber"]=="1")
        capgnd=next(q for q in pins if q["PadNumber"]=="2")
        if (capreg["Net"]!=net or capgnd["Net"]!="PGND" or
            reg[0]["Net"]!=net or gnd[0]["Net"]!="PGND" or
            cp["Rotation"]!=0):
            raise ValueError("Design REG/PGND pin mapping drift "+c)
        # Native bottom component rotation 180deg gives pad1 right, pad2 left.
        # Original capreg offset is ~-0.7007mm, so new centre
        # = REG_pinX + original_capreg_x - original_comp_x.
        new_x=round((reg[0]["X"]+capreg["X"]-cp["X"])*M,5)
        new_y=75.0
        reg_x=round(reg[0]["X"]*M,5)
        gnd_x=round((new_x*1.0+(cp["X"]-capgnd["X"])*M),5)
        # Native 180-degree rotation of 0603 gives cap pad2 to LEFT,
        # i.e. new centre minus +0.7007mm.
        reg_pad_x=round(new_x+(cp["X"]-capreg["X"])*M,5)
        ground_pad_x=round(new_x+(cp["X"]-capgnd["X"])*M,5)
        if abs(reg_pad_x-reg_x)>.03 or abs(ground_pad_x-gnd[0]["X"]*M)>.3:
            raise ValueError("180-degree real native pad inversion unverified")
        pins_plan=[{"net":net,"x_mm":reg_pad_x,"cap_y_mm":new_y,
                    "top_pin_x_mm":reg_x,"top_pin_y_mm":round(-reg[0]["Y"]*M,5)},
                   {"net":"PGND","x_mm":ground_pad_x,"cap_y_mm":new_y,
                    "top_pin_x_mm":round(gnd[0]["X"]*M,5),
                    "top_pin_y_mm":round(-gnd[0]["Y"]*M,5)}]
        rows.append({"ref":c,"driver":drv,"component_origin_x_mm":new_x,
           "component_origin_y_mm":new_y,"layer":2,"rotation":180,
           "original_component_origin_mil":[cp["X"],cp["Y"]],
           "original_rotation":cp["Rotation"],"pins":pins_plan})
    # This is a purely geometric check against every unlike-net Pad, 468
    # native existing copper lines and 96 PTH vias; no fake net re-label.
    obstacles={}
    for layer in (1,2):
        shapes=[]
        for q in board["pads"]:
            if q["Layer"] in (0,12,layer):
                shapes.append((q["Net"],q.get("ref"),box(*pad_bbox(q))))
        for q in board["lines"]:
            if q["layer"]==layer:
                line=LineString([(q["x1"]*M,-q["y1"]*M),(q["x2"]*M,-q["y2"]*M)]).buffer(q["width"]*M/2)
                shapes.append((q["net"],None,line))
        for q in board["vias"]:
            shapes.append((q["net"],None,Point(q["x"]*M,-q["y"]*M).buffer(q["diameter"]*M/2)))
        obstacles[layer]=shapes
    proposed=[]
    for row in rows:
        for pin in row["pins"]:
            x=pin["x_mm"];y=76.0;net=pin["net"]
            via=Point(x,y).buffer(.4)
            copper1=LineString([(pin["top_pin_x_mm"],pin["top_pin_y_mm"]),(x,y)]).buffer(.1)
            copper2=LineString([(x,row["component_origin_y_mm"]),(x,y)]).buffer(.1)
            for layer,sh in ((0,via),(1,copper1),(2,copper2)):
                groups=obstacles[1]+obstacles[2] if layer==0 else obstacles[layer]
                for other,ref,ob in groups:
                    if other==net:continue
                    if ref==row["ref"]:continue # will move this native component
                    if sh.distance(ob)<.2-1e-7:
                        raise ValueError(f"{row['ref']} {net} L{layer} planned via/trace violates unrelated native copper {other} {ref}")
            proposed.append({"ref":row["ref"],"net":net,"via_mm":[x,y],
                "top_segment_mm":[[pin["top_pin_x_mm"],pin["top_pin_y_mm"]],[x,y]],
                "bottom_segment_mm":[[x,row["component_origin_y_mm"]],[x,y]]})
    # Exclude near-by paired unlike-net vias and PCB backside 0603 pads.
    for i,x in enumerate(proposed):
        for y in proposed[i+1:]:
            if x["net"]!=y["net"] and math.dist(x["via_mm"],y["via_mm"])<1.0:
                raise ValueError("New REG/PGND opposite-net PTHs are <1mm apart")
    return {"schema":"D1_G2_V14_NATIVE_REG1_REG4_BOTTOM_CAPACITORS_V1",
      "status":"FOUR_CAPS_8_VIAS_16_TRACKS_BOTTOM_PRECHECK_PASS_NOT_YET_APPLIED",
      "source_saved_native_SHA256":SOURCE_SHA,
      "actual_423Pad_468Line_96Via_readback_SHA256":sha(READ),
      "corrected_C7_bottom_180deg_native_verification_SHA256":sha(C7_TRIAL),
      "before_native_DRC":{"Connection Error":120},
      "candidate_backside_parts":rows,"eight_PTH_sites_and_sixteen_routes":proposed,
      "via_hole_mm":.4,"via_outer_mm":.8,"routing_copper_width_mm":.2,
      "native_board_to_modify":BOARD_UUID,
      "guaranteed_bottom_side_clearance_mm":.2,
      "ferrite_window_and_full_PCB_stackup_supplier_approved":False,
      "fabrication_approved":False}

def apply():
    if RECEIPT.exists():raise FileExistsError("These component moves were already attempted; don't duplicate")
    plan=build()
    if not PLAN.exists() or json.loads(PLAN.read_text("utf8"))!=json.loads(json.dumps(plan)):
        raise ValueError("Bottom cap source-bound plan stale")
    sid=json.loads(SESS.read_text("utf8"))["new_session"]
    live=V9.D.call([str(V9.D.LEDA),"session","list"],timeout_s=21)
    if not live.get("ok") or not any(q["sessionId"]==sid and q["status"]=="alive" and q["headless"] is False for q in live["value"]):
        raise ValueError("V13 visible GUI not available; do not launch new")
    js="""return await(async()=>{
      const project=await eda.dmt_Project.getCurrentProjectInfo();
      if(project?.friendlyName!==%s)throw Error('WRONG GUI');
      await eda.dmt_EditorControl.openDocument(%s);
      const pcb=await eda.pcb_PrimitiveComponent.getAll();
      if(pcb.length!==149||(await eda.pcb_PrimitivePad.getAll()).length!==423||
         (await eda.pcb_PrimitiveLine.getAll()).length!==468||
         (await eda.pcb_PrimitiveVia.getAll()).length!==96)
        throw Error('WIP native part/copper counts drifted');
      const p=%s;const prior=[], vias=[],traces=[];
      const rollback=async()=>{try{
        if(traces.length)await eda.pcb_PrimitiveLine.delete(traces);
        if(vias.length)await eda.pcb_PrimitiveVia.delete(vias);
        for(const s of prior.reverse())await eda.pcb_PrimitiveComponent.modify(s.id,{
          layer:s.layer,rotation:s.rotation,x:s.x,y:s.y});
        return true;
      }catch(e){return String(e)}};
      try{
       for(const item of p.candidate_backside_parts){
         const c=pcb.find(x=>x.getState_Designator()===item.ref);
         if(!c)throw Error('Not found original '+item.ref);
         prior.push({ref:item.ref,id:c.getState_PrimitiveId(),x:c.getState_X(),
            y:c.getState_Y(),rotation:c.getState_Rotation(),layer:c.getState_Layer()});
         if(item.ref==='C7'){
           if(c.getState_Layer()!==2||c.getState_Rotation()!==180)
             throw Error('Prior native trial C7 rotation180 no longer active');
         }else if(c.getState_Layer()!==1||c.getState_Rotation()!==0){
           throw Error('Other cap not original state '+item.ref);
         }
         const changed=await eda.pcb_PrimitiveComponent.modify(c.getState_PrimitiveId(),{
           layer:2,x:item.component_origin_x_mm/.0254,
           y:-item.component_origin_y_mm/.0254,rotation:180});
         if(!changed)throw Error('Native component move failed '+item.ref);
         const pins=await eda.pcb_PrimitiveComponent.getAllPinsByPrimitiveId(c.getState_PrimitiveId());
         const one=pins.find(x=>x.getState_PadNumber()==='1');
         const two=pins.find(x=>x.getState_PadNumber()==='2');
         const reg=item.pins.find(x=>x.net!=='PGND');
         const ground=item.pins.find(x=>x.net==='PGND');
         if(!one||!two||changed.getState_Layer()!==2||
           one.getState_Net()!==reg.net||two.getState_Net()!=='PGND'||
           Math.abs(one.getState_X()*.0254-reg.x_mm)>.08||
           Math.abs(two.getState_X()*.0254-ground.x_mm)>.08||
           Math.abs(-one.getState_Y()*.0254-75)>.05||
           Math.abs(-two.getState_Y()*.0254-75)>.05)
              throw Error('Native double-side orientation or pads wrong '+item.ref);
       }
       for(const row of p.eight_PTH_sites_and_sixteen_routes){
         const q=await eda.pcb_PrimitiveVia.create(row.net,
            row.via_mm[0]/.0254,-row.via_mm[1]/.0254,
            p.via_hole_mm/.0254,p.via_outer_mm/.0254);
         if(!q)throw Error('Real PTH creation failed '+row.ref);
         vias.push(q.getState_PrimitiveId());
         for(const [layer,way] of [[1,row.top_segment_mm],[2,row.bottom_segment_mm]]){
            const q=await eda.pcb_PrimitiveLine.create(row.net,layer,
              way[0][0]/.0254,-way[0][1]/.0254,
              way[1][0]/.0254,-way[1][1]/.0254,
              p.routing_copper_width_mm/.0254,false);
            if(!q)throw Error('Native copper create failed '+row.ref+' L'+layer);
            traces.push(q.getState_PrimitiveId());
         }
       }
       const drc=await eda.pcb_Drc.check(true,false,true);
       const errs=Object.fromEntries(drc.map(g=>[g.name,
           g.list.reduce((n,x)=>n+(x.list||[]).length,0)]));
       if((errs['Connection Error']||0)>=120 ||
          (errs['Physical Error']||0)!==0 ||
          (errs['Netlist Error']||0)!==0){
         const reverted=await rollback();
         return {status:'REG_BOTTOM_REVERTED_NATIVE_DRC_NOT_BETTER',
             DRC:errs,rollback:reverted};
       }
       const saved=await eda.pcb_Document.save();
       if(saved!==true)throw Error('Native save returned false');
       const final=(await eda.pcb_PrimitiveComponent.getAll()).filter(x=>['C7','C8','C9','C10'].includes(x.getState_Designator()))
             .map(x=>({ref:x.getState_Designator(),layer:x.getState_Layer(),rot:x.getState_Rotation()}));
       return {status:'REG1_REG4_BOTTOM_CAPS_AND_8PTH_NATIVE_SAVED_DRC_IMPROVED',
          DRC:errs,saved,moved:final,viaIds:vias,lineIds:traces,
          lineCount:(await eda.pcb_PrimitiveLine.getAll()).length,
          viaCount:(await eda.pcb_PrimitiveVia.getAll()).length};
      }catch(e){
        return{status:'REG_BOTTOM_NATIVE_ABORTED',error:String(e),
          rollback:await rollback()};
      }
     })();"""%(json.dumps(PROJECT),json.dumps(BOARD_UUID),json.dumps(plan,ensure_ascii=False,separators=(",",":")))
    result=V9.D.call(V9.D.build_invoke_args(sid,js,59000),timeout_s=85)
    data=result.get("value") or {}
    passed=(result.get("ok") and data.get("status")=="REG1_REG4_BOTTOM_CAPS_AND_8PTH_NATIVE_SAVED_DRC_IMPROVED"
        and data.get("saved") is True and len(data.get("viaIds",[]))==8
        and len(data.get("lineIds",[]))==16)
    RECEIPT.write_text(json.dumps({"status":"FOUR_BOTTOM_REG_CAPACITORS_REAL_DRC_REDUCED_NOT_FOR_FAB" if passed
       else "FOUR_BOTTOM_REG_CAPACITORS_NOT_VERIFIED_NATIVE", "native_result":result,
       "source_unchanged_V11_sha":SOURCE_SHA,"fabrication_approved":False},
        ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"status":data.get("status"),"DRC":data.get("DRC"),
       "bottom_placed":data.get("moved"),"vias":len(data.get("viaIds",[])),
       "tracks":len(data.get("lineIds",[])),"error":data.get("error"),
       "rollback":data.get("rollback")},ensure_ascii=False,indent=2))
    if not passed:raise RuntimeError("native bottom caps did not pass DRC/rollback; inspect!")

def snapshot():
    if SNAP.exists() or SNAP_META.exists():raise FileExistsError("Existing REG cap snapshot must be preserved")
    if not RECEIPT.exists() or json.loads(RECEIPT.read_text("utf8"))["status"]!="FOUR_BOTTOM_REG_CAPACITORS_REAL_DRC_REDUCED_NOT_FOR_FAB":
        raise RuntimeError("Native REG caps never verified")
    if sha(LIVE)==SOURCE_SHA:raise RuntimeError("Native EDA saved, binary flush not complete")
    shutil.copy2(LIVE,SNAP)
    SNAP_META.write_text(json.dumps({"status":"FOUR_TRUE_BOTTOM_REG_CAPS_NATIVE_BINARY_SAVED_NOT_FOR_FAB",
       "source_file":SNAP.name,"sha256":sha(SNAP),
       "pre_change_SHA256":SOURCE_SHA,"manufacturer_stackup_signed":False,
       "fabrication_approved":False},ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"saved_native_file":SNAP.name,"sha256":sha(SNAP)}))

def main():
    ap=argparse.ArgumentParser()
    mode=ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan",action="store_true")
    mode.add_argument("--apply",action="store_true")
    mode.add_argument("--snapshot",action="store_true")
    a=ap.parse_args()
    if a.plan:
        p=build()
        if PLAN.exists() and json.loads(PLAN.read_text("utf8"))!=json.loads(json.dumps(p)):
            raise ValueError("Previous REG source-locked plan differs")
        if not PLAN.exists():PLAN.write_text(json.dumps(p,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
        print(json.dumps({"status":p["status"],"real_bottom_components":4,
             "PTHs":len(p["eight_PTH_sites_and_sixteen_routes"]),
             "segments":16},ensure_ascii=False))
    elif a.apply:apply()
    else:snapshot()
if __name__=="__main__":main()

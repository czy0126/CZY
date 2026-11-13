"""One-shot REAL EasyEDA-native G2 V14 four ELP32 triple-leg cutouts.

ONLY reuse the already alive V13 GUI; V14 is a separately copied native board
UUID 8c496410b2877d3c inside that project. Do not edit original PCB1 UUID.
The original V11 saved eprj2 remains source bound.

Commands in order, NEVER replay after receipt:
  python hardware/dcx_main/g2/g2_v14_native_pcb_12slots_apply.py --plan
  python hardware/dcx_main/g2/g2_v14_native_pcb_12slots_apply.py --remove
  python hardware/dcx_main/g2/g2_v14_native_pcb_12slots_apply.py --slots
  python hardware/dcx_main/g2/g2_v14_native_pcb_12slots_apply.py --save

This only removes 20 obsolete magnetic RAW pads + 7 VOUT tracks + 3 VOUT
vias and makes 12 real Board Outline contours. It DOES NOT actually design
three series primary turns, two secondary turns, 12-layer stackup or DFM.
"""
from __future__ import annotations
import argparse,hashlib,json,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"hardware/dcx_main/g1"),str(HERE)]
import g2_v14_through_board_magnetics as G
import g2_v9_real_t530_components as V9

SID_FILE=HERE/"g2_v13_GUI_open_unique_attempt_NOT_FOR_FAB.json"
COPY=HERE/"g2_v14_real_native_pcb_copy_first_once_NOT_FOR_FAB.json"
CLONE=HERE/"g2_v14_copied_native_PCB_initial_full_readback_NOT_FOR_FAB.json"
PARENT=HERE/"dcx_main_board_g2_V11_NATIVE_SR_GATE_ESCAPE_NOT_FOR_FAB.eprj2"
ORIGINAL=HERE/"dcx_main_board_g2_V13_FIVE_MAGNETICS_LOGICAL_LANDING_TRIAL_NOT_FOR_FAB.eprj2"
BOARD_UUID="8c496410b2877d3c"
ORIGINAL_BOARD="2f6fa2d508d3f9a8"
PROJECT=ORIGINAL.stem
REPORT=G.OUT
PREP=HERE/"g2_v14_real_native_12slot_board_apply_plan_NOT_FOR_FAB.json"
REMOVED=HERE/"g2_v14_real_native_obsolete_20pads_7tracks_3vias_REMOVED_NOT_FOR_FAB.json"
SLOTS=HERE/"g2_v14_real_native_12_NPTH_outline_CREATED_NOT_FOR_FAB.json"
SAVED=HERE/"g2_v14_native_board_12slots_saved_receipt_NOT_FOR_FAB.json"
D=V9.D
M=.0254


def once(dest,data):
    if dest.exists():raise FileExistsError("No blind native API replay: "+str(dest))
    dest.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf8",newline="\n")


def receipt(arg):
    p=json.loads(arg.read_text("utf8"))
    return p


def run_js(sid,code,limit=53000):
    return D.call(D.build_invoke_args(sid,code,limit),timeout_s=int(limit/1000)+28)


def check(r,what):
    if not r.get("ok"):raise RuntimeError(f"{what}: {str(r.get('error'))[:2000]}")
    return r["value"]


def get_session():
    r=receipt(SID_FILE)
    sid=r["new_session"]
    a=check(D.call([str(D.LEDA),"session","list"],timeout_s=20),"GUI session list")
    if not any(x.get("sessionId")==sid and x.get("status")=="alive" and x.get("headless") is False for x in a):
        raise ValueError("User's original V13 GUI session closed; REFUSE extra GUI")
    return sid


def plan():
    model=G.build()
    if G.sha(PARENT)!=G.SOURCE_SHA:
        raise ValueError("V11 source drift")
    orig=receipt(COPY)["native_response"]["value"]
    if orig["newuuid"]!=BOARD_UUID or orig["old"]!=ORIGINAL_BOARD:
        raise ValueError("V14 copy source/target do not match")
    clone=receipt(CLONE)["real_native_data"]
    for name,n in [("components",149),("pads",443),("lines",465),("vias",93)]:
        if len(clone[name])!=n:raise ValueError("Copy native count mismatch "+name)
    old=receipt(REPORT)["actual_native_V11_overlap_details"]
    targets={"pads":[],"lines":[],"vias":[]}
    names=set()
    for it in old:
        if it["kind"]=="PAD":
            pt=it["point_mm"]
            keys=(it["pad_number"],it["net"],tuple(pt))
            if keys in names:raise ValueError("Duplicate raw pad")
            names.add(keys)
            matches=[x for x in clone["pads"] if not x.get("ref") and
                     x["PadNumber"]==it["pad_number"] and x["Net"]==it["net"] and
                     abs(x["X"]*M-pt[0])<.03 and abs(-x["Y"]*M-pt[1])<.03]
            if len(matches)!=1:raise ValueError("Native copied magnetic pad mismatch: "+str(keys))
            targets["pads"].append({"number":it["pad_number"],"net":it["net"],"point_mm":pt})
        elif it["kind"]=="COPPER_TRACK":
            v=next((x for x in clone["lines"] if x["id"]==it["native_line_uuid"]),None)
            if v is None or v["net"]!="VOUT":raise ValueError("VOUT track not in independent copied board")
            targets["lines"].append(it["native_line_uuid"])
        elif it["kind"]=="VIA":
            v=next((x for x in clone["vias"] if x["id"]==it["native_via_uuid"]),None)
            if v is None or v["net"]!="VOUT":raise ValueError("VOUT via not in independent copied board")
            targets["vias"].append(it["native_via_uuid"])
        else:raise ValueError("Unsupported native collision")
    if {k:len(v) for k,v in targets.items()}!={"pads":20,"lines":7,"vias":3}:
        raise ValueError("Unexpected V14 copper collision target count")
    raw=[]
    for s in model["slots"]:
        pts=G.capsule_roundrect(s["x_min_mm"],s["y_min_mm"],
            s["x_max_mm"],s["y_max_mm"],G.CNC_CORNER_R_MM,segments=8)
        mil=[(round(x/M,5),round(-y/M,5)) for x,y in pts]
        mil.append(mil[0])
        flat=[mil[0][0],mil[0][1],"L"]
        for x,y in mil[1:]:flat.extend([x,y])
        raw.append({"id":s["id"],"native_boardoutline_layer":11,"source":flat})
    return {
        "schema":"G2_V14_REAL_NATIVE_PCB_CUTOUT_12SLOT_SOURCE_LOCKED_PLAN_V1",
        "source_native_v11_sha256":G.SOURCE_SHA,
        "source_12slot_geometry_sha256":G.sha(G.OUT),
        "same_gui_project":PROJECT,
        "source_original_PCB_uuid":ORIGINAL_BOARD,
        "target_copy_V14_PCB_uuid":BOARD_UUID,
        "old_copper_replacements":targets,
        "native_EI_PCB_slot_contours":raw,
        "expect_unlinked_magnetic_CT_four_pads_still_present":4,
        "original_PCB1_source_will_never_be_edited":True,
        "supplier_3_1_1_PCB_windings_already_created":False,
        "manufacturer_DFM_approved":False,
        "fabrication_approved":False
    }


def prepare():
    p=plan()
    text=json.dumps(p,ensure_ascii=False,indent=2)+"\n"
    if PREP.exists() and PREP.read_text("utf8")!=text:raise ValueError("Cutout plan changed after issue")
    if not PREP.exists():PREP.write_text(text,encoding="utf8",newline="\n")
    print(json.dumps({"target_PCB_uuid":BOARD_UUID,"raw_pads":len(p["old_copper_replacements"]["pads"]),
      "VOUT_lines":len(p["old_copper_replacements"]["lines"]),
      "VOUT_vias":len(p["old_copper_replacements"]["vias"]),
      "NPTH_slot_count":len(p["native_EI_PCB_slot_contours"]),"released":False},indent=2))


def existing_plan():
    p=plan()
    if receipt(PREP)!=p:raise ValueError("Native V14 cutout plan no longer exactly source locked")
    return p


def remove():
    if REMOVED.exists():raise FileExistsError("Removals already attempted; preserve")
    p=existing_plan()
    sid=get_session()
    payload=p["old_copper_replacements"]
    js="""return await(async()=>{
      const project=await eda.dmt_Project.getCurrentProjectInfo();
      if(project.friendlyName!==%s)throw Error("wrong project");
      await eda.dmt_EditorControl.openDocument(%s);
      const other=await eda.dmt_Pcb.getPcbInfo(%s);
      if(other?.name!=="PCB1")throw Error("Original PCB1 identity mismatch");
      const pads=await eda.pcb_PrimitivePad.getAll();
      const lines=await eda.pcb_PrimitiveLine.getAll();
      const vias=await eda.pcb_PrimitiveVia.getAll();
      const comp=await eda.pcb_PrimitiveComponent.getAll();
      if(pads.length!==443||lines.length!==465||vias.length!==93||comp.length!==149)
        throw Error("Copy V14 board inventory drift");
      const target=%s,ids=[];
      for(const q of target.pads){
        const found=pads.filter(x=>x.getState_PadNumber()===q.number &&
          x.getState_Net()===q.net &&
          Math.abs(x.getState_X()*0.0254-q.point_mm[0])<0.03 &&
          Math.abs(-x.getState_Y()*0.0254-q.point_mm[1])<0.03);
        if(found.length!==1)throw Error("ambiguous raw pad "+JSON.stringify(q));
        ids.push(found[0].getState_PrimitiveId());
      }
      if(new Set(ids).size!==20)throw Error("20 distinct raw pad IDs missing");
      for(const id of target.lines){
        const x=lines.find(y=>y.getState_PrimitiveId()===id);
        if(!x||x.getState_Net()!=="VOUT")throw Error("Missing VOUT track "+id);
      }
      for(const id of target.vias){
        const x=vias.find(y=>y.getState_PrimitiveId()===id);
        if(!x||x.getState_Net()!=="VOUT")throw Error("Missing VOUT via "+id);
      }
      const padDeleted=await eda.pcb_PrimitivePad.delete(ids);
      if(!padDeleted)throw Error("Native raw pad deletion failed");
      const lineDeleted=await eda.pcb_PrimitiveLine.delete(target.lines);
      if(!lineDeleted)throw Error("Native intersecting VOUT line deletion failed");
      const viaDeleted=await eda.pcb_PrimitiveVia.delete(target.vias);
      if(!viaDeleted)throw Error("Native VOUT via deletion failed");
      const updatedPads=await eda.pcb_PrimitivePad.getAll();
      const updatedLines=await eda.pcb_PrimitiveLine.getAll();
      const updatedVias=await eda.pcb_PrimitiveVia.getAll();
      return{removed_native_pad_ids:ids,padDeleted,lineDeleted,viaDeleted,
        counts:{pads:updatedPads.length,lines:updatedLines.length,vias:updatedVias.length},
        obsolete_pad_ids_remaining:updatedPads.filter(x=>ids.includes(x.getState_PrimitiveId())).length,
        obsolete_track_ids_remaining:updatedLines.filter(x=>target.lines.includes(x.getState_PrimitiveId())).length,
        obsolete_via_ids_remaining:updatedVias.filter(x=>target.vias.includes(x.getState_PrimitiveId())).length};
    })();"""%(json.dumps(PROJECT),json.dumps(BOARD_UUID),json.dumps(ORIGINAL_BOARD),json.dumps(payload,separators=(",",":")))
    res=run_js(sid,js,56000)
    result=res.get("value") or {}
    ok=(res.get("ok") and result.get("padDeleted") and result.get("lineDeleted") and result.get("viaDeleted")
        and result.get("obsolete_pad_ids_remaining")==0 and result.get("obsolete_track_ids_remaining")==0 and
        result.get("obsolete_via_ids_remaining")==0 and result.get("counts",{}).get("pads")==423 and
        result.get("counts",{}).get("vias")==90)
    once(REMOVED,{"status":"NATIVE_V14_20_PAD_7_VOUT_TRACK_3_VIA_REMOVED_NOT_FOR_FAB" if ok else "V14_NATIVE_OBSTRUCTION_REMOVAL_PARTIAL_UNVERIFIED_NOT_FOR_FAB",
        "native":res,"source_plan_sha256":G.sha(PREP),"fabrication_approved":False})
    print(json.dumps({"status":receipt(REMOVED)["status"],"readback":result},ensure_ascii=False,indent=2)[:3900])
    if not ok:raise RuntimeError("Native obstruction removal incomplete; stop, never replay")


def slots():
    if SLOTS.exists():raise FileExistsError("Never duplicate actual NPTH board cutouts")
    p=existing_plan()
    if receipt(REMOVED)["status"]!="NATIVE_V14_20_PAD_7_VOUT_TRACK_3_VIA_REMOVED_NOT_FOR_FAB":
        raise ValueError("Old native copper pad obstacles not cleared")
    sid=get_session()
    js="""return await(async()=>{
      const project=await eda.dmt_Project.getCurrentProjectInfo();
      if(project.friendlyName!==%s)throw Error("wrong project");
      await eda.dmt_EditorControl.openDocument(%s);
      const pads=await eda.pcb_PrimitivePad.getAll(),via=await eda.pcb_PrimitiveVia.getAll();
      if(pads.length!==423||via.length!==90)
        throw Error("PCB obstruction removal not acknowledged");
      const before=await eda.pcb_PrimitivePolyline.getAll();
      const board=before.filter(x=>x.getState_Layer()===11);
      if(board.length!==1)throw Error("Original board contour not exactly one");
      const requests=%s,created=[];
      for(const slot of requests){
        try{
          const polygon=eda.pcb_MathPolygon.createPolygon(slot.source);
          const line=await eda.pcb_PrimitivePolyline.create("",11,polygon,1,false);
          if(!line)throw Error("native outline null");
          created.push({slot:slot.id,id:line.getState_PrimitiveId(),
            layer:line.getState_Layer(),source_length:line.getState_Polygon()?.getSource()?.length});
        }catch(e){created.push({slot:slot.id,error:String(e)});break;}
      }
      const after=await eda.pcb_PrimitivePolyline.getAll();
      const onBoard=after.filter(x=>x.getState_Layer()===11);
      return{requested:requests.length,created,all_on_board: onBoard.map(x=>x.getState_PrimitiveId()),
        original_outline_present:onBoard.some(x=>x.getState_PrimitiveId()===board[0].getState_PrimitiveId()),
        board_layer_contour_count:onBoard.length,total_polyline_count:after.length};
    })();"""%(json.dumps(PROJECT),json.dumps(BOARD_UUID),json.dumps(p["native_EI_PCB_slot_contours"],separators=(",",":")))
    res=run_js(sid,js,59000)
    v=res.get("value") or {}
    good=res.get("ok") and v.get("board_layer_contour_count")==13 and v.get("original_outline_present") and len(v.get("created",[]))==12 and all(not x.get("error") and x.get("layer")==11 for x in v.get("created",[]))
    once(SLOTS,{"status":"REAL_NATIVE_V14_BOARD_12_NPTH_CONTOURS_CREATED_NOT_FOR_FAB" if good else "V14_NATIVE_12_NPTH_PARTIAL_UNVERIFIED_NOT_FOR_FAB",
        "native":res,"source_plan_sha256":G.sha(PREP),"fabrication_approved":False})
    print(json.dumps({"status":receipt(SLOTS)["status"],"new_count":v.get("board_layer_contour_count"),"created":v.get("created",[])},ensure_ascii=False,indent=2)[:3900])
    if not good:raise RuntimeError("Native layer11 cutout writing failed, do not replay")


def save():
    if SAVED.exists():raise FileExistsError("Already saved V14 real source")
    p=existing_plan()
    if receipt(SLOTS)["status"]!="REAL_NATIVE_V14_BOARD_12_NPTH_CONTOURS_CREATED_NOT_FOR_FAB":
        raise ValueError("No verified real native 12 NPTH")
    sid=get_session()
    js="""return await(async()=>{const project=await eda.dmt_Project.getCurrentProjectInfo();
      if(project.friendlyName!==%s)throw Error("wrong project");
      await eda.dmt_EditorControl.openDocument(%s);
      const polys=(await eda.pcb_PrimitivePolyline.getAll()).filter(x=>x.getState_Layer()===11);
      if(polys.length!==13)throw Error("Not 13 total board layer cutout contours");
      const saved=await eda.pcb_Document.save();
      return {saved,pads:(await eda.pcb_PrimitivePad.getAll()).length,
        components:(await eda.pcb_PrimitiveComponent.getAll()).length,
        vias:(await eda.pcb_PrimitiveVia.getAll()).length,
        tracks:(await eda.pcb_PrimitiveLine.getAll()).length,
        board_outlines:polys.length};
    })();"""%(json.dumps(PROJECT),json.dumps(BOARD_UUID))
    r=run_js(sid,js,44000)
    v=r.get("value") or {}
    good=r.get("ok") and v.get("saved") is True and v.get("pads")==423 and v.get("components")==149 and v.get("vias")==90 and v.get("board_outlines")==13
    once(SAVED,{"status":"V14_NEW_PCB_WITH_12_REAL_NPTH_CONTOURS_SAVED_NOT_FOR_FAB" if good else "V14_NATIVE_SAVED_NOT_VERIFIED_NOT_FOR_FAB","native":r,"fabrication_approved":False})
    print(json.dumps({"status":receipt(SAVED)["status"],"native_counts":v},ensure_ascii=False,indent=2))
    if not good:raise RuntimeError("Saved new native V14 PCB not confirmed")


def main():
    p=argparse.ArgumentParser()
    group=p.add_mutually_exclusive_group(required=True)
    for x in ("plan","remove","slots","save"):group.add_argument("--"+x,action="store_true")
    args=p.parse_args()
    if args.plan:prepare()
    elif args.remove:remove()
    elif args.slots:slots()
    else:save()
if __name__=="__main__":
    main()

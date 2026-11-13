"""Native EasyEDA Pro *library* ELP32 three-leg board-outline cutout prototype.

Uses ONLY the existing visible V13 GUI session; never starts a new window.
Native board documents V11/V12/V13 are NOT changed. The new footprint lives
in the existing test library and contains three BOARD_OUTLINE layer contours,
not an accepted manufacturer footprint nor the real V14 board cutouts.

python hardware/dcx_main/g2/g2_v14_native_elp32_cutout_footprint.py --plan
python hardware/dcx_main/g2/g2_v14_native_elp32_cutout_footprint.py --create
python hardware/dcx_main/g2/g2_v14_native_elp32_cutout_footprint.py --apply
python hardware/dcx_main/g2/g2_v14_native_elp32_cutout_footprint.py --verify
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"hardware/dcx_main/g1"),str(HERE)]
import g2_v14_through_board_magnetics as V14
import g2_v9_real_t530_components as V9

D=V9.D
USER_SESSION=HERE/"g2_v13_GUI_open_unique_attempt_NOT_FOR_FAB.json"
BOARD_V13=HERE/"dcx_main_board_g2_V13_FIVE_MAGNETICS_LOGICAL_LANDING_TRIAL_NOT_FOR_FAB.eprj2"
BOARD_SHA=V14.SOURCE_SHA
NAME="CZY_G2_V14_ELP32_THREE_NPTH_SLOT_BOARDOUTLINE_TRIAL_NOT_FOR_FAB"
LIB="G1_R34_REC10K_v3_TEST"
PLAN=HERE/"g2_v14_native_three_slot_library_plan_NOT_FOR_FAB.json"
CREATED=HERE/"g2_v14_native_three_slot_library_created_once_NOT_FOR_FAB.json"
APPLIED=HERE/"g2_v14_native_three_slot_contours_created_once_NOT_FOR_FAB.json"
VERIFIED=HERE/"g2_v14_native_three_slot_saved_reopened_NOT_FOR_FAB.json"
M=V14.MM_PER_MIL


def write_once(path,data):
    if path.exists():
        raise FileExistsError(f"Evidence already exists; never blind-repeat native API: {path}")
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf8",newline="\n")


def session():
    if V14.sha(BOARD_V13)!=BOARD_SHA:
        raise ValueError("Original existing open V13 PCB changed; do not mutate")
    r=json.loads(USER_SESSION.read_text("utf8"))
    sid=r["new_session"]
    list_reply=D.call([str(D.LEDA),"session","list"],timeout_s=20)
    if not list_reply.get("ok") or not any(
         q.get("sessionId")==sid and q.get("status")=="alive" and not q.get("headless")
         for q in list_reply["value"]):
        raise ValueError("Prior V13 original visible GUI session is not alive; NO additional window")
    return sid


def call(sid,code,timeout=30000):
    return D.call(D.build_invoke_args(sid,code,timeout),timeout_s=max(40,int(timeout/1000)+20))


def check(r,what):
    if not r.get("ok"):
        raise RuntimeError(f"{what}: {r.get('error')}")
    return r["value"]


def path_plan():
    v=V14.build()
    slots=[s for s in v["slots"] if s["device"]=="T1"]
    if [s["leg"] for s in slots]!=["LEFT","CENTRE","RIGHT"]:
        raise ValueError("T1 cutout not exactly three slots")
    # footprint local coord centered at ELP32 nominal mechanical centre.
    local=[]
    for slot in slots:
        coords=V14.capsule_roundrect(slot["x_min_mm"],slot["y_min_mm"],
            slot["x_max_mm"],slot["y_max_mm"],V14.CNC_CORNER_R_MM,segments=8)
        # Source polygon closes by explicitly repeating first vertex.
        coords=[(round((x-V14.CENTERS[0])/M,5),round(-(y-V14.Y)/M,5)) for x,y in coords]
        coords.append(coords[0])
        native=[coords[0][0],coords[0][1],"L"]
        for x,y in coords[1:]:
            native.extend([x,y])
        local.append({"name":slot["leg"],"PCB_layer_id_board_outline":11,
            "native_polygon_source_mil":native,
            "native_line_width_mil":1.0})
    return {
     "schema":"G2_ELP32_NATIVE_BOARD_OUTLINE_3NPTH_SLOT_ONE_FOOTPRINT_PLAN_V1",
     "source_V11_native_sha256":V14.SOURCE_SHA,
     "source_V14_geometry_sha256":V14.sha(V14.OUT),
     "existing_GUI_project_name":BOARD_V13.stem,
     "reuse_existing_V13_GUI_only":True,
     "native_test_library":LIB,"native_footprint_name":NAME,
     "slot_polygons":local,
     "project_PCB_geometry_will_remain_untouched":True,
     "manufacturer_DFM_acceptance":False,
     "native_real_V14_PCB_cutouts_already_applied":False,
     "fabrication_approved":False}


def main():
    a=argparse.ArgumentParser()
    m=a.add_mutually_exclusive_group(required=True)
    for x in ("plan","create","apply","verify"):
        m.add_argument("--"+x,action="store_true")
    z=a.parse_args()
    plan=path_plan()
    if z.plan:
        body=json.dumps(plan,ensure_ascii=False,indent=2)+"\n"
        if PLAN.exists() and PLAN.read_text("utf8")!=body:
            raise ValueError("Existing native mechanical footprint plan changed")
        if not PLAN.exists():PLAN.write_text(body,encoding="utf8",newline="\n")
        print(json.dumps({"status":"THREE_NATIVE_OUTLINE_CONTOURS_PREPARED_NOT_FOR_FAB",
           "outline_count":len(plan["slot_polygons"]),"existing_GUI_reused":True,
           "fabrication_approved":False},ensure_ascii=False))
        return
    if not PLAN.exists() or json.loads(PLAN.read_text("utf8"))!=plan:
        raise ValueError("Source locked three-slot native footprint plan absent/stale")
    sid=session()
    if z.create:
        if CREATED.exists():raise FileExistsError("Footprint was already created; no API replay")
        js="""return await(async()=>{
          const project=await eda.dmt_Project.getCurrentProjectInfo();
          if(project?.friendlyName!==%s)throw Error("Wrong user EDA GUI");
          const uuid=await eda.lib_Footprint.create(%s,%s,[],
             "V14 mechanically routed ELP32 3 E-legs, NOT FABBED / board source unchanged / supplier not approved");
          return {project:project?.friendlyName,lib:%s,uuid};
        })();"""%(json.dumps(BOARD_V13.stem),json.dumps(LIB),json.dumps(NAME),json.dumps(LIB))
        result=call(sid,js)
        write_once(CREATED,{"status":"NATIVE_LIBRARY_CREATE_CONFIRMED_NOT_FOR_FAB"
            if result.get("ok") and (result.get("value") or {}).get("uuid")
            else "NATIVE_LIBRARY_CREATE_NOT_CONFIRMED_NOT_FOR_FAB",
            "native_reply":result,"session_id":sid,"fabrication_approved":False})
        print(json.dumps(CREATED and json.loads(CREATED.read_text("utf8")),ensure_ascii=False)[:3400])
        if not result.get("ok") or not (result.get("value") or {}).get("uuid"):
            raise RuntimeError("Native create did not succeed")
        return
    created=json.loads(CREATED.read_text("utf8"))
    if created["status"]!="NATIVE_LIBRARY_CREATE_CONFIRMED_NOT_FOR_FAB":
        raise ValueError("No independently acknowledged new footprint")
    uuid=created["native_reply"]["value"]["uuid"]
    if z.apply:
        if APPLIED.exists():raise FileExistsError("Three native cutouts already applied; do not duplicate")
        # Open a new TAB in the existing V13 GUI, never a new external window.
        js="""return await(async()=>{
            const project=await eda.dmt_Project.getCurrentProjectInfo();
            if(project?.friendlyName!==%s)throw Error("Wrong V13 GUI");
            await eda.lib_Footprint.openInEditor(%s,%s);
            const before=await eda.pcb_PrimitivePolyline.getAll();
            const pad=await eda.pcb_PrimitivePad.getAll();
            if(before.length!==0||pad.length!==0)throw Error("New mechanical footprint not empty");
            const routes=%s;
            const made=[];
            for(const r of routes){
               try{
                 const polygon=eda.pcb_MathPolygon.createPolygon(r.native_polygon_source_mil);
                 const line=await eda.pcb_PrimitivePolyline.create("",11,polygon,1.0,false);
                 if(!line)throw Error("native polyline create null");
                 made.push({name:r.name,id:line.getState_PrimitiveId(),layer:line.getState_Layer()});
               }catch(e){made.push({name:r.name,error:String(e)});break;}
            }
            const after=await eda.pcb_PrimitivePolyline.getAll();
            return {project:project.friendlyName,created:made,
                    count:after.length,pad_count:(await eda.pcb_PrimitivePad.getAll()).length};
        })();"""%(json.dumps(BOARD_V13.stem),json.dumps(uuid),json.dumps(LIB),
                  json.dumps(plan["slot_polygons"],separators=(",",":")))
        response=call(sid,js,59000)
        value=response.get("value") or {}
        passed=(response.get("ok") and value.get("count")==3 and value.get("pad_count")==0
                and len(value.get("created",[]))==3
                and all(not x.get("error") and x.get("layer")==11 for x in value["created"]))
        write_once(APPLIED,{"status":"THREE_NATIVE_BOARDOUTLINE_CUTOUT_CONTOURS_CREATED_NOT_FOR_FAB"
            if passed else "NATIVE_CONTOUR_CREATE_UNVERIFIED_NOT_FOR_FAB",
            "source_plan_sha256":V14.sha(PLAN),"native_response":response,
            "session_id":sid,"native_library_uuid":uuid,"fabrication_approved":False})
        print(json.dumps(json.loads(APPLIED.read_text("utf8")),ensure_ascii=False)[:4800])
        if not passed:
            raise RuntimeError("Contour partial creation, don't replay")
        return
    if z.verify:
        if VERIFIED.exists():raise FileExistsError("Native footprint saved already inspected")
        applied=json.loads(APPLIED.read_text("utf8"))
        if applied["status"]!="THREE_NATIVE_BOARDOUTLINE_CUTOUT_CONTOURS_CREATED_NOT_FOR_FAB":
            raise ValueError("Footprint 3 polylines not acknowledged")
        js="""return await(async()=>{
            const project=await eda.dmt_Project.getCurrentProjectInfo();
            if(project?.friendlyName!==%s)throw Error("Wrong EDA GUI");
            const first=await eda.pcb_Document.save();
            if(first!==true)throw Error("Native footprint save did not acknowledge");
            await eda.lib_Footprint.openInEditor(%s,%s);
            const lines=await eda.pcb_PrimitivePolyline.getAll();
            return {project:project.friendlyName,saved:first,
               count:lines.length,
               rows:lines.map(x=>({id:x.getState_PrimitiveId(),layer:x.getState_Layer(),
                polygon_source:x.getState_Polygon()?.getSource()})),
               pad_count:(await eda.pcb_PrimitivePad.getAll()).length};
         })();"""%(json.dumps(BOARD_V13.stem),json.dumps(uuid),json.dumps(LIB))
        reply=call(sid,js,44000)
        value=reply.get("value") or {}
        passed=reply.get("ok") and value.get("saved") is True and value.get("count")==3 and value.get("pad_count")==0
        if passed:
            baseline=json.loads(APPLIED.read_text("utf8"))["native_response"]["value"]
            passed={x["id"] for x in baseline["created"]}=={x["id"] for x in value["rows"]} and all(x["layer"]==11 for x in value["rows"])
        write_once(VERIFIED,{"status":"THREE_NATIVE_BOARDOUTLINE_CONTOURS_SAVED_AND_REOPENED_IN_SAME_GUI_NOT_FOR_FAB"
            if passed else "NATIVE_SAVED_FOOTPRINT_REOPEN_UNVERIFIED_NOT_FOR_FAB",
            "native_response":reply,
            "native_PCB_cutout_not_placed":True,
            "original_V13_board_unchanged":V14.sha(BOARD_V13)==BOARD_SHA,
            "fabrication_approved":False})
        print(json.dumps({k:v for k,v in json.loads(VERIFIED.read_text("utf8")).items()
                          if k!="native_response"},ensure_ascii=False))
        if not passed:
            raise RuntimeError("Native outline footprint saved/roundtrip failed")
        return


if __name__=="__main__":
    main()

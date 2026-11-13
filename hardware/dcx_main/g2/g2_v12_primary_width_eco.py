"""One-shot safe correction to actual V12 native PRI_T1 trace max-width rule.

V12 native DRC confirmed 145 Connection/1 Netlist but 1 Physical Error:
PRI_T1 trace 3.0 mm > PCB rule 100 mil maximum. Change exact native
primitive UUID from 3.0 to 2.5 mm without rerouting/recreating any copper.
Preserve other EDA windows and V11 parent. No blind retry.

python hardware/dcx_main/g2/g2_v12_primary_width_eco.py --check
python hardware/dcx_main/g2/g2_v12_primary_width_eco.py --fix
"""
from __future__ import annotations
import argparse,hashlib,json,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path[:0]=[str(HERE),str(ROOT/"hardware/dcx_main/g1")]
import g2_v9_real_t530_components as V9

TARGET=HERE/"dcx_main_board_g2_V12_NATIVE_PRIMARY_RESONANT_LINKS_NOT_FOR_FAB.eprj2"
TARGET_PRE_SHA="527280764de6121b3a6f3eb5bbc1bac7ee72f8714e0c4be4f7a7a1f8087d1a4e"
PARENT=HERE/"dcx_main_board_g2_V11_NATIVE_SR_GATE_ESCAPE_NOT_FOR_FAB.eprj2"
PARENT_SHA="d90ca22079ad7245e8c3904eb8369da58c705ae39b56574bf7843dad34cad89b"
ORIGINAL_DRC=HERE/"g2_v12_native_gui_DRC_after_readback_NOT_FOR_FAB.json"
BASE_READBACK=HERE/"g2_v12_native_readback_before_drc_NOT_FOR_FAB.json"
APPLIED=HERE/"g2_v12_primary_copper_native_applied_NOT_FOR_FAB.json"
ATTEMPT=HERE/"g2_v12_primary_width_eco_attempt_once_NOT_FOR_FAB.json"
RECEIPT=HERE/"g2_v12_primary_width_eco_applied_NOT_FOR_FAB.json"
TRACE_ID="25fcbfaa23a768e3"
OLD_MM=3.0
NEW_MM=2.5
M=.0254

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def once(path,data):
    if path.exists():raise FileExistsError("Native one-shot result already exists: "+str(path))
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf8",newline="\n")

def source():
    if sha(PARENT)!=PARENT_SHA or sha(TARGET)!=TARGET_PRE_SHA:
        raise ValueError("V12 saved / V11 parent native CAD changed before ECO")
    base=json.loads(BASE_READBACK.read_text("utf8"))
    bad=json.loads(ORIGINAL_DRC.read_text("utf8"))
    previous=json.loads(APPLIED.read_text("utf8"))
    line=next(q for q in base["value"]["lines"] if q["id"]==TRACE_ID)
    if (line["net"]!="PRI_T1" or abs(line["width"]*M-OLD_MM)>1e-5 or
        bad["native_categories"]!={"Physical Error":1,"Connection Error":145,"Netlist Error":1} or
        not previous["native_reply"]["all_created"] or
        not any(x["id"]==TRACE_ID for x in previous["native_reply"]["created"])):
        raise ValueError("Cannot safely identify exact one offending native PRI_T1 track")
    raw=bad["response"]["value"]["raw"]
    physical=next(g for g in raw if g["name"]=="Physical Error")
    errors=[r for x in physical["list"] for r in x["list"]]
    if len(errors)!=1 or errors[0]["explanation"]["errData"]["obj1"]!=TRACE_ID:
        raise ValueError("Native physical error is not exactly known over-width trace")
    return previous["session_id"]

def fix():
    if ATTEMPT.exists() or RECEIPT.exists():
        raise FileExistsError("Width-only ECO was already attempted: never replay")
    sid=source()
    old=V9.D.call([str(V9.D.LEDA),"session","list"],timeout_s=22)
    if not old.get("ok"):raise RuntimeError("Cannot inventory existing native GUI")
    users={x["sessionId"] for x in old["value"] if x.get("status")=="alive" and x.get("headless") is False}
    if sid not in users:raise RuntimeError("V12 native target GUI not open")
    once(ATTEMPT,{"source_sha256":TARGET_PRE_SHA,"original_user_guI_session_ids":sorted(users),
        "trace_id":TRACE_ID,"net":"PRI_T1","old_width_mm":OLD_MM,"new_width_mm":NEW_MM,
        "one_shot":True,"fabrication_approved":False})
    js="""return await(async()=>{
       const p=await eda.dmt_Project.getCurrentProjectInfo();
       if(p?.friendlyName!==%s)throw Error("Wrong source V12 GUI");
       const line=await eda.pcb_PrimitiveLine.get(%s);
       if(!line||line.getState_Net()!=="PRI_T1"||
          Math.abs(line.getState_LineWidth()*0.0254-3.0)>0.0001)
          throw Error("Unknown or altered original native trace; refuse");
       const result=await eda.pcb_PrimitiveLine.modify(%s,{lineWidth:%s});
       if(!result)throw Error("Native width-only modify failed");
       const after=await eda.pcb_PrimitiveLine.get(%s);
       if(!after||after.getState_Net()!=="PRI_T1"||
          Math.abs(after.getState_LineWidth()*0.0254-2.5)>0.0001)
          throw Error("Native width-only readback failed");
       return {id:after.getState_PrimitiveId(),net:after.getState_Net(),
          width_mm:after.getState_LineWidth()*0.0254,
          line_count:(await eda.pcb_PrimitiveLine.getAll()).length};
    })();"""%(json.dumps(TARGET.stem),json.dumps(TRACE_ID),json.dumps(TRACE_ID),NEW_MM/M,json.dumps(TRACE_ID))
    resp=V9.D.call(V9.D.build_invoke_args(sid,js,59000),timeout_s=75)
    val=resp.get("value") or {}
    doc={"status":"V12_WIDTH_ECO_NOT_VERIFIED_NOT_FOR_FAB",
         "source_pre_eco_sha256":TARGET_PRE_SHA,"V11_parent_sha256":PARENT_SHA,
         "session_id":sid,"native_response":resp,"fabrication_approved":False}
    if (resp.get("ok") and val.get("id")==TRACE_ID and
        val.get("net")=="PRI_T1" and abs(val.get("width_mm",0)-NEW_MM)<.0001):
        doc["status"]="V12_NATIVE_WIDTH_ECO_2P5MM_READBACK_NOT_FOR_FAB"
    once(RECEIPT,doc)
    print(json.dumps(doc,ensure_ascii=False,indent=2)[:5000])
    return 0 if doc["status"].startswith("V12_NATIVE_WIDTH_ECO_2P5MM") else 1

def main():
    p=argparse.ArgumentParser()
    x=p.add_mutually_exclusive_group(required=True)
    x.add_argument("--check",action="store_true")
    x.add_argument("--fix",action="store_true")
    a=p.parse_args()
    if a.check:
        print(json.dumps({"native_V12_session":source(),"trace_id":TRACE_ID,
            "correct_width_mm":NEW_MM,"original_width_mm":OLD_MM,"fab":False}))
        return 0
    return fix()
if __name__=="__main__":
    raise SystemExit(main())

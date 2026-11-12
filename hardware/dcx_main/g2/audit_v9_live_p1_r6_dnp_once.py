"""Read R6's real native P1 assembly flags on a byte-for-byte V9 copy, ONCE.

Original V9/V8 and existing visible GUI windows are never modified/closed.
No subsequent retry of an unknown native result; preserve attempt/failed
receipts, and keep ALL project release gates NOT_FOR_FAB.
"""
from __future__ import annotations
import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(HERE))
import g2_v9_real_t530_components as V9
import audit_v9_p1_terminal_parity as P

ATTEMPT=HERE/"g2_v9_p1_r6_dnp_native_attempt_NOT_FOR_FAB.json"
RECEIPT=HERE/"g2_v9_p1_r6_dnp_native_verification_NOT_FOR_FAB.json"
D=V9.D


def dump(path,doc):
    if path.exists():raise FileExistsError("Historical native result must not be replayed/overwritten")
    path.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+"\n",encoding="utf8",newline="\n")


JS="""return await (async()=>{
 const p=await eda.dmt_Project.getCurrentProjectInfo();
 if(p?.friendlyName!=="dcx_main_board_g2_T530_OEM_DENSITY_B_V9_REAL_72_COMPONENT_TRIAL_NOT_FOR_FAB")
    throw Error("Wrong native CAD project; refuse");
 const sheets=p?.data?.find(x=>x?.schematic?.uuid)?.schematic?.page||[];
 const pages=sheets.filter(x=>x.name==="P1");
 if(pages.length!==1)throw Error("Exactly one native P1 page required");
 await eda.dmt_EditorControl.openDocument(pages[0].uuid);
 const all=await eda.sch_PrimitiveComponent.getAll();
 const r6=all.filter(x=>x.getState_Designator()==="R6");
 const r8=all.filter(x=>x.getState_Designator()==="R8");
 if(r6.length!==1||r8.length>0)throw Error("R6/R8 native designator mapping inconsistent");
 const c=r6[0];
 const pins=await eda.sch_PrimitiveComponent.getAllPinsByPrimitiveId(c.getState_PrimitiveId());
 return {native_page:"P1",native_schematic_component_count:all.length,
    R6:{count:r6.length,primitive_id:c.getState_PrimitiveId(),
        addIntoBom:c.getState_AddIntoBom(),
        addIntoPcb:c.getState_AddIntoPcb(),
        schematic_pin_numbers:pins.map(x=>x.getState_PinNumber()).sort()},
    original_R8_designator_count:r8.length};
})();"""


def run():
    if ATTEMPT.exists() or RECEIPT.exists():
        raise FileExistsError("Native R6 one-time verification already attempted")
    if V9.sha(V9.V9)!=P.NATIVE_SHA:raise RuntimeError("V9 saved source changed")
    source_sha=P.NATIVE_SHA
    before=D.call([str(D.LEDA),"session","list"],timeout_s=22)
    if not before.get("ok"):raise RuntimeError("Cannot inventory current user GUI sessions")
    previous={x["sessionId"] for x in before["value"] if x.get("status")=="alive"
              and x.get("headless") is False}
    scratch=Path(tempfile.mkdtemp(prefix="czy_p1_r6_native_readonly_",dir=str(ROOT.parent)))
    target=scratch/V9.V9.name
    shutil.copy2(V9.V9,target)
    if V9.sha(target)!=source_sha:raise RuntimeError("Source copy changed")
    dump(ATTEMPT,{"source_sha256":source_sha,"status":"READ_ONLY_SUBMITTED_ONCE",
                  "original_gui_session_count":len(previous),
                  "fabrication_approved":False})
    session=None
    out={"status":"NATIVE_R6_FLAGS_NOT_VERIFIED_NOT_FOR_FAB",
         "source_sha256":source_sha,"source_unchanged":False,
         "original_gui_preserved":False,"fabrication_approved":False}
    try:
        args=D.build_open_args(target)
        if args[-2:]!=["--headless","true"]:raise RuntimeError("Unsupported open protocol")
        args[-1]="false"
        opened=D.call(args,timeout_s=115)
        if not opened.get("ok"):raise RuntimeError("Native copy open failed")
        session=opened["value"]["sessionId"]
        out["read_only_gui_session"]=session
        time.sleep(D.SETTLE_S+3)
        ping=D.call(D.build_ping_args(session),timeout_s=20)
        if not ping.get("ok"):raise RuntimeError("Native renderer not ready")
        response=D.call(D.build_invoke_args(session,JS,59000),timeout_s=75)
        if not response.get("ok"):raise RuntimeError(str(response.get("error")))
        val=response["value"]
        if val["native_schematic_component_count"]!=83 or val["R6"]["schematic_pin_numbers"]!=["1","2"]:
            raise RuntimeError("Saved P1 R6 count/pin check failed")
        if val["R6"]["addIntoPcb"] not in (True,False) or val["R6"]["addIntoBom"] not in (True,False):
            raise RuntimeError("Native R6 assembly flags not booleans")
        out.update({"status":"NATIVE_V9_P1_R6_FLAGS_READBACK_VERIFIED_NOT_FOR_FAB",
                    "native_P1":val,
                    "R6_present_on_real_PCB":False,
                    "historical_R8_DNP_reference_verified":True,
                    "R6_true_current_DNP":not val["R6"]["addIntoPcb"] and not val["R6"]["addIntoBom"],
                    "fabrication_approved":False})
    except Exception as e:
        out["error"]=str(e)
    finally:
        if session:
            closed=D.call(D.build_close_args(session),timeout_s=38)
            out["own_verification_GUI_closed"]=closed.get("ok") is True
        after=D.call([str(D.LEDA),"session","list"],timeout_s=22)
        if after.get("ok"):
            active={x["sessionId"] for x in after["value"] if x.get("status")=="alive" and
                    x.get("headless") is False}
            out["original_gui_preserved"]=previous.issubset(active)
        out["source_unchanged"]=V9.sha(V9.V9)==source_sha
        out["clone_bytes_unchanged"]=V9.sha(target)==source_sha
        if not out["source_unchanged"] or not out["original_gui_preserved"] or not out["clone_bytes_unchanged"]:
            out["status"]="NATIVE_R6_READBACK_SAFETY_CHECK_FAILED_NOT_FOR_FAB"
        if out.get("own_verification_GUI_closed"):
            try:
                target.unlink()
                scratch.rmdir()
                out["temporary_clone_cleaned"]=True
            except OSError:
                out["temporary_clone_cleaned"]=False
        dump(RECEIPT,out)
    return out


def main():
    p=argparse.ArgumentParser()
    g=p.add_mutually_exclusive_group(required=True)
    g.add_argument("--check",action="store_true")
    g.add_argument("--capture",action="store_true")
    a=p.parse_args()
    if a.check:
        print(json.dumps({"source_sha":P.NATIVE_SHA,
             "source_unchanged":V9.sha(V9.V9)==P.NATIVE_SHA,
             "already_attempted":ATTEMPT.exists() or RECEIPT.exists()}))
        return 0
    r=run()
    print(json.dumps(r,ensure_ascii=False,indent=2))
    return 0 if r["status"]=="NATIVE_V9_P1_R6_FLAGS_READBACK_VERIFIED_NOT_FOR_FAB" else 1
if __name__=="__main__":
    raise SystemExit(main())

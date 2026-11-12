"""Build/verify a *separate* real EasyEDA G2 72-cap, 144-pad trial board.

This creates individual netted pad primitives, NOT approved component
footprints; the product C2158170 is not available in this installed
EasyEDA local library. The original schematic has not acquired 72 symbols.
Never send to fabrication. No source or prior candidate is overwritten.

python hardware/dcx_main/g2/plan_t530_72_native.py --write
python hardware/dcx_main/g2/apply_t530_72_native.py --check
python hardware/dcx_main/g2/apply_t530_72_native.py --apply
# If the editor saved but native reopen failed, ONLY:
python hardware/dcx_main/g2/apply_t530_72_native.py --resume

The script uses the same accepted lceda-pro --path/ping/save/reopen protocol as
G1, and rejects any mismatch in the exact original 149 tracks, original
component pads, or the 144 source-locked land trial numbers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from collections import Counter
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
G1=ROOT/"hardware/dcx_main/g1"
sys.path.insert(0,str(G1))
import run_driver_drc as D
import route_open_connections as R
import plan_t530_72_native as P

TARGET=HERE/"dcx_main_board_g2_t530_72_PROVISIONAL_PADS_NOT_FOR_FAB.eprj2"
PREFIX="g2_t530_72_native"
READ_JS=G1/"read_driver_route.js"
DRC_JS=G1/"driver_drc.js"
READBACK=HERE/(PREFIX+"_reopen_readback.json")
DELTA=HERE/(PREFIX+"_drc_delta.json")

def sha(path:Path)->str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def dump(name:str,data:dict)->None:
    (HERE/f"{PREFIX}_{name}.json").write_text(
        json.dumps(data,ensure_ascii=False,indent=2)+"\n",
        encoding="utf-8",newline="\n")

def verified_plan()->dict:
    d=P.make()
    if d["problems"]:
        raise ValueError("unsafe G2 native pad preflight: "+repr(d["problems"][:10]))
    if not P.OUT.is_file() or json.loads(P.OUT.read_text(encoding="utf-8")) != d:
        raise ValueError("Regenerate/commit exact source-locked pad plan before ECO")
    if sha(P.C.BASE)!=d["source_board_sha256"]:
        raise ValueError("G1 149-line source changed")
    return d

def pad_rows(plan:dict)->list[dict]:
    return [pad for item in plan["placements"] for pad in item["provisional_pads"]]

def chunk_js(rows:list[dict])->str:
    items=[{"num":pad["number"],
            "net":pad["net"],
            "x":round(pad["centre_mm"][0]*P.MIL,7),
            "y":round(-pad["centre_mm"][1]*P.MIL,7),
            "w":round(pad["size_mm"][0]*P.MIL,7),
            "h":round(pad["size_mm"][1]*P.MIL,7)} for pad in rows]
    return """return await (async()=>{
      const ROWS = %s;
      const info=await eda.dmt_Project.getCurrentProjectInfo();
      const board=info?.data?.find(d=>d?.pcb?.uuid);
      if(!board)throw new Error("PCB missing");
      await eda.dmt_EditorControl.openDocument(board.pcb.uuid);
      const old=await eda.pcb_PrimitivePad.getAll();
      const ids=new Set(old.map(p=>p.getState_PadNumber()));
      if(ROWS.some(p=>ids.has(p.num)))throw new Error("G2 pad already on board, refuse double-apply");
      const out=[];
      for(const p of ROWS){
        try{
          const v=await eda.pcb_PrimitivePad.create(
             1,p.num,p.x,p.y,0,['RECT',p.w,p.h],p.net,null);
          if(!v)throw new Error("primitive create returned null");
          const got=v.getState_PadNumber(), net=v.getState_Net();
          if(got!==p.num||net!==p.net)throw new Error("readback mismatch "+got+"/"+net);
          out.push({num:got,net:net,ok:true});
        }catch(e){out.push({num:p.num,ok:false,error:String(e)});break}
      }
      return {requested:ROWS.length,created:out,all_created:out.length===ROWS.length&&out.every(x=>x.ok)};
    })();""" % json.dumps(items,separators=(",",":"))

def invoke(session:str,script:str)->dict:
    return D.call(D.build_invoke_args(session,script),timeout_s=150)

def open_ping(label:str)->str|None:
    opened=D.call(D.build_open_args(TARGET),timeout_s=90)
    dump(label+"_open",opened)
    s=(opened.get("value") or {}).get("sessionId")
    if not s:return None
    time.sleep(D.SETTLE_S)
    ping=D.call(D.build_ping_args(s),timeout_s=30)
    dump(label+"_ping",ping)
    if not ping.get("ok"):
        dump(label+"_close",D.call(D.build_close_args(s)))
        return None
    return s

def compare_readback(actual:dict,plan:dict)->dict:
    from collections import Counter
    parent=P.C.active_native_g1()
    if len(actual["components"])!=77 or len(actual["lines"])!=149 or len(actual["vias"])!=18:
        raise ValueError("native candidate component/traces/vias counts changed")
    if Counter(json.dumps(x,sort_keys=True) for x in actual["components"])!=Counter(
            json.dumps(x,sort_keys=True) for x in parent["components"]):
        raise ValueError("candidate changed existing component placement")
    if Counter(json.dumps(x,sort_keys=True) for x in actual["lines"])!=Counter(
            json.dumps(x,sort_keys=True) for x in parent["lines"]):
        raise ValueError("G2 changed previously accepted 149 native copper lines")
    if Counter(json.dumps(x,sort_keys=True) for x in actual["vias"])!=Counter(
            json.dumps(x,sort_keys=True) for x in parent["vias"]):
        raise ValueError("G2 changed existing vias")
    if Counter(json.dumps(x,sort_keys=True) for x in actual["nets"])!=Counter(
            json.dumps(x,sort_keys=True) for x in parent["nets"]):
        raise ValueError("G2 changed the 65 accepted G1 nets")
    if len(actual["pads"])!=443:
        raise ValueError("Expected 299 old + 144 new actual native pads")
    wanted={x["number"]:x for x in pad_rows(plan)}
    seen={}
    oldpad=[]
    for p in actual["pads"]:
        num=str(p["PadNumber"])
        if num in wanted and not p.get("ref"):
            if num in seen:
                raise ValueError("Duplicated G2 experimental pad "+num)
            w=wanted[num]
            if (p.get("Net")!=w["net"] or int(p["Layer"])!=1 or
                abs(float(p["X"])*.0254-w["centre_mm"][0])>.006 or
                abs(-float(p["Y"])*.0254-w["centre_mm"][1])>.006):
                raise ValueError("Wrong native land net/layer/XY for "+num)
            shape=p.get("Pad") or []
            if (len(shape)<3 or shape[0]!="RECT" or
                abs(float(shape[1])*.0254-w["size_mm"][0])>.006 or
                abs(float(shape[2])*.0254-w["size_mm"][1])>.006):
                raise ValueError("Wrong native land size for "+num)
            seen[num]=p
        else:
            oldpad.append(p)
    if set(seen)!=set(wanted):
        raise ValueError("Missing new real pads "+repr(sorted(set(wanted)-set(seen))[:10]))
    if Counter(json.dumps(x,sort_keys=True) for x in oldpad)!=Counter(
            json.dumps(x,sort_keys=True) for x in parent["pads"]):
        raise ValueError("Previously accepted original 299 native pads changed")
    return {"original_components_preserved":77,
            "original_pads_preserved":299,"new_trial_lands":len(seen),
            "original_nets_preserved":65,"original_lines_preserved":149,
            "original_vias_preserved":18,
            "native_pad_xy_net_size_verified":True,
            "schematic_components_added":0,"fabrication_approved":False}

def resume()->int:
    plan=verified_plan()
    if not TARGET.is_file() or sha(TARGET)==sha(P.C.BASE):
        raise ValueError("No distinct saved G2 candidate to inspect; never double-apply")
    source_sha=sha(P.C.BASE)
    candidate_sha=sha(TARGET)
    session=open_ping("reopen")
    if not session:
        print("Native reopen failed; retained candidate, no repeat creation")
        return 1
    try:
        rb=invoke(session,READ_JS.read_text(encoding="utf-8"))
        dump("reopen_readback",rb)
        if not rb.get("ok"):
            print(json.dumps(rb,ensure_ascii=False)[:3000])
            return 1
        audit=compare_readback(rb["value"],plan)
        drc=invoke(session,DRC_JS.read_text(encoding="utf-8"))
        dump("drc_raw",drc)
        if not drc.get("ok"):
            print("Native DRC could not execute; no release")
            return 1
    finally:
        dump("reopen_close",D.call(D.build_close_args(session)))
    if source_sha!=sha(P.C.BASE) or candidate_sha!=sha(TARGET):
        raise ValueError("Read-only G2 native reopen modified project bytes")
    categories=R.categories(drc)
    out={"status":"ACTUAL_144_PROVISIONAL_PAD_NATIVE_SAVE_REOPEN_NOT_FOR_FAB",
         "parent_sha256":source_sha,"candidate_sha256":candidate_sha,
         "provisional_land_plan_sha256":sha(P.OUT),
         "native_reopen_drc":categories,"readback":audit,
         "added_actual_component_instances":0,
         "pad_footprint_oem_qualified":False,
         "schematic_parity_passed":False,
         "100a_power_copper_done":False,
         "real_both_pole_busbar_connected":False,
         "all_unconnected_closed":categories.get("Connection Error")==0,
         "native_drc_zero":all(v==0 for v in categories.values()),
         "fabrication_approved":False}
    dump("drc_delta",out)
    print(json.dumps(out,ensure_ascii=False,indent=2))
    return 0

def apply()->int:
    plan=verified_plan()
    if TARGET.exists():
        raise FileExistsError("G2 candidate already exists; use --resume only "+str(TARGET))
    original_sha=sha(P.C.BASE)
    shutil.copy2(P.C.BASE,TARGET)
    session=open_ping("apply")
    if not session:
        print("Native editor unavailable; G2 candidate remains an unmodified source copy")
        return 1
    saved=False
    try:
        row=pad_rows(plan)
        for i in range(0,len(row),24):
            batch=invoke(session,chunk_js(row[i:i+24]))
            dump("apply_batch_"+str(i//24+1),batch)
            data=batch.get("value") or {}
            if not batch.get("ok") or not data.get("all_created"):
                print("G2 native batch failed, not saving",str(batch)[:1400])
                return 1
        saved_result=invoke(session,"return await eda.pcb_Document.save();")
        dump("apply_save",saved_result)
        saved=(saved_result.get("ok") is True and saved_result.get("value") is True)
        if not saved:
            print("G2 native save not confirmed, don't claim pads")
            return 1
        time.sleep(30)  # native debounced save
    finally:
        dump("apply_close",D.call(D.build_close_args(session)))
    if sha(P.C.BASE)!=original_sha:
        raise ValueError("THE FROZEN 149-line G1 ORIGINAL CHANGED")
    if not saved or sha(TARGET)==original_sha:
        raise RuntimeError("G2 file was never natively modified")
    # The save receipt cannot count as validation: reopen and run actual DRC.
    return resume()

def main()->int:
    ap=argparse.ArgumentParser(description=__doc__)
    g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check",action="store_true")
    g.add_argument("--apply",action="store_true")
    g.add_argument("--resume",action="store_true")
    a=ap.parse_args()
    if a.check:
        d=verified_plan()
        print(json.dumps({"source":d["source_board"],"source_sha256":d["source_board_sha256"],
                          "parts":d["part_count"],"pads":d["pad_count"],
                          "problems":d["problems"],
                          "native_target_exists":TARGET.exists(),"oem_land_approved":False,
                          "fabrication_approved":False},indent=2))
        return 0
    return apply() if a.apply else resume()

if __name__=="__main__":
    raise SystemExit(main())

"""Independent *fresh GUI* reopen of actual EasyEDA V11 disk-saved board.

Uses PCB full native readback, physical islands, original real DRC, then native
Cout72 schematic (PCB->DRC->SCH order avoids bridge/editor stale DRC).
Never modifies/closes any existing original user V5/V8/V9/V10/V11 GUI.
One-shot source-hash audit: no rerun after uncertain native EDA attempt.

    python hardware/dcx_main/g2/g2_v11_independent_native_reopen.py --check
    python hardware/dcx_main/g2/g2_v11_independent_native_reopen.py --verify
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path[:0]=[str(ROOT/"tools"),str(ROOT/"hardware/dcx_main/g1"),str(HERE)]
import g2_v11_eight_sr_gate_escape as V11
import g2_oem_net_islands as ISLAND
import route_open_connections as ROUTE
import g2_v9_sch_cout72 as SCH

D=V11.V9.D
CAP_EXPECT={"components":149,"pads":443,"lines":465,"vias":93,"nets":65}
DRC_EXPECT={"Connection Error":149,"Netlist Error":1}
ATTEMPT=HERE/"g2_v11_independent_reopen_submitted_once_NOT_FOR_FAB.json"
RECEIPT=HERE/"g2_v11_independent_native_reopen_verified_NOT_FOR_FAB.json"
READBACK=HERE/"g2_v11_independent_native_full_readback_NOT_FOR_FAB.json"
DRC_RAW=HERE/"g2_v11_independent_native_drc_raw_NOT_FOR_FAB.json"


def required(reply,what):
    if reply.get("ok") is not True:
        raise RuntimeError(f"{what}: {reply.get('error')}")
    return reply["value"]


def invoke(sid,code,timeout=59000):
    return D.call(D.build_invoke_args(sid,code,timeout),timeout_s=75)


def alive():
    items=required(D.call([str(D.LEDA),"session","list"],timeout_s=25),"native GUI sessions")
    return {x["sessionId"] for x in items
            if x.get("status")=="alive" and x.get("headless") is False}


def inputs():
    original=V11.frozen()
    proposal=V11.plan()
    if json.loads(V11.PLAN.read_text("utf8"))!=proposal:
        raise ValueError("Source-locked V11 planned repair stale")
    applied=json.loads(V11.APPLIED.read_text("utf8"))
    mem=json.loads((HERE/"g2_v11_in_memory_native_drc_NOT_FOR_FAB.json").read_text("utf8"))
    live=json.loads((HERE/"g2_v11_pre_save_readback_NOT_FOR_FAB.json").read_text("utf8"))
    if not (applied["edit_receipt"]["deleted"] and
            applied["edit_receipt"]["all_added"] and
            applied["edit_receipt"]["new_lines"]==465 and
            len(applied["edit_receipt"]["wrote"])==32):
        raise ValueError("Unconfirmed 32 native lines / 8 native deletions")
    if (mem["native_categories"]!=DRC_EXPECT or live["native"]["lines"]==original["lines"] or
        mem["real_runtime_islands_after"]["PGND"]!=37 or
        any(mem["real_runtime_islands_after"][f"G{c}{i}"]!=1
            for i in range(1,5) for c in "AB")):
        raise ValueError("Native in-memory DRC/copper islands not a known safe precursor")
    fresh=V11.sha(V11.TARGET)
    if fresh==V11.SOURCE_SHA or not V11.TARGET.is_file() or V11.sha(V11.SOURCE)!=V11.SOURCE_SHA:
        raise ValueError("V11 saved file not different from immutable V10 original")
    if RECEIPT.exists() or ATTEMPT.exists() or READBACK.exists() or DRC_RAW.exists():
        raise FileExistsError("V11 independent native verification already attempted, no blind retry")
    return original,proposal,applied,mem,live,fresh


def verify():
    orig,proposal,applied,mem,live,src=inputs()
    user_gui=alive()
    directory=Path(tempfile.mkdtemp(prefix="czy_v11_verify_",dir=str(ROOT.parent)))
    clone=directory/V11.TARGET.name
    shutil.copy2(V11.TARGET,clone)
    if V11.sha(clone)!=src:raise RuntimeError("Native V11 clone exact byte integrity failed")
    V11.once(ATTEMPT,{"source_v11_sha256":src,"original_v10_sha256":V11.SOURCE_SHA,
       "visible_user_GUI_session_ids":sorted(user_gui),"one_shot":True,"fabrication_approved":False})
    result={"status":"V11_INDEPENDENT_NATIVE_REOPEN_NOT_VERIFIED_NOT_FOR_FAB",
            "saved_V11_native_sha256":src,
            "source_V10_native_sha256":V11.SOURCE_SHA,
            "fabrication_approved":False,"100A_qualified":False}
    sid=None
    try:
        args=D.build_open_args(clone)
        if args[-2:]!=["--headless","true"]:raise ValueError("Unexpected native GUI protocol")
        args[-1]="false"
        opened=required(D.call(args,timeout_s=120),"open independently saved V11")
        sid=opened["sessionId"]
        result["independent_session_id"]=sid
        time.sleep(D.SETTLE_S+3)
        required(D.call(D.build_ping_args(sid),timeout_s=23),"native renderer initialization")
        info=required(invoke(sid,"""return await(async()=>{const p=await eda.dmt_Project.getCurrentProjectInfo();
           const sch=p?.data?.find(t=>t?.schematic?.uuid)?.schematic;
           return {name:p?.friendlyName,pcb:p?.data?.find(t=>t?.pcb?.uuid)?.pcb?.uuid,
             pages:sch?.page?.map(t=>({name:t.name,uuid:t.uuid}))};})();""",18000),"clone project identity")
        if info["name"]!=V11.TARGET.stem or not info["pcb"]:
            raise RuntimeError("Clone opens wrong native project")
        cout=[x for x in info.get("pages") or [] if x["name"]=="COUT_T530_72"]
        if len(cout)!=1:raise RuntimeError("Expected COUT_T530_72 native page missing")
        read_js=(ROOT/"hardware/dcx_main/g1/read_driver_route.js").read_text("utf8")
        data=required(invoke(sid,read_js),"separately loaded V11 PCB raw primitives")
        counts={key:len(data[key]) for key in CAP_EXPECT}
        if counts!=CAP_EXPECT:raise ValueError("V11 saved native geometry different from live V11: "+str(counts))
        for key in ("pads","nets"):
            if Counter(json.dumps(x,sort_keys=True) for x in orig[key])!=Counter(
                    json.dumps(x,sort_keys=True) for x in data[key]):
                raise ValueError("V11 changed existing native pads or nets: "+key)
        oldC={x["ref"]:x for x in orig["components"]}
        newC={x["ref"]:x for x in data["components"]}
        if oldC.keys()!=newC.keys():raise ValueError("Native component designators changed")
        for ref,before in oldC.items():
            after=newC[ref]
            if (before["Rotation"]!=after["Rotation"] or
                abs(before["X"]-after["X"])>.00012 or
                abs(before["Y"]-after["Y"])>.00012):
                raise ValueError("Original native component moved: "+ref)
        oldV={x["id"]:x for x in orig["vias"]}
        newV={x["id"]:x for x in data["vias"]}
        if oldV.keys()!=newV.keys():raise ValueError("Original via identity changed")
        for identity,before in oldV.items():
            after=newV[identity]
            if any(before[x]!=after[x] for x in ("net","hole","diameter")) or any(
                    abs(before[x]-after[x])>.00012 for x in ("x","y")):
                raise ValueError("Original via changed: "+identity)
        for c in range(1,73):
            ref=f"CHB{c:02d}"
            nets={str(p["PadNumber"]):p["Net"] for p in data["pads"] if p.get("ref")==ref}
            if nets!={"1":"VOUT","2":"PGND"}:
                raise ValueError("Real T530 native two-pin connection changed: "+ref)
        before_islands=ISLAND.islands(orig,{"PGND"}|{f"G{c}{i}" for i in range(1,5) for c in "AB"})
        after_islands=ISLAND.islands(data,{"PGND"}|{f"G{c}{i}" for i in range(1,5) for c in "AB"})
        prev={k:v["island_count_geometry_screen"] for k,v in before_islands.items()}
        post={k:v["island_count_geometry_screen"] for k,v in after_islands.items()}
        if post!=proposal["after_simulated_islands"] or prev!=proposal["before_real_native_islands"]:
            raise ValueError("Real native saved connectivity different from V11 preflight")
        l_ids={x["id"] for x in data["lines"]}
        old_ids=set(proposal["real_old_ground_spine_to_delete_ids"])
        new_ids={x["id"] for x in applied["edit_receipt"]["wrote"]}
        if old_ids & l_ids or not new_ids.issubset(l_ids):
            raise ValueError("Deleted old copper or 32 new native traces do not persist")
        V11.once(READBACK,{"status":"V11_INDEPENDENT_NATIVE_FULL_PRIMITIVE_READBACK_NOT_FOR_FAB",
                     "source_native_sha256":src,
                     "native_counts":counts,
                     "physical_islands_before":prev,
                     "physical_islands_after":post,
                     "all_32_new_native_trace_ids_present":True,
                     "all_8_old_PGND_trace_ids_absent":True,
                     "real_native_data":data,
                     "fabrication_approved":False})
        # Native PCB DRC BEFORE opening/activating a SCH page.
        raw=invoke(sid,(ROOT/"hardware/dcx_main/g1/driver_drc.js").read_text("utf8"))
        category=ROUTE.categories(raw)
        V11.once(DRC_RAW,{"status":"V11_INDEPENDENT_NATIVE_DRC_RAW_NOT_FOR_FAB",
              "source_native_sha256":src,"categories":category,"real_native_reply":raw,
              "fabrication_approved":False})
        if category!=DRC_EXPECT:
            raise RuntimeError("Actual independent native V11 DRC mismatch: "+str(category))
        # Native 72 T530/144-wire schematic page remains linked to its PCB.
        sch_js=SCH.js_verify(cout[0]["uuid"])
        sch_js=sch_js.replace(json.dumps(V11.V9.V9.stem),json.dumps(V11.TARGET.stem))
        schem=required(invoke(sid,sch_js),"native COUT72 schematic re-open")
        if (schem.get("count")!=72 or schem.get("wires")!=144 or
            schem.get("physical_component_ref_count")!=72 or schem.get("issues")):
            raise RuntimeError("Native 72 Cout devices/144 schematic wires changed")
        result.update({"status":"V11_INDEPENDENT_NATIVE_GUI_REOPEN_AND_DRC_PASSED_NOT_FOR_FAB",
             "native_counts":counts,"real_native_DRC":category,
             "gate_nets_closed":sorted(k for k in post if k!="PGND" and post[k]==1),
             "ground_islands_before_and_after":[prev["PGND"],post["PGND"]],
             "COUT72_native_144_pinwire_parity":True,
             "32_added_native_trace_ids_preserved":True,
             "8_original_ground_spine_ids_removed":True})
    except Exception as e:
        result["error"]=str(e)
    finally:
        if sid:
            close=D.call(D.build_close_args(sid),timeout_s=35)
            result["own_verification_GUI_closed"]=close.get("ok") is True
        result["all_original_gui_sessions_preserved"]=user_gui.issubset(alive())
        result["V11_original_source_unchanged"]=V11.sha(V11.TARGET)==src
        result["V10_parent_source_unchanged"]=V11.sha(V11.SOURCE)==V11.SOURCE_SHA
        result["V11_clone_source_unchanged"]=V11.sha(clone)==src
        if result["status"]=="V11_INDEPENDENT_NATIVE_GUI_REOPEN_AND_DRC_PASSED_NOT_FOR_FAB" and not (
            result["all_original_gui_sessions_preserved"] and result["own_verification_GUI_closed"] and
            result["V11_original_source_unchanged"] and result["V10_parent_source_unchanged"] and
            result["V11_clone_source_unchanged"]):
            result["status"]="V11_INDEPENDENT_NATIVE_POSTCHECK_SAFETY_FAILED_NOT_FOR_FAB"
        if result.get("own_verification_GUI_closed"):
            try:clone.unlink();directory.rmdir();result["temporary_clone_cleaned"]=True
            except OSError:result["temporary_clone_cleaned"]=False
        V11.once(RECEIPT,result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result["status"]=="V11_INDEPENDENT_NATIVE_GUI_REOPEN_AND_DRC_PASSED_NOT_FOR_FAB" else 1


def main():
    p=argparse.ArgumentParser()
    z=p.add_mutually_exclusive_group(required=True)
    z.add_argument("--check",action="store_true")
    z.add_argument("--verify",action="store_true")
    a=p.parse_args()
    if a.check:
        sha=V11.sha(V11.TARGET)
        print(json.dumps({"V11_source_sha256":sha,"parent_V10_sha256":V11.SOURCE_SHA,
            "binary_saved":sha!=V11.SOURCE_SHA,
            "already_submitted":ATTEMPT.exists() or RECEIPT.exists(),"fabrication_approved":False}))
        return 0
    return verify()
if __name__=="__main__":
    raise SystemExit(main())

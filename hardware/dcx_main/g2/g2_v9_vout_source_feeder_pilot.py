"""One-shot real G2 V9 source-CTAP to Cout VOUT bottom collector feeder pilot.

This adds *three* independently scanned bottom-layer feeder tracks and plated
vias in an ALREADY OPEN, VISIBLE V9 native EasyEDA PCB. No GUI open/close,
no blind retries after native API timeout. Source V8 remains frozen; native
DRV/DRC + full copper islands are mandatory after saving V9.

This trial is NOT continuous 100 A qualified (existing bottom 1.6 mm collector,
vias and four source CTAP land pin current/thermal limits not qualified).
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(HERE))
import connect_t530_oem_16x5_bipolar as CONNECT
import g2_oem_net_islands as ISLAND
import g2_v9_real_t530_components as V9

READBACK=HERE/"g2_v9_two_page_readback_native_20261112_NOT_FOR_FAB.json"
PLAN=HERE/"g2_v9_vout_source_bottom_feeder_plan_NOT_FOR_FAB.json"
ATTEMPT=HERE/"g2_v9_vout_source_bottom_feeder_attempt_NOT_FOR_FAB.json"
VIAS_RECEIPT=HERE/"g2_v9_vout_source_bottom_feeder_vias_NOT_FOR_FAB.json"
LINES_RECEIPT=HERE/"g2_v9_vout_source_bottom_feeder_lines_NOT_FOR_FAB.json"
SAVE_RECEIPT=HERE/"g2_v9_vout_source_bottom_feeder_native_save_NOT_FOR_FAB.json"
VERIFY_RECEIPT=HERE/"g2_v9_vout_source_bottom_feeder_verified_NOT_FOR_FAB.json"
CANDIDATE_SHA="598e896935093e3c7c86bb18258c3e00c11edf1005c13fd0c885cb33085c6ce9"
WIDTH_MM=1.6
VIA_DIA_MM=1.0
VIA_HOLE_MM=.4
XS=(37,75,151)


def write_once(path,obj):
    if path.exists():
        raise FileExistsError(f"Never overwrite native write evidence: {path.name}")
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf8",newline="\n")


def freeze():
    if V9.sha(V9.V9)!=CANDIDATE_SHA:
        raise ValueError("Native PCB CAD source hash changed; reject new write")
    if not READBACK.is_file():
        raise FileNotFoundError(READBACK)
    r=json.loads(READBACK.read_text("utf8"))
    if not r.get("ok") or r["candidate_sha256"]!=CANDIDATE_SHA:
        raise ValueError("Full native readback source not current")
    v=r["value"]
    sizes={k:len(v[k]) for k in ("components","pads","lines","vias","nets")}
    if sizes!={"components":149,"pads":443,"lines":403,"vias":90,"nets":65}:
        raise ValueError("V9 source inventory differs")
    return v


def create_plan():
    v=freeze()
    islands=ISLAND.islands(v,{"VOUT"})["VOUT"]["islands"]
    if len(islands)!=2:
        raise ValueError("VOUT source/Cout islands not exactly two")
    ctap=[i for i,x in enumerate(islands) if "RAW.CTAP" in x["pads"]]
    cap=[i for i,x in enumerate(islands) if "CHB01.1" in x["pads"]]
    if len(ctap)!=1 or len(cap)!=1 or ctap[0]==cap[0]:
        raise ValueError("Physical VOUT source already joined or ambiguous")
    lines=[]
    vias=[]
    problems=[]
    for x in XS:
        lines.append(CONNECT._track("VOUT",2,(x,20),(x,94),WIDTH_MM))
        vias.append({"net":"VOUT","xy_mm":[x,20],
                     "diameter_mm":VIA_DIA_MM,"hole_mm":VIA_HOLE_MM})
    for i,q in enumerate(lines):
        for hit in CONNECT._conflicts_line(q,v):
            problems.append(f"line[{i}] {hit}")
    for i,q in enumerate(vias):
        for hit in CONNECT._conflicts_via(q,v):
            problems.append(f"via[{i}] {hit}")
    # Min spacing to board edge, before any manufacturer stackup.
    if any(x<3 or x>152 for x in XS):
        problems.append("PCB edge copper screening margin")
    return {"status":"REVIEWED_NATIVE_V9_TRIAL_BOTTOM_VOUT_SOURCE_FEEDERS_NOT_FOR_FAB",
            "source_sha256":CANDIDATE_SHA,
            "net":"VOUT","bottom_layer":2,
            "source_connected_vout_island_count":2,
            "source_ctap_pad_count":4,
            "target_cout_native_capacitor_count":72,
            "tracks":lines,"vias":vias,"physical_preflight_problems":sorted(set(problems)),
            "one_through_via_per_feeder_NOT_100A_RATED":True,
            "feeder_mm":WIDTH_MM,
            "full_100a_copper_ampacity_qualified":False,
            "magnetic_physical_pins_qualified":False,
            "fabrication_approved":False}


def check():
    p=create_plan()
    if p["physical_preflight_problems"]:
        raise RuntimeError(str(p["physical_preflight_problems"]))
    if PLAN.exists():
        if json.loads(PLAN.read_text("utf8"))!=p:
            raise ValueError("Previously frozen native V9 route plan differs")
    else:
        write_once(PLAN,p)
    print(json.dumps({k:v for k,v in p.items() if k not in ("tracks","vias")},
                     ensure_ascii=False,indent=2))


def invoke(session,script,timeout_ms=59000):
    return V9.D.call(V9.D.build_invoke_args(session,script,timeout_ms),timeout_s=72)


def apply():
    if any(x.exists() for x in (ATTEMPT,VIAS_RECEIPT,LINES_RECEIPT,SAVE_RECEIPT,VERIFY_RECEIPT)):
        raise FileExistsError("Native V9 source feeder attempt already happened, never replay")
    pre=create_plan()
    if pre["physical_preflight_problems"]:
        raise RuntimeError(str(pre["physical_preflight_problems"]))
    if not PLAN.exists() or json.loads(PLAN.read_text("utf8"))!=pre:
        raise ValueError("Frozen route plan not current")
    sid,pcb_uuid=V9.active_v9()
    source=V9.sha(V9.V9)
    if source!=CANDIDATE_SHA:
        raise ValueError("Source drift before native submission")
    write_once(ATTEMPT,{"status":"SUBMISSION_INITIATED_DO_NOT_RETRY",
       "gui_session":sid,"target":V9.V9.name,"source_sha256":source,
       "vias_requested":len(pre["vias"]),"lines_requested":len(pre["tracks"]),
       "do_not_replay_if_timeout":True,"fabrication_approved":False})
    # Native endpoint args using existing vetted line/via creator, no new GUI.
    reply_v=invoke(sid,CONNECT.js_vias(pre["vias"]))
    write_once(VIAS_RECEIPT,reply_v)
    if not reply_v.get("ok") or not (reply_v.get("value") or {}).get("all_created"):
        raise RuntimeError("Native via creation failed: DO NOT RETRY")
    reply_l=invoke(sid,CONNECT.js_tracks(pre["tracks"]))
    write_once(LINES_RECEIPT,reply_l)
    if not reply_l.get("ok") or not (reply_l.get("value") or {}).get("all_created"):
        raise RuntimeError("Native line creation failed: DO NOT RETRY")
    reply_save=invoke(sid,"return await eda.pcb_Document.save();",30000)
    write_once(SAVE_RECEIPT,reply_save)
    if not reply_save.get("ok") or reply_save.get("value") is not True:
        raise RuntimeError("Native save not acknowledged")
    time.sleep(26)
    if V9.sha(V9.V9)==source or V9.sha(V9.V8)!=V9.EXPECTED_V8_SHA:
        raise RuntimeError("Saved candidate not changed or old V8 changed")
    print(json.dumps({"status":"V9_3_REAL_BOT_VOUT_SOURCE_FEEDERS_SAVED_NOT_FOR_FAB",
        "new_sha256":V9.sha(V9.V9),"gui_left_open":True},indent=2))
    return 0


def main():
    p=argparse.ArgumentParser()
    g=p.add_mutually_exclusive_group(required=True)
    g.add_argument("--check",action="store_true")
    g.add_argument("--apply",action="store_true")
    a=p.parse_args()
    if a.check:
        check()
    if a.apply:
        return apply()
    return 0

if __name__=="__main__":
    raise SystemExit(main())

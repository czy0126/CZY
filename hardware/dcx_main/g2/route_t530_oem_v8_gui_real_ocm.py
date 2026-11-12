"""One-shot GUI-native OCM pilot on isolated V8; do not close EDA GUI.

Two commands:
    python hardware/dcx_main/g2/route_t530_oem_v8_gui_real_ocm.py --apply
    python hardware/dcx_main/g2/route_t530_oem_v8_gui_real_ocm.py --verify

A pre-write receipt prevents retries after unknown/partial native outcomes.
NOT_FOR_FAB throughout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import route_t530_oem_v6_ocm_one_real_island_join as V6

TARGET = HERE / "dcx_main_board_g2_T530_OEM_DENSITY_B_V8_GUI_REAL_OCM_NOT_FOR_FAB.eprj2"
PREFIX = "g2_t530_oem_v8_gui_ocm"
ATTEMPT = HERE / (PREFIX + "_attempt.json")
APPLIED = HERE / (PREFIX + "_apply.json")
VERIFIED = HERE / (PREFIX + "_verification.json")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def record(path, data):
    if path.exists():
        raise FileExistsError("Never overwrite native evidence: " + str(path))
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf8", newline="\n")


def session():
    d = V6.V.A.D
    listing = d.call([str(d.LEDA), "session", "list"], timeout_s=25)
    if not listing.get("ok"):
        raise RuntimeError("Native EDA session listing failed")
    matches = []
    for item in listing["value"]:
        if item.get("headless") is not False or item.get("status") != "alive":
            continue
        sid = item["sessionId"]
        js = """return await (async()=>{
         const p=await eda.dmt_Project.getCurrentProjectInfo();
         return {name:p?.friendlyName,pcb:p?.data?.find(x=>x?.pcb?.uuid)?.pcb?.uuid};
         })();"""
        reply = d.call(d.build_invoke_args(sid, js, 9000), timeout_s=17)
        if (reply.get("ok") and (reply.get("value") or {}).get("name") == TARGET.stem
                and (reply["value"] or {}).get("pcb")):
            matches.append(sid)
    if len(matches) != 1:
        raise RuntimeError("No unique alive visible V8 session, count=" + str(len(matches)))
    return matches[0]


def apply():
    if ATTEMPT.exists() or APPLIED.exists() or VERIFIED.exists():
        raise FileExistsError("Already attempted. Never replay a native mutation.")
    plan = V6.geometry_plan()
    if plan["preflight_problems"]:
        raise ValueError(plan["preflight_problems"])
    if not TARGET.is_file() or sha(TARGET) != sha(V6.SOURCE):
        raise ValueError("V8 is not untouched frozen V5 copy")
    if not V6.PLAN.is_file() or json.loads(V6.PLAN.read_text(encoding="utf8")) != plan:
        raise ValueError("Frozen reviewed route plan is missing or altered")
    before = sha(V6.SOURCE)
    sid = session()
    rb = V6.V.A.invoke(sid, V6.V.A.READ_JS.read_text(encoding="utf8"))
    if not rb.get("ok"):
        raise RuntimeError("Real GUI native read failed; no write")
    value = rb["value"]
    if tuple(len(value[k]) for k in ("components","pads","lines","vias","nets")) != V6.EXPECTED_COUNTS:
        raise ValueError("V8 native counts differ from frozen design")
    groups = V6.V.ISLAND.islands(value, {"OCM"})["OCM"]["islands"]
    ids = [[i for i,g in enumerate(groups) if name in g["pads"]]
           for name in (V6.START,V6.END)]
    if any(len(x)!=1 for x in ids) or ids[0] == ids[1]:
        raise ValueError("OCM targets not distinct copper islands")
    if sha(TARGET) != before:
        raise ValueError("V8 file changed during no-write preflight")
    record(ATTEMPT, {"status":"NATIVE_WRITE_SUBMISSION_NOT_CONFIRMED",
                     "source_sha256":before,"candidate_before_sha256":sha(TARGET),
                     "gui_session":sid,"net":"OCM","segments":len(plan["tracks"]),
                     "do_not_retry_even_on_timeout":True,"fabrication_approved":False})
    js = """return await (async()=>{
       const p=await eda.dmt_Project.getCurrentProjectInfo();
       if(p?.friendlyName!==%s)throw new Error("Wrong visible GUI project");
       %s
    })();""" % (json.dumps(TARGET.stem),V6.V.C.js_tracks(plan["tracks"]))
    outcome = V6.V.A.invoke(sid, js)
    record(APPLIED, {"ok":outcome.get("ok"),"value":outcome.get("value"),
                     "error":outcome.get("error"),"source_unchanged":sha(V6.SOURCE)==before})
    if not outcome.get("ok") or not (outcome.get("value") or {}).get("all_created"):
        raise RuntimeError("Native write unverified. Do not replay.")
    saved=V6.V.A.invoke(sid,"return await eda.pcb_Document.save();")
    record(HERE/(PREFIX+"_save.json"),saved)
    if not saved.get("ok") or saved.get("value") is not True:
        raise RuntimeError("Native save not acknowledged. Do not replay.")
    time.sleep(28)
    if sha(TARGET)==before or sha(V6.SOURCE)!=before:
        raise RuntimeError("Native file save/source hashes not verified")
    print(json.dumps({"status":"V8_SAVED_NOT_FOR_FAB","gui_session":sid,
                      "candidate_sha256":sha(TARGET),"v5_unchanged":True,
                      "gui_left_open":True},indent=2))
    return 0


def verify():
    if VERIFIED.exists():
        raise FileExistsError("Already verified")
    if not ATTEMPT.exists() or not APPLIED.exists() or sha(TARGET)==sha(V6.SOURCE):
        raise RuntimeError("No proven distinct saved native V8")
    plan=V6.geometry_plan()
    before=sha(V6.SOURCE)
    sid=session()
    rb=V6.V.A.invoke(sid,V6.V.A.READ_JS.read_text(encoding="utf8"))
    if not rb.get("ok"):
        raise RuntimeError("Real GUI readback failed")
    audit=V6.verify_target(rb["value"],plan)
    drc=V6.V.A.invoke(sid,V6.V.A.DRC_JS.read_text(encoding="utf8"))
    if not drc.get("ok"):
        raise RuntimeError("Native DRC failed")
    cats=V6.V.A.R.categories(drc)
    if (cats.get("Connection Error",999)>=172 or cats.get("Netlist Error",999)>1
        or cats.get("Physical Error",0)!=0):
        raise RuntimeError("Native DRC failed improvement or physical safety gate")
    if sha(V6.SOURCE)!=before:
        raise RuntimeError("V5 changed during V8 verification")
    report={"status":"V8_REAL_GUI_NATIVE_OCM_ISLAND_JOIN_NOT_FOR_FAB",
            "candidate_sha256":sha(TARGET),"v5_sha256":before,
            "native_counts":{k:len(rb["value"][k]) for k in
              ("components","pads","lines","vias","nets")},
            "native_drc":cats,"route":audit,"gui_kept_open":True,
            "100A_approved":False,"72_caps_real_instances_verified":False,
            "fabrication_approved":False}
    record(VERIFIED,report)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0


def main():
    a=argparse.ArgumentParser()
    g=a.add_mutually_exclusive_group(required=True)
    g.add_argument("--apply",action="store_true")
    g.add_argument("--verify",action="store_true")
    args=a.parse_args()
    return apply() if args.apply else verify()


if __name__ == "__main__":
    raise SystemExit(main())

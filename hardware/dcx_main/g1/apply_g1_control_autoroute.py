"""One-command staged *native* G1 low-current autorouting, after the 12-pad batch.

Why: native DRC 199 Connection Errors repeatedly survive offline PRECHECK PRs.
The EasyEDA Pro extension API actually supports selected-net autorouting since
v3.2.150. Scope the editor's betatype router to eight named LOW-CURRENT
control/protection nets, NEVER PGND/VOUT/SW/VIN_P/SEC/PRI/SR gates or Kelvin.

Use one command ON THE LICENSED WINDOWS EDA HOST:
  python hardware/dcx_main/g1/apply_g1_control_autoroute.py --apply

--apply:
  1. Execute PR91's already-reviewed 12-route native copy (if it has not run).
  2. Verify PR91 actually saved/reopened, its SHA and reduced native DRC.
  3. COPY that board to a third, non-overwriting candidate, never edit parents.
  4. Invoke native pcb_Document.autoRouting(RoutingNets=ALLOW,
     ignoreNets=ALL_OTHER_G1_NETS, layers=[1], keep existing default).
  5. Save, close, reopen, audit EVERY original trace/pad/net and ALL new nets.
  6. Run native DRC; accept only if Connection errors further decline,
     Netlist does not grow, Physical stays zero and no existing copper changed.

This is NOT executed by GitHub Linux CI. Do not claim the 199 count changes
until original EasyEDA evidence is committed. Fails closed if a beta EDA
version silently ignores the RoutingNets case-sensitive property.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import apply_increment as E
import apply_g1_open_batch as STAGE1
import route_open_connections as G1
import run_driver_drc as D
import audit_driver_eco as A

HERE=Path(__file__).resolve().parent
STAGE1_BOARD=STAGE1.TARGET
STAGE2_BOARD=HERE/"dcx_main_board_g1_control_autoroute.eprj2"
STAGE1_REOPEN=G1.READBACK_OUT
STAGE2_REOPEN=HERE/"g1_control_autoroute_reopen_readback.json"
STAGE2_JS=HERE/"g1_control_autoroute_native.js"
STAGE2_APPLY=HERE/"g1_control_autoroute_apply.json"
STAGE2_DRC=HERE/"g1_control_autoroute_drc_raw.json"
STAGE2_REPORT=HERE/"g1_control_autoroute_drc_delta.json"
PREFIX="g1_control_autoroute"

# Top-side, low-current CONTROL/FAULT nets. OC/OCM/OCD still need noise and
# fault-capture timing review; DRC reduction alone does not sign their quality.
# Deliberately EXCLUDE all 100A, resonant, power, Kelvin and SR gate networks.
ROUTE_NETS=(
    "RUN","SS","DT","RT","OC1","OC","OCM","OCD"
)


def sha(path:Path)->str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plan() -> dict:
    current=G1.source()  # signed current 107-line, 299-pad, SHA, 199 DRC
    names=current["nets"]
    if not isinstance(names,list) or len(names)!=65 or len(set(names))!=65:
        raise ValueError("Active EasyEDA G1 net inventory changed")
    if len(ROUTE_NETS)!=8 or len(set(ROUTE_NETS))!=8:
        raise ValueError("Native low-risk autorouter whitelist changed")
    if not set(ROUTE_NETS).issubset(set(names)):
        raise ValueError("Selected native control net is absent from G1")
    banned=[x for x in names if x not in ROUTE_NETS]
    if len(banned)!=57:raise ValueError("Not all excluded power and gate nets were forbidden")
    if not {"PGND","VOUT","VIN_P","SW","CT_LR","SEC1_A","GA1","VG1_A","REG1"}.issubset(banned):
        raise ValueError("Dangerous output/driver net escaped exclusion")
    before=G1.categories(json.loads(G1.DRC.read_text(encoding="utf-8")))
    found={x["name"]:len(x["list"]) for x in
           json.loads(G1.DRC.read_text(encoding="utf-8"))["value"]["raw"][0]["list"]}
    # The original DRC export has the selected eight nets, but the DRC
    # subcategory's number of *reports* differs from the actual wire count.
    if any(x not in found for x in ROUTE_NETS):
        raise ValueError("Auto-routing selected a net with no original native DRC evidence")
    return {
        "status":"SOURCE_LOCKED_SELECTED_NATIVE_AUTOROUTER_READY_NOT_EXECUTED",
        "source_sha256":sha(G1.SOURCE),
        "net_count":len(names),
        "routing_nets":list(ROUTE_NETS),
        "ignoring_nets":banned,
        "routing_drc_subcategories":{n:found[n] for n in ROUTE_NETS},
        "source_native_drc":before,
        "stage1_native_candidate":STAGE1_BOARD.name,
        "stage2_native_candidate":STAGE2_BOARD.name,
        "eda_api_min_version":"3.2.150",
        "routing_layer":1,
        "no_autorouting_power_or_kelvin_nets":True,
        "native_eda_applied":False,
        "fabrication_approved":False,
    }


def js_body(config:dict) -> str:
    # Exact property is *RoutingNets*, not 'nets' from an inconsistent example;
    # use ignoreNets as independent protection against scope being ignored.
    allow=json.dumps(config["routing_nets"])
    exclude=json.dumps(config["ignoring_nets"])
    return f"""// Generated EasyEDA native PCB script; never use on original G1 parent.
const allow={allow};
const excluded={exclude};
if (allow.length !== 8 || excluded.length !== 57) {{
  throw new Error('Wrong G1 autoRoute net scope; refusing');
}}
const result=await eda.pcb_Document.autoRouting({{
  RoutingNets: allow,
  ignoreNets: excluded,
  layers: [1]
}});
if (!result || typeof result !== 'object') {{
  throw new Error('EasyEDA autoRouting did not provide a completion result');
}}
const saved=await eda.pcb_Document.save();
return {{routeResult: result, saved: saved,
         allowed: allow, excludedCount: excluded.length,
         fabricationApproved: false}};"""


def stage1_verified() -> dict:
    if not STAGE1_BOARD.is_file() or not STAGE1.DELTA.is_file():
        raise FileNotFoundError("Actual first 12 native routes and original DRC evidence are missing")
    data=json.loads(STAGE1.DELTA.read_text(encoding="utf-8"))
    if (data.get("status")!="ACTUAL_EASYEDA_COPPER_IMPROVED_NOT_FOR_FAB"
         or data.get("parent_sha256")!=sha(G1.SOURCE)
         or data.get("candidate_sha256")!=sha(STAGE1_BOARD)
         or data.get("candidate_drc_sha256")!=sha(STAGE1.AFTER_DRC)
         or data.get("native_connection_errors_reduced",0)<1
         or data.get("full_board_fabrication_approved") is not False):
        raise ValueError("First 12 native tracks are not bound to their real PCB/DRC")
    # Do not blindly trust a stored 'reduced' boolean.
    b=data["source_drc"];a=data["native_reopen_drc"]
    now=G1.categories(json.loads(STAGE1.AFTER_DRC.read_text(encoding="utf-8")))
    if (now!=a or b.get("Connection Error")!=199
         or now.get("Connection Error",999)>=199
         or now.get("Netlist Error",0)>1 or now.get("Physical Error",0)>0):
        raise ValueError("First native 12-route DRC delta is inconsistent")
    saved=json.loads(STAGE1_REOPEN.read_text(encoding="utf-8"))
    if saved.get("ok") is not True or not saved.get("value"):
        raise ValueError("First native copy did not reopen successfully")
    return saved["value"]


def compare_readback(original:dict,current:dict) -> dict:
    problems=[]
    for key in ("components","pads","nets"):
        # PCB routing must never change components, pad nets/XY or set of nets.
        # Stable original editor sessions preserve these source arrays.
        if original[key]!=current.get(key):
            problems.append(f"Existing {key} changed by autorouter")
    if original["vias"]!=current.get("vias"):
        problems.append("Autorouter created/removed/modified vias despite L1-only configuration")
    old={s["id"]:s for s in original["lines"]}
    new={s["id"]:s for s in current.get("lines",[])}
    for id,a in old.items():
        if id not in new:
            problems.append(f"Original copper line missing {id}")
            continue
        b=new[id]
        if any(a[k]!=b.get(k) for k in ("net","layer","x1","y1","x2","y2","width")):
            problems.append(f"Original copper line geometry changed {id}")
    added=[x for id,x in new.items() if id not in old]
    unexpected=sorted({x["net"] for x in added if x.get("net") not in ROUTE_NETS})
    if unexpected:
        problems.append(f"Unauthorized new copper on excluded nets {unexpected}")
    if any(x.get("layer")!=1 for x in added):
        problems.append("Autorouter created non-top-layer track")
    if not added:
        problems.append("AutoRouting produced no new native copper")
    return {
        "original_lines":len(old),"after_lines":len(new),
        "added_line_count":len(added),
        "added_nets":sorted({x.get("net") for x in added}),
        "unexpected_nets":unexpected,
        "problems":problems,
        "readback_accepted_for_native_drc":not problems,
        "fabrication_approved":False,
    }


def compare_native_drc(first:dict,second:dict)->dict:
    first_drc=G1.categories(json.loads(STAGE1.AFTER_DRC.read_text(encoding="utf-8")))
    new_drc=G1.categories(json.loads(STAGE2_DRC.read_text(encoding="utf-8")))
    missing=[x for x,n in first_drc.items() if n>0 and x not in new_drc]
    if missing:raise ValueError("Native DRC error category disappeared: "+repr(missing))
    if new_drc.get("Connection Error",999)>=first_drc["Connection Error"]:
        raise ValueError("Native autoRoute did not decrease real open connections")
    if new_drc.get("Netlist Error",0)>first_drc.get("Netlist Error",0):
        raise ValueError("Native autoRoute introduced netlist mismatch")
    if new_drc.get("Physical Error",0)>0:
        raise ValueError("Native autoRoute introduced physical DRC error")
    if any(new_drc.get(x,0)>first_drc.get(x,0) for x in new_drc.keys() | first_drc.keys()):
        raise ValueError("New native DRC rule category/error introduced")
    return {
        "source_board":STAGE1_BOARD.name,
        "source_sha256":sha(STAGE1_BOARD),
        "output_board":STAGE2_BOARD.name,
        "output_sha256":sha(STAGE2_BOARD),
        "source_drc":first_drc,
        "native_reopen_drc":new_drc,
        "extra_real_connection_errors_removed":
            first_drc["Connection Error"]-new_drc["Connection Error"],
        "first_stage_native_199_baseline":199,
        "actual_origin_199_to_new_count":new_drc["Connection Error"],
        "status":"REAL_NATIVE_DRC_REDUCTION_PROVISIONAL_NEEDS_KELVIN_AND_FAULT_SIGNOFF",
        "fab_approved":False,
    }


def apply()->int:
    config=plan()
    # Single command: apply the #91 reviewed batch first if not present.
    if not STAGE1_BOARD.exists() and not STAGE1.DELTA.exists():
        if STAGE1.apply():
            raise RuntimeError("First native 12-route batch failed. Do not autoroute unverified parent.")
    first=stage1_verified()
    if STAGE2_BOARD.exists():
        raise FileExistsError("Refusing to overwrite prior native autoRoute candidate: "+str(STAGE2_BOARD))
    shutil.copy2(STAGE1_BOARD,STAGE2_BOARD)
    target=STAGE2_BOARD
    prior=sha(STAGE1_BOARD)
    print(f"Actual stage-1 12-route SHA: {prior}; copied for selected-net native autoRoute")
    session=E.open_and_ping(target,PREFIX,"apply")
    if not session:raise RuntimeError("Native EasyEDA autoroute candidate failed to open")
    result=None
    try:
        # Native router has an *internal* 900-second hard limit independent
        # from CLI --timeout. Allow the CLI to return an explicit failure.
        result=D.call(D.build_invoke_args(session,js_body(config),timeout_ms=930000),
                      timeout_s=960)
    finally:
        E.dump(PREFIX,"apply",result or {"ok":False,"why":"CLI_EXCEPTION"})
        time.sleep(30)  # ensure EDA's asynchronous save debounce completes
        E.dump(PREFIX,"close",D.call(D.build_close_args(session)))
    if sha(STAGE1_BOARD)!=prior or sha(G1.SOURCE)!=config["source_sha256"]:
        raise RuntimeError("Source board changed during native autoRoute")
    info=(result or {}).get("value") or {}
    if not result or not result.get("ok") or not info.get("saved"):
        raise RuntimeError("Native selected-net routing did not save successfully")
    session=E.open_and_ping(target,PREFIX,"reopen")
    if not session:raise RuntimeError("Could not reopen selected-net routed copy")
    try:
        after=E.invoke(session,E.READ_JS.read_text(encoding="utf-8"))
    finally:
        E.dump(PREFIX,"reopen_close",D.call(D.build_close_args(session)))
    STAGE2_REOPEN.write_text(json.dumps(after,ensure_ascii=False,indent=2)+"\n",
                             encoding="utf-8")
    if after.get("ok") is not True or not isinstance(after.get("value"),dict):
        raise RuntimeError("Native autoRoute board readback invalid")
    geometry=compare_readback(first,after["value"])
    if geometry["problems"]:
        raise RuntimeError("Native autoroute copper scope/layout rejected: "+str(geometry["problems"][:8]))
    drc_cmd=[sys.executable,str(HERE/"run_driver_drc.py"),
             "--board",str(STAGE2_BOARD),"--prefix",PREFIX+"_drc"]
    subprocess.run(drc_cmd,check=True)
    drc=compare_native_drc(first,after["value"])
    drc["native_new_copper_evidence"]=geometry
    drc["beta_software_and_real_OC_noise_review_pending"]=True
    STAGE2_REPORT.write_text(json.dumps(drc,ensure_ascii=False,indent=2)+"\n",
                             encoding="utf-8")
    print(json.dumps(drc,ensure_ascii=False,indent=2))
    return 0


def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    exclusive=parser.add_mutually_exclusive_group(required=True)
    exclusive.add_argument("--check",action="store_true")
    exclusive.add_argument("--emit-js",action="store_true")
    exclusive.add_argument("--apply",action="store_true")
    args=parser.parse_args()
    d=plan()
    if args.check:
        print(json.dumps(d,ensure_ascii=False,indent=2))
        return 0
    if args.emit_js:
        print(js_body(d))
        return 0
    return apply()


if __name__=="__main__":
    raise SystemExit(main())

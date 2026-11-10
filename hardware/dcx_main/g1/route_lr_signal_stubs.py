"""Prepare exactly NINE same-net low-current signal stubs on the applied native G1.

Only the nine vetted, direct short segments are allowed (no magnet terminals, no
100 A output rail, no 8 SR gate/VD Kelvin links). Six supply/decoupling connections, the controller RUN link, and two OC
filter/divider links are planned on layer 1.

Only SOURCE is validated now; actual native EasyEDA routing is separate and
must be applied to a NEW copy on a licensed/installed Windows EDA host:

  python hardware/dcx_main/g1/route_lr_signal_stubs.py --check
  python hardware/dcx_main/g1/route_lr_signal_stubs.py --emit-js
  python hardware/dcx_main/g1/apply_lr_signal_stubs.py --apply

The passed offline 0-conflict check is *not* native DRC, 3D, Maxwell, or fab.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'tools'))
import route_driver_eco as R
import audit_driver_eco as E
import g1_magnetics_envelope as geom

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = HERE / "dcx_main_board_g1_lr_repack.eprj2"
READBACK = HERE / "lr_repack_readback.json"
PARENT_REPORT = HERE / "lr_repack_native_report.json"
CANDIDATE = "dcx_main_board_g1_signal_stubs.eprj2"
READBACK_OUT = HERE / "lr_signal_readback.json"
REPORT_OUT = HERE / "lr_signal_native_report.json"
PLAN_OUT = HERE / "lr_signal_route_plan.json"

# Routing is intentionally limited to the currently re-opened, known-safe
# direct endpoint pairs. C106 -> U4 would short/pass through U4.8 / C106.2,
# so it is explicitly excluded rather than silently creating copper.
PAIRS = (
    ("C101", "1", "U2", "1", "VCC12"),
    ("C102", "1", "U1", "7", "VCC12"),
    ("C103", "1", "C104", "1", "VCC12"),
    ("C105", "1", "U3", "7", "VCC12_S"),
    ("C107", "1", "U5", "7", "VCC12_S"),
    ("C108", "1", "U6", "7", "VCC12_S"),
    ("R7", "1", "U2", "6", "RUN"),
    ("R15", "2", "R16", "1", "OC1"),
    ("R16", "2", "R17", "1", "OC"),
)
WIDTH_MM = .20
CLEARANCE_MM = R.CLEARANCE
BASE_COMPONENTS = 77
BASE_PADS = 299
BASE_NETS = 65
BASE_LINES = 98
BASE_VIAS = 18
BASE_POLYLINES = 38
MAX_ALLOWED_ROUTE_LENGTH_MM = 4.0


def value(path: Path) -> dict:
    v = json.loads(path.read_text(encoding="utf-8"))
    if v.get("ok") is not True or not isinstance(v.get("value"), dict):
        raise ValueError(f"Native EDA reopen not successful: {path}")
    return v["value"]


def parent() -> dict:
    report = json.loads(PARENT_REPORT.read_text(encoding="utf-8"))
    if report["candidate_sha256"] != hashlib.sha256(SOURCE.read_bytes()).hexdigest():
        raise ValueError("Lr source native .eprj2 hash changed; abort new routing")
    if report["candidate"] != SOURCE.relative_to(ROOT).as_posix() or report["fab_release"]:
        raise ValueError("Unexpected native Lr source or fabrication approval")
    if (report["components"], report["pads"], report["nets"], report["lines"],
            report["vias"]) != (BASE_COMPONENTS, BASE_PADS, BASE_NETS, BASE_LINES, BASE_VIAS):
        raise ValueError("Unexpected Lr ECO parent's component/routing counts")
    if geom.git_blob_sha(READBACK) != geom.git_blob_sha(geom.ACTIVE_READBACK):
        raise ValueError("Lr source does not match the active magnetic clearance audit")
    p = value(READBACK)
    if (len(p["components"]),len(p["pads"]),len(p["nets"]),len(p["lines"]),
            len(p["vias"]),p["polylines"]) != (
                BASE_COMPONENTS,BASE_PADS,BASE_NETS,BASE_LINES,BASE_VIAS,BASE_POLYLINES):
        raise ValueError("Native parent reopen counts changed; regenerate plan")
    return p


def reference_pad(pads: list[dict], ref: str, pin: str, net: str) -> tuple:
    found = [p for p in pads if p.get("ref")==ref
             and str(p.get("PadNumber"))==pin]
    if len(found)!=1 or found[0].get("Net")!=net:
        raise ValueError(f"Missing or wrong native net for {ref}.{pin} (expected {net})")
    p = found[0]
    if p["Layer"] not in (1,12,0):
        raise ValueError(f"{ref}.{pin} cannot be touched by a layer-1 trace")
    return (p["X"]/R.MIL, -p["Y"]/R.MIL)


def copper() -> dict:
    p = parent()
    plan = {}
    for ref1,pin1,ref2,pin2,net in PAIRS:
        a = reference_pad(p["pads"],ref1,pin1,net)
        b = reference_pad(p["pads"],ref2,pin2,net)
        length = math.dist(a,b)
        if not .6 < length < MAX_ALLOWED_ROUTE_LENGTH_MM:
            raise ValueError(f"Endpoint length changed {ref1}.{pin1}->{ref2}.{pin2}: {length}")
        plan.setdefault(net, {"width": WIDTH_MM, "layer": 1, "paths": []})
        plan[net]["paths"].append([a,b])
    if len(R.segments(plan))!=9 or sorted(plan)!=["OC","OC1","RUN","VCC12","VCC12_S"]:
        raise ValueError("Unexpected low-current routing scope")
    return plan


def vias() -> list:
    return []


def source_segments() -> list:
    return R.lines_from_readback(READBACK)


def source_vias() -> list:
    return R.vias_from_readback(READBACK)


def problems() -> list:
    p = parent()
    planned = copper()
    pads = R.load_pads(READBACK)
    s = R.segments(planned)
    issues = R.check_plan(pads,planned,clearance=CLEARANCE_MM)

    # Existing lines and vias are actual already-routed power/driver/CT
    # geometry. Checking only the nine NEW lines against themselves is unsafe.
    for route in s:
        for previous in source_segments():
            if previous["net"]==route["net"] or previous["layer"]!=route["layer"]:
                continue
            d = R._segment_segment(route["a"],route["b"],previous["a"],previous["b"])
            margin = d-(route["width"]+previous["width"])/2
            if margin + 1e-9 < CLEARANCE_MM:
                issues.append({"kind":"preexisting-copper","new_net":route["net"],
                               "existing_net":previous["net"],
                               "clearance_mm":round(margin,4)})
        for priorvia in source_vias():
            if priorvia["net"] == route["net"]:
                continue
            d = R._point_segment(priorvia["x"],priorvia["y"],route["a"],route["b"])
            margin = d-(route["width"]+priorvia["diameter"])/2
            if margin + 1e-9 < CLEARANCE_MM:
                issues.append({"kind":"preexisting-via","new_net":route["net"],
                               "existing_net":priorvia["net"],
                               "clearance_mm":round(margin,4)})
    # Keep away from Lr ferrite body (a geometrical concept), even if
    # technically it might allow under-body copper with later Z evidence.
    base = geom.load_current()
    m = json.loads(geom.MAG.read_text(encoding="utf-8"))
    body,transformers,_ = geom.core_rects(base,m)
    for seg in s:
        bodylist = [("Lr",body),*transformers.items()]
        for ref,b in bodylist:
            rect=(b["left"],b["top"],b["right"],b["bottom"])
            gap=R._segment_rect(seg["a"],seg["b"],rect)-seg["width"]/2
            if gap < .5:
                issues.append({"kind":"concept-magnet-body","net":seg["net"],
                               "magnet":ref,"margin_mm":round(gap,4)})
    return issues


def report() -> dict:
    p = parent()
    segments=R.segments(copper())
    issues=problems()
    audit={
        "status":"REAL_NATIVE_LR_BOARD_SIGNAL_STUBS_CANDIDATE_NOT_APPLIED",
        "native_source":SOURCE.relative_to(ROOT).as_posix(),
        "source_sha256":hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "source_reopen":READBACK.relative_to(ROOT).as_posix(),
        "source_readback_git_blob_sha":geom.git_blob_sha(READBACK),
        "candidate":CANDIDATE,
        "source_counts":{"components":len(p["components"]),"pads":len(p["pads"]),
                         "nets":len(p["nets"]),"lines":len(p["lines"]),
                         "vias":len(p["vias"]),"polylines":p["polylines"]},
        "routes":[{"from":f"{r1}.{pin1}","to":f"{r2}.{pin2}","net":net,
                   "layer":1,"width_mm":WIDTH_MM,
                   "length_mm":round(math.dist(s["a"],s["b"]),4)}
                  for (r1,pin1,r2,pin2,net),s in zip(PAIRS,segments)],
        "new_trace_count":len(segments),
        "new_via_count":0,
        "total_additional_length_mm":round(sum(math.dist(x["a"],x["b"])
                                                 for x in segments),4),
        "minimum_clearance_policy_mm":CLEARANCE_MM,
        "preflight_problems":issues,
        "forbidden_not_routed":["C106.1→U4.7: short-circuits U4.8 wrong-net pad on direct line; requires reroute",
                                "Lr actual CT_LR and PRI_T1: magnetic terminals unverified",
                                "100A VOUT+PGND output copper and CT provisional PADs",
                                "remaining SR gate and source Kelvin pairs"],
        "native_eda_run":False,"native_drc_result":None,
        "maxwell_executed":False,"fab_approved":False
    }
    return audit


def verify(readback: Path=READBACK_OUT) -> dict:
    before=parent()
    after=value(readback)
    pl=copper()
    expected=R.segments(pl)
    old_lines={x["id"]:x for x in before["lines"]}
    new_lines={x["id"]:x for x in after["lines"]}
    layout_problems=[]
    if not set(old_lines).issubset(set(new_lines)):
        layout_problems.append("Native existing 98 copper line IDs missing after applying")
    for line_id,o in old_lines.items():
        n=new_lines.get(line_id)
        if n is None:
            continue
        for key in ("net","layer","x1","y1","x2","y2","width"):
            if key in ("net","layer"):
                if n[key]!=o[key]:layout_problems.append(f"Existing line {line_id} net/layer changed")
            elif abs(float(n[key])-float(o[key]))>.25:
                layout_problems.append(f"Existing line {line_id} geometry changed {key}")
    if (len(after["components"]),len(after["pads"]),len(after["nets"]),
            len(after["vias"]),after["polylines"]) != (
                BASE_COMPONENTS,BASE_PADS,BASE_NETS,BASE_VIAS,BASE_POLYLINES):
        layout_problems.append("Native component/pad/net/via/polyline counts changed")
    if len(after["lines"]) < BASE_LINES+9:
        layout_problems.append("Not all nine intended copper segments added")
    oldorig={x["ref"]:(x["X"],x["Y"]) for x in before["components"]}
    neworig={x["ref"]:(x["X"],x["Y"]) for x in after["components"]}
    if oldorig!=neworig:
        layout_problems.append("Component locations changed during signal-stub routing")
    if not E.pads_match(before["pads"],oldorig,after["pads"],neworig):
        layout_problems.append("Pad net/footprint/local geometry changed during stub routing")
    old_vias={v["id"]:v for v in before["vias"]}
    new_vias={v["id"]:v for v in after["vias"]}
    if old_vias!=new_vias:
        layout_problems.append("Existing native via identities or geometries changed")
    # Coverage check allows the native editor to split a newly created segment
    # into two collinear pieces, but every point on the intended line must
    # exist in the saved/re-opened board at the correct width, layer, and net.
    new_s=R.lines_from_readback(readback)
    problems=[]
    for seg in expected:
        ok,reasons=R._covered(seg,[x for x in new_s if x["net"]==seg["net"]])
        if not ok:
            problems.append({"net":seg["net"],"at":[seg["a"],seg["b"]],"why":reasons})
    if not layout_problems and not problems:
        status="REOPENED_NATIVE_SIGNAL_STUBS_PENDING_ACTUAL_DRC"
    else:
        status="NATIVE_ROUTING_REOPEN_VERIFICATION_FAILED"
    return {
        "status":status,"source_cad":SOURCE.relative_to(ROOT).as_posix(),
        "candidate":CANDIDATE,"new_seg_count":len(after["lines"])-BASE_LINES,
        "layout_counts":{"unchanged":not layout_problems,"errors":layout_problems},
        "lines":{"planned_segments":len(expected),"coverage_problems":problems},
        "vias":{"planned":0,"problems":[] if old_vias==new_vias else ["via changed"]},
        "placement_drift":[] if oldorig==neworig else ["component moved"],
        "native_drc_passed":False,"fab_release":False,
    }


def main() -> int:
    ap=argparse.ArgumentParser(description=__doc__)
    group=ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--check",action="store_true")
    group.add_argument("--emit-js",action="store_true")
    group.add_argument("--write-plan",action="store_true")
    group.add_argument("--verify",action="store_true")
    args=ap.parse_args()
    if args.verify:
        result=verify()
        REPORT_OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        is_ok=(result["layout_counts"]["unchanged"] and
               not result["lines"]["coverage_problems"] and
               not result["vias"]["problems"] and
               not result["placement_drift"])
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0 if is_ok else 1
    payload=report()
    if payload["preflight_problems"]:
        print(json.dumps(payload,ensure_ascii=False,indent=2))
        return 1
    if args.emit_js:
        print(R.emit_js(copper(),[]))
    elif args.write_plan:
        PLAN_OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(f"Wrote {PLAN_OUT}")
    else:
        print(json.dumps(payload,ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())

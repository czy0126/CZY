"""Native EasyEDA host runner for the *review-only* Lr/11-passive G1 repack.

Windows host prerequisites: installed licensed EasyEDA Pro and its proven
lceda-pro.exe CLI, a separate process with exclusive access to the project.

    python hardware/dcx_main/g1/apply_lr_repack.py --check
    python hardware/dcx_main/g1/apply_lr_repack.py --apply

--apply ALWAYS copies dcx_main_board_g1_kelvin.eprj2 into a NEW
dcx_main_board_g1_lr_repack.eprj2. It refuses to overwrite a previous trial;
the baseline and golden source are NEVER opened for editing.

After saving, it closes and reopens the candidate and checks all real native
component positions, counts, pad net identities and existing line/via geometry,
then runs a read-only native GUI DRC and preserves original raw error counts.
It does NOT approve G1 layout, Maxwell, ampacity, physical windings or fab.
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

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/"tools"))
import g1_lr_repack_ready as R
import g1_magnetics_envelope as G
import apply_increment as A
import run_driver_drc as D

SOURCE=HERE/"dcx_main_board_g1_kelvin.eprj2"
TARGET=HERE/"dcx_main_board_g1_lr_repack.eprj2"
READBACK=HERE/"lr_repack_readback.json"
REPORT=HERE/"lr_repack_native_report.json"
PREFIX="lr_repack"


def hashfile(path:Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def native_verify(original:dict, fresh:dict, planned:dict) -> dict:
    if not fresh.get("ok") or not isinstance(fresh.get("value"),dict):
        raise ValueError("Saved/reopened EasyEDA PCB readback not successful")
    v=fresh["value"]
    before={x["ref"]:x for x in original["components"]}
    after={x["ref"]:x for x in v.get("components",[])}
    moves=planned["moves"]
    if set(before)!=set(after) or len(before)!=77:
        raise ValueError("Native component identities changed during ECO")
    for ref,item in before.items():
        dest=moves[ref]["new_xy_mm"] if ref in moves else [
            item["X"]/G.MIL_PER_MM, -item["Y"]/G.MIL_PER_MM]
        deg=float(moves[ref].get("rotation_deg",0)) if ref in moves else float(item.get("Rotation") or 0)
        actual=after[ref]
        if (abs(actual["X"]/G.MIL_PER_MM-float(dest[0]))>0.25/G.MIL_PER_MM
                or abs(-actual["Y"]/G.MIL_PER_MM-float(dest[1]))>0.25/G.MIL_PER_MM
                or abs(float(actual.get("Rotation") or 0)-deg)>.02):
            raise ValueError(f"Native reopen did not preserve intended ECO: {ref}")
    if (len(v.get("pads",[]))!=299 or len(v.get("nets",[]))!=65
            or len(v.get("lines",[]))!=98 or len(v.get("vias",[]))!=18
            or v.get("polylines")!=38):
        raise ValueError("ECO silently changed footprint/copper/net counts")
    # More than counts: serializing the same x/y/net/width ensures no old line
    # or via disappears and no unreviewed replacement is accepted.
    fields=[("lines",("net","layer","x1","y1","x2","y2","width")),
            ("vias",("net","x","y","hole","diameter"))]
    for attr,keys in fields:
        normalized=lambda d: sorted(tuple(d.get(k) for k in keys)
                                     for d in dct[attr])
        dct=original
        left=sorted(tuple(p.get(k) for k in keys) for p in original[attr])
        right=sorted(tuple(p.get(k) for k in keys) for p in v[attr])
        if left!=right:
            raise ValueError(f"Native existing {attr} altered by placement ECO")
    old_pad_nets=sorted((p.get("ref") or "",str(p["PadNumber"]),p.get("Net") or "")
                        for p in original["pads"])
    new_pad_nets=sorted((p.get("ref") or "",str(p["PadNumber"]),p.get("Net") or "")
                        for p in v["pads"])
    if old_pad_nets!=new_pad_nets:
        raise ValueError("An existing pad/net/designator changed during native move")
    candidate={"board":G.load_current()["board"],
               "tbd_zones":G.load_current()["tbd_zones"],
               "pads":v["pads"],"components":v["components"],
               "lines":v["lines"],"vias":v["vias"]}
    physical=G.report(candidate)
    if physical["lr_elp38_candidate"]["other_pad_envelope_intersections"]!=0:
        raise ValueError("Reopened physical Lr core still intersects other native pads")
    if not physical["lr_elp38_candidate"]["board_edge_reserve_passed"]:
        raise ValueError("Reopened core still below board edge planning reserve")
    return {
        "status":"REOPENED_NATIVE_CAD_CANDIDATE_REQUIRES_GUI_DRC_AND_3D_REVIEW",
        "components":77,"pads":299,"nets":65,"lines":98,"vias":18,
        "moved_refs":sorted(moves),
        "lr_other_pad_intersections":0,
        "core_board_edge_margin_mm":physical["lr_elp38_candidate"]["minimum_board_edge_margin_mm"],
        "unrouted_connections_assumed_zero":False,
        "real_assembly_3d_verified":False,
        "fab_release":False
    }


def apply()->int:
    prepared=R.check()
    if prepared["preflight_errors"]:
        raise RuntimeError("Offline relocation preflight fails; abort native CAD")
    if TARGET.exists():
        raise FileExistsError(f"Refusing to overwrite prior ECO candidate {TARGET}")
    original=json.loads(G.ACTIVE_READBACK.read_text(encoding="utf-8"))["value"]
    md5=D.md5(SOURCE)
    shutil.copy2(SOURCE,TARGET)
    session=A.open_and_ping(TARGET,PREFIX,"apply")
    if not session:
        return 1
    try:
        result=A.invoke(session,R.emit_js(prepared))
        A.dump(PREFIX,"apply",result)
        time.sleep(30)  # Editor's documented delayed save flush.
    finally:
        A.dump(PREFIX,"close",D.call(D.build_close_args(session)))
    if not result.get("ok") or (result.get("value") or {}).get("saved") is not True:
        raise RuntimeError("ECO modify/save failed; only the isolated copy may be affected")
    if D.md5(SOURCE)!=md5:
        raise RuntimeError("Golden source binary changed unexpectedly; STOP")
    session=A.open_and_ping(TARGET,PREFIX,"reopen")
    if not session:
        return 1
    try:
        fresh=A.invoke(session,A.READ_JS.read_text(encoding="utf-8"))
    finally:
        A.dump(PREFIX,"reopen_close",D.call(D.build_close_args(session)))
    READBACK.write_text(json.dumps(fresh,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    plan=json.loads(R.PLAN.read_text(encoding="utf-8"))
    report=native_verify(original,fresh,plan)
    report.update({"candidate":TARGET.relative_to(ROOT).as_posix(),
                   "candidate_sha256":hashfile(TARGET),
                   "source_md5_unchanged":True,
                   "source_readback_git_blob_sha":prepared["source_readback_git_blob_sha"],
                   "native_erc_passed":False,"native_drc_passed":False,
                   "manufacturer_qualified_magnet":False,
                   "winding_terminal_and_dot_verified":False})
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))
    # DRC always collects genuine fail counts, even when source has 206 opens.
    # We do NOT auto-mark DRC passed or change the fabrication release gate.
    command=[sys.executable,str(HERE/"run_driver_drc.py"),
             "--board",str(TARGET),"--prefix",PREFIX+"_drc"]
    drc=subprocess.run(command,check=False)
    return 0 if drc.returncode==0 else drc.returncode


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    g=parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--check",action="store_true")
    g.add_argument("--apply",action="store_true")
    args=parser.parse_args()
    if args.check:
        value=R.check()
        print(json.dumps(value,ensure_ascii=False,indent=2))
        raise SystemExit(0 if not value["preflight_errors"] else 1)
    raise SystemExit(apply())

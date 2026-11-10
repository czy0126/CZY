"""Prepare an actual G1 EasyEDA Lr+11-passive *candidate* ECO, never edit native CAD here.

Source is the latest saved/reopened 98-track/18-via EasyEDA G1 board.
The plan keeps high-frequency Lr near the original T1 region and moves 11
small unconnected passives close to same-net controller/SR-driver pins.

  python tools/g1_lr_repack_ready.py --check
  python tools/g1_lr_repack_ready.py --emit-js > /tmp/g1_lr_repack_apply.js

The returned JS may run ONLY on a new isolated copy of the .eprj2 created
from dcx_main_board_g1_kelvin.eprj2, with native GUI API enabled. The script
checks component coordinates/number before modifying and saving.
No Maxwell solve, original project revision, DRC, manufacturing or wiring
release is implied; the core and the 100A output structure remain provisional.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import g1_magnetics_envelope as geom

ROOT = geom.ROOT
PLAN = ROOT / "hardware/dcx_main/g1/lr_elp38_repack_plan.json"
CLEARANCE_PAD_MM = 0.5
CLEARANCE_ROUTE_MM = 0.3
CLEARANCE_CORE_MM = 0.25
MIL = geom.MIL_PER_MM
EXPECTED_MOVER_REFS = {
    "Lr", "C101", "C102", "C105", "C106", "C107", "C108",
    "R1", "R2", "R7", "R9", "R10",
}


def union(boxes: list[dict]) -> dict:
    if not boxes:
        raise ValueError("No footprint pads")
    return {"left": min(b["left"] for b in boxes),
            "right": max(b["right"] for b in boxes),
            "top": min(b["top"] for b in boxes),
            "bottom": max(b["bottom"] for b in boxes)}


def extended(b: dict, clearance: float) -> dict:
    return {"left": b["left"]-clearance, "right": b["right"]+clearance,
            "top": b["top"]-clearance, "bottom": b["bottom"]+clearance}


def touches(a: dict, b: dict, clearance: float = 0.0) -> bool:
    # Extra clearance belongs to the SECOND body. For two moving pads, equal
    # priority gives the same result; we do not inflate both and double count.
    dx, dy = geom.intersection(a, extended(b, clearance))
    return dx > 1e-6 and dy > 1e-6


def shifted_pad_box(p: dict, old_xy: tuple[float,float], new_xy: tuple[float,float],
                    rotate_180: bool) -> dict:
    b = geom.pad_rect(p)
    ox, oy = old_xy
    cx = (b["left"]+b["right"])/2
    cy = (b["top"]+b["bottom"])/2
    dx, dy = cx-ox, cy-oy
    if rotate_180:
        dx, dy = -dx, -dy
    x, y = new_xy
    return geom.rectangle(x+dx,y+dy,b["right"]-b["left"],
                          b["bottom"]-b["top"])


def route_bbox(r: dict) -> dict:
    x1, y1 = float(r["x1"])/MIL, -float(r["y1"])/MIL
    x2, y2 = float(r["x2"])/MIL, -float(r["y2"])/MIL
    w = float(r["width"])/MIL
    return {"left": min(x1,x2)-w/2, "right": max(x1,x2)+w/2,
            "top": min(y1,y2)-w/2, "bottom": max(y1,y2)+w/2}


def via_bbox(v: dict) -> dict:
    x, y = float(v["x"])/MIL, -float(v["y"])/MIL
    d = float(v["diameter"])/MIL
    return geom.rectangle(x,y,d,d)


def electrical_proxy_length(center: tuple[float,float], rotate_180: bool) -> float:
    """Straight-line lower bound, NOT total resonant conductor or inductance."""
    x, y = center
    pins = ((x+4.501,y),(x-4.501,y)) if rotate_180 else (
        (x-4.501,y),(x+4.501,y))
    return (math.dist(pins[0],(80.0,48.0)) +
            math.dist(pins[1],(3.0,28.0)))


def check() -> dict:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    board = geom.load_current()
    # Source is locked to a concrete saved EasyEDA copy; do not run against
    # any future layout until a human refreshes this source-locked plan.
    if plan["source_reopen_git_blob_sha"] != geom.git_blob_sha(geom.ACTIVE_READBACK):
        raise ValueError("The native G1 source changed; re-audit before moving anything")
    if plan["status"] != "CANDIDATE_ECO_NOT_APPLIED":
        raise ValueError("A candidate cannot claim to have been applied")
    actual = {k: len(board[k]) for k in ("components","pads","lines","vias")}
    actual["nets"] = len(json.loads(
        geom.ACTIVE_READBACK.read_text(encoding="utf-8"))["value"]["nets"])
    if actual != plan["source_count_guard"]:
        raise ValueError(f"Live source counts changed: {actual}")
    moves = plan["moves"]
    if set(moves) != EXPECTED_MOVER_REFS:
        raise ValueError("Unexpected ECO scope; must review the 11 passives and Lr")
    refpos = {c["ref"]: (float(c["X"])/MIL, -float(c["Y"])/MIL)
              for c in board["components"]}
    if set(moves) - set(refpos):
        raise ValueError("ECO components absent from native PCB")
    if any(abs(float(c.get("Rotation") or 0)) > 1e-4 for c in board["components"]
           if c["ref"] in moves):
        raise ValueError("Source component rotations changed; target must be requalified")

    newpos = {ref: tuple(map(float, v["new_xy_mm"])) for ref,v in moves.items()}
    if newpos["Lr"] != (26.0,49.0) or moves["Lr"]["rotation_deg"] != 180:
        raise ValueError("Unreviewed resonant core move/rotation")
    pad_by_ref: dict[str, list] = {}
    for p in board["pads"]:
        pad_by_ref.setdefault(p.get("ref"), []).append(p)

    candidates: dict[str,list[dict]] = {}
    for ref in sorted(moves):
        my_pads = pad_by_ref.get(ref,[])
        if len(my_pads) < 2:
            raise ValueError(f"Missing actual existing native footprint pads for {ref}")
        candidates[ref] = [
            shifted_pad_box(p,refpos[ref],newpos[ref],ref=="Lr")
            for p in my_pads
        ]

    # Actual body (not only the tiny native Lr footprint). T zones/CT remain
    # conceptual, so 3D and Z-dependent mounting evidence are still missing.
    mag = json.loads(geom.MAG.read_text(encoding="utf-8"))
    core, transformer, _ = geom.core_rects(
        {**board, "components": [
            {**c,"X":newpos["Lr"][0]*MIL,"Y":-newpos["Lr"][1]*MIL}
            if c["ref"]=="Lr" else c for c in board["components"]]},mag)
    if geom.rounded_box(core) != {
            "left":7.0,"right":45.0,"top":36.3,"bottom":61.7}:
        raise ValueError("Wrong actual Lr ferrite body envelope")

    fixed = {ref: [geom.pad_rect(p) for p in group]
             for ref, group in pad_by_ref.items()
             if ref not in moves and ref is not None}
    free_pads = [geom.pad_rect(p) for p in pad_by_ref.get(None,[])]
    errors = []
    for ref,bb in fixed.items():
        for b in bb:
            if touches(core,b):
                errors.append(f"Lr core XY covers fixed {ref} pad")
    if any(touches(core,p) for p in free_pads):
        errors.append("Lr core XY covers a provisional transformer/CT pad")
    for ref,body in transformer.items():
        if touches(core,body):
            errors.append(f"Lr core XY covers transformer body {ref}")

    # Do not move pads that are already attached to the old 98 source traces.
    # This plan does not contain corresponding track/via deletion+rerouting.
    old_pads = [p for ref in moves for p in pad_by_ref[ref]]
    old_attach = []
    # No clearance inflation in old endpoint test; an actual copper segment
    # intersecting the old pad would be orphaned by the movement.
    traces = [(r,route_bbox(r)) for r in board["lines"]]
    vias = [via_bbox(v) for v in board["vias"]]
    for p in old_pads:
        old_box = geom.pad_rect(p)
        for r,b in traces:
            if touches(old_box,b):
                old_attach.append(f"{p['ref']}.{p['PadNumber']} connected to {r['net']}")
    if old_attach:
        errors.extend(old_attach)

    all_moving = {ref:union(bb) for ref,bb in candidates.items()}
    for ref,b in all_moving.items():
        for other,boxes in fixed.items():
            if touches(b,union(boxes),CLEARANCE_PAD_MM):
                errors.append(f"{ref} placement collides with fixed {other} pad/body")
        for fb in free_pads:
            if touches(b,fb,CLEARANCE_PAD_MM):
                errors.append(f"{ref} placement collides with free magnetic pad")
        if ref!="Lr" and touches(b,core,CLEARANCE_CORE_MM):
            errors.append(f"{ref} placement enters Lr magnetic body")
        for r, rb in traces:
            if touches(b,rb,CLEARANCE_ROUTE_MM):
                errors.append(f"{ref} placement crosses existing {r['net']} route")
        for vb in vias:
            if touches(b,vb,CLEARANCE_ROUTE_MM):
                errors.append(f"{ref} placement overlaps a source via")
        if (b["left"]<2 or b["right"]>153
                or b["top"]<2 or b["bottom"]>129):
            errors.append(f"{ref} footprint outside G1 pad planning border")
    refs = sorted(all_moving)
    for i,a in enumerate(refs):
        for b in refs[i+1:]:
            # Lr's two native pads are intentionally inside the Lr core,
            # but its real body is already checked against every moved part.
            if touches(all_moving[a], all_moving[b],CLEARANCE_PAD_MM):
                errors.append(f"Moving footprints {a} and {b} overlap")
    for name,body in transformer.items():
        if touches(core,body,2.0):
            errors.append(f"Lr body has less than 2mm to {name} body")

    expected = plan["options"]["near_loop_candidate"]["expected_neighbour_refs_to_relocate"]
    old_inside = {p.get("ref") for p in board["pads"]
                  if p.get("ref") not in (None,"Lr") and touches(
                      core,geom.pad_rect(p))}
    if old_inside != set(expected):
        errors.append("Source magnet overlaps differ from the 11 named mover refs")
    if len(candidates)!=12:
        errors.append("Missing moved component")
    original_center = refpos["Lr"]
    d_original = electrical_proxy_length(original_center,False)
    d_local = electrical_proxy_length(newpos["Lr"],True)
    d_far = electrical_proxy_length((99,109),True)
    if not (d_local < d_original and d_far > d_local * 2):
        errors.append("Electric proxy did not substantiate near-loop preference")

    result = {
        "status": "ECO_PREVIEW_SOURCE_LOCKED_NOT_NATIVE_APPLIED",
        "source_cad": plan["source_cad"],
        "source_readback_git_blob_sha": plan["source_reopen_git_blob_sha"],
        "move_count": len(moves),
        "actual_cross_ref_overlap": len(old_inside),
        "moved_refs": sorted(moves),
        "Lr_center_mm": list(newpos["Lr"]),
        "Lr_core_xy_mm": geom.rounded_box(core),
        "Lr_nominal_turn_rotation_deg": 180,
        "resonant_endpoint_proxy_mm": {
            "original": round(d_original,2),
            "near_loop_candidate": round(d_local,2),
            "rejected_remote": round(d_far,2),
        },
        "preflight_errors": sorted(set(errors)),
        "note": "Nominal pad/track and ferrite XY screen only; neither full 3D clearance nor a ready-to-fabricate 100A layout.",
        "native_eda_modified": False,
        "native_drc_passed": False,
        "maxwell_solved": False,
        "fab_approved": False,
    }
    return result


def emit_js(report:dict) -> str:
    if report["preflight_errors"]:
        raise ValueError("Never generate writable EDA actions with known preflight errors")
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    # Standalone JS invocation; never allows an unknown subset of parts to be
    # moved, and asserts original coordinates and rotation on a *copied* board.
    commands = {k: [*v["new_xy_mm"], v.get("rotation_deg",0)]
                for k,v in plan["moves"].items()}
    old = geom.load_current()
    original = {c["ref"]: [round(c["X"],3),round(c["Y"],3),
                           round(c.get("Rotation") or 0,3)]
                for c in old["components"] if c["ref"] in commands}
    js = r"""// G1 Lr provisional ECO: RUN ONLY AFTER COPYING Kelvin .eprj2 TO A NEW FILE.
// Generated from live native 77-part source; NEVER run against the frozen parent.
// Not a vendor footprint, Maxwell solve, final 100 A route or fab approval.
return await (async () => {
  const MM_MIL=39.37007874015748;
  const MOVES=__MOVES__;
  const SOURCE=__OLD__;
  const project=await eda.dmt_Project.getCurrentProjectInfo();
  const board=project?.data?.find(x=>x?.pcb?.uuid);
  if (!board) throw new Error('Expected a real EasyEDA PCB document');
  await eda.dmt_EditorControl.openDocument(board.pcb.uuid);
  const parts=await eda.pcb_PrimitiveComponent.getAll();
  if (parts.length!==77) throw new Error('Wrong native source revision: expected 77 parts');
  const partsByRef={};
  for (const c of parts) {
    const k=c.getState_Designator();
    if (partsByRef[k]) throw new Error('Duplicate native designator '+k);
    partsByRef[k]=c;
  }
  const keys=Object.keys(MOVES);
  if (keys.length!==12) throw new Error('Expected exactly Lr plus 11 passives');
  for (const ref of keys) {
    const c=partsByRef[ref], b=SOURCE[ref];
    if (!c || !b) throw new Error('Missing expected native ref '+ref);
    if (Math.abs(c.getState_X()-b[0])>0.25 ||
        Math.abs(c.getState_Y()-b[1])>0.25 ||
        Math.abs(c.getState_Rotation()-b[2])>0.01)
      throw new Error('Ref moved since readback; refuse to apply: '+ref);
  }
  const lines=await eda.pcb_PrimitiveLine.getAll();
  const vias=await eda.pcb_PrimitiveVia.getAll();
  if (lines.length!==98 || vias.length!==18)
    throw new Error('Tracks/vias changed since preflight; do not move copper');
  const before=[];
  for (const ref of keys) {
    const c=partsByRef[ref], [x,y,rot]=MOVES[ref];
    before.push({ref,x:c.getState_X(),y:c.getState_Y(),rotation:c.getState_Rotation()});
    await eda.pcb_PrimitiveComponent.modify(c.getState_PrimitiveId(),{
      x:x*MM_MIL, y:-y*MM_MIL, rotation:rot
    });
  }
  const saved=await eda.pcb_Document.save();
  if (!saved) throw new Error('New candidate copy was not saved');
  return {saved,source:'G1_KELVIN_COPY_ONLY',moved:before.map(x=>x.ref),
          moves:MOVES,hardware_approved:false};
})();"""
    return js.replace("__MOVES__",json.dumps(commands)).replace(
        "__OLD__",json.dumps(original)) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--check",action="store_true")
    g.add_argument("--emit-js",action="store_true")
    p = parser.parse_args()
    report=check()
    if report["preflight_errors"]:
        print(json.dumps(report,ensure_ascii=False,indent=2),file=sys.stderr)
        raise SystemExit("Preflight failed; no native edit JS generated")
    if p.emit_js:
        print(emit_js(report),end="")
    else:
        print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()

"""Source-locked physical G2 pad trial on the real 149-line G1 PCB.

Unlike the original 18x4 body-position-only trial, this positions 144
top-layer solder *pad primitives* and screens them against every existing
149-line native copper/pad/via on the parent. Two capacitors are moved to a
fifth, bottom-edge row to avoid the still-needed J_OUT connector. No existing
board conductor is removed or touched.

THE PADS ARE A DESIGN-OWNED, NOT OEM-QUALIFIED land trial (2.3x2.7mm);
manufacturing land pattern, schematic parity, 100A wiring, thermal and 16mm
stack are unqualified. This script must not be cited for FAB release.

python hardware/dcx_main/g2/plan_t530_72_native.py --write
python hardware/dcx_main/g2/plan_t530_72_native.py --check
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/"tools"))
import cout_t530_72 as C
import g2_board_keepout as K

OUT=HERE/"t530_72_native_pad_plan_149_NOT_FOR_FAB.json"
BODY_W,BODY_H=7.6,4.6
PAD_W,PAD_H=2.3,2.7
PAD_X=2.5
PAD_TRIAL_CLEARANCE=0.15
BODY_TO_OLD_PAD_CLEARANCE=0.30
RELOCATIONS={"CHV63":(7.0,125.0),"CHV64":(15.3,125.0)}
MIL=1/0.0254

def sha(path:Path)->str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha_original_windows_readback(path:Path)->str:
    """Bind the saved native EasyEDA readback's original CRLF bytes.

    Git checks out this JSON as LF on CI while the original Windows readback
    receipt was captured as CRLF. Reconstruct the original bytes exactly;
    never reinterpret the native board archive or alter its identity hash.
    """
    lf=path.read_bytes().replace(b"\r\n",b"\n")
    return hashlib.sha256(lf.replace(b"\n",b"\r\n")).hexdigest()

def rect(x,y,w,h):
    return (x-w/2,y-h/2,x+w/2,y+h/2)

def make()->dict:
    original=C.report()
    native=C.active_native_g1()
    placement=[]
    all_lands=[]
    problems=[]
    for base in original["placement"]["units"]:
        ref=base["ref"]
        x,y=base["candidate_position_mm"]
        x,y=RELOCATIONS.get(ref,(round(x-1.0,4),round(y+7.0,4)))
        body=rect(x,y,BODY_W,BODY_H)
        if not (body[0]>=2.0 and body[2]<=153.0 and body[1]>=2.0 and body[3]<=129.0):
            problems.append(ref+":body outside minimum 2mm board edge")
        if any(C.touches(body,rect(*other["centre_mm"],BODY_W,BODY_H),.001) for other in placement):
            problems.append(ref+":overlap another new capacitor body")
        for old in native["pads"]:
            if C.touches(body,K.pad_bbox(old),BODY_TO_OLD_PAD_CLEARANCE):
                problems.append(ref+":body overlaps existing pad "+str(old.get("ref"))+"."+str(old.get("PadNumber")))
        lands=[]
        for side,net,suffix in ((-1,"PGND","N"),(1,"VOUT","P")):
            px=x+side*PAD_X
            land=rect(px,y,PAD_W,PAD_H)
            if not all(body[i]-1e-8<=land[i] for i in (0,1)) or land[2]>body[2]+1e-8 or land[3]>body[3]+1e-8:
                problems.append(ref+":provisional pad outside body envelope")
            for oldland in all_lands:
                if C.touches(land,rect(*oldland["centre_mm"],PAD_W,PAD_H),.152):
                    problems.append(ref+":new pads too close to "+oldland["number"])
            for old in native["pads"]:
                if C.touches(land,K.pad_bbox(old),PAD_TRIAL_CLEARANCE):
                    problems.append(ref+":new pad touches old "+str(old.get("ref"))+"."+str(old.get("PadNumber")))
            for trace in native["lines"]:
                if int(trace["layer"]) != 1 or trace["net"]==net:
                    continue
                half=float(trace["width"])*.0254/2
                fat=(land[0]-PAD_TRIAL_CLEARANCE-half,land[1]-PAD_TRIAL_CLEARANCE-half,
                     land[2]+PAD_TRIAL_CLEARANCE+half,land[3]+PAD_TRIAL_CLEARANCE+half)
                a=(float(trace["x1"])*.0254,-float(trace["y1"])*.0254)
                b=(float(trace["x2"])*.0254,-float(trace["y2"])*.0254)
                if C.segment_hits_rectangle(a,b,fat):
                    problems.append(ref+":wrong-net track "+str(trace["net"])+"/"+str(trace["id"]))
            for via in native["vias"]:
                if via["net"]==net:
                    continue
                pos=(float(via["x"])*.0254,-float(via["y"])*.0254)
                min_dist=float(via["diameter"])*.0254/2+PAD_TRIAL_CLEARANCE
                if K.distance_to_box(pos,land)<min_dist:
                    problems.append(ref+":wrong-net via "+str(via["id"]))
            pad={"number":f"{ref}_{suffix}","ref":ref,"pin":suffix,
                 "centre_mm":[round(px,4),round(y,4)],"size_mm":[PAD_W,PAD_H],
                 "layer":1,"net":net,
                 "oem_footprint_approved":False}
            lands.append(pad)
            all_lands.append(pad)
        placement.append({"ref":ref,"centre_mm":[x,y],
                          "body_envelope_mm":[BODY_W,BODY_H],
                          "provisional_pads":lands,
                          "actual_pcb_component":False,
                          "placement_approved":False})
    if len(placement)!=72 or len(all_lands)!=144:
        raise ValueError("72 components/144 trial lands required")
    if len({x["number"] for x in all_lands})!=144:
        raise ValueError("duplicate trial pad numbers")
    if original["placement"]["board_source_sha256"]!=sha(C.BASE):
        raise ValueError("G2 parent SHA not immutable")
    return {
      "schema":"G2_T530_72_NATIVE_PROVISIONAL_PAD_PLAN_V1",
      "status":"SOURCE_LOCKED_149_LINE_NATIVE_PAD_TRIAL_NOT_FOR_FAB",
      "source_board":C.BASE.relative_to(ROOT).as_posix(),
      "source_board_sha256":sha(C.BASE),
      "source_native_readback_sha256":sha_original_windows_readback(C.READBACK),
      "source_native_drc_sha256":sha(C.DRC_DELTA),
      "oem_part":"KEMET_T530X477M006ATE004",
      "lcsc_part_number":"C2158170",
      "oem_case":"7343-43_X",
      "footprint_type":"DESIGN_OWNED_RECTANGULAR_TRIAL_NOT_OEM_LAND_PATTERN",
      "body_mm":[BODY_W,BODY_H],
      "pad_size_mm":[PAD_W,PAD_H],
      "pad_centre_offset_mm":PAD_X,
      "pad_polarity":"VOUT_RIGHT_P/PGND_LEFT_N_UNCONFIRMED_ASSEMBLY_MARKING",
      "original_149_line_connection_errors":173,
      "original_149_line_netlist_errors":1,
      "original_149_line_copper_preserved":True,
      "relocations":{k:list(v) for k,v in RELOCATIONS.items()},
      "part_count":len(placement),
      "pad_count":len(all_lands),
      "problems":sorted(set(problems)),
      "placements":placement,
      "hardware_manufacturing_approved":False,
      "actual_oem_land_pattern_verified":False,
      "schematic_parity_verified":False,
      "100A_both_pole_power_copper_done":False,
      "high_current_bars_connected":False,
      "hot_esr_current_sharing_verified":False,
    }

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write",action="store_true")
    g.add_argument("--check",action="store_true")
    opt=ap.parse_args()
    d=make()
    payload=json.dumps(d,ensure_ascii=False,indent=2)+"\n"
    if d["problems"]:
        raise SystemExit("REFUSING unsafe pad ECO: "+str(d["problems"][:12]))
    if opt.write:
        OUT.write_text(payload,encoding="utf-8",newline="\n")
    elif not OUT.is_file() or json.loads(OUT.read_text(encoding="utf-8")) != d:
        raise SystemExit("G2 pad plan missing/stale")
    print(f"{len(d['placements'])} bodies / {d['pad_count']} experimental netted lands; "
          "zero visible-geometry conflicts; never OEM/FAB.")

if __name__=="__main__":
    main()

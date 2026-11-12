"""Manufacturer-derived KEMET T530 X case Density-B 16x5, 72-unit G2 ECO.

OEM source: https://content.kemet.com/datasheets/KEM_T2076_T52X-530.pdf
2026 datasheet Table 2, T520/T521/T525/T530 X/7343-43 (page 37):
  pad W (Y)=2.43mm; pad L (X)=2.37mm; inner gap S=3.87mm;
  nominal courtyard V1 (X)=9.12mm, V2 (Y)=5.10mm.
Our prior 18x4 trial has 8.3mm pitch, INVALID for Density B; on a
155mm PCB, 16 columns at 9.2mm plus 9.12mm courier footprint fits.

This is NOT a factory-sourced PCB footprint or 72 real components. It
plans pad primitives only on an immutable 149-track board, with explicit
manufacturer land dimensions/courtyards, physical collisions and false
fabrication gates.
"""
from __future__ import annotations
import argparse,hashlib,json,sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/"tools"))
import cout_t530_72 as C
import g2_board_keepout as K

SOURCE=C.BASE
OUT=HERE/"t530_72_oem_density_b_16x5_pad_plan_NOT_FOR_FAB.json"
DATASHEET="https://content.kemet.com/datasheets/KEM_T2076_T52X-530.pdf"
W,L,S,V1,V2=(2.43,2.37,3.87,9.12,5.10)
DX=(S+L)/2
PITCH_X=9.2
PITCH_Y=6.4
X0,Y0=7.5,99.0
BODY_X,BODY_Y=7.6,4.6 # maximum body dimensions (7.3±.3 x 4.3±.3)
CLEAR=0.30

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def rect(x,y,w,h):
    return x-w/2,y-h/2,x+w/2,y+h/2

def site(x,y,old):
    box=rect(x,y,V1,V2)
    body=rect(x,y,BODY_X,BODY_Y)
    errors=[]
    if box[0]<2 or box[1]<2 or box[2]>153 or box[3]>129:
        errors.append("courtyard outside 2mm board margin")
    for p in old["pads"]:
        if C.touches(body,K.pad_bbox(p),.3):
            errors.append("old PCB pad under capacitor body "+str(p.get("PadNumber")))
        if C.touches(box,K.pad_bbox(p)):
            errors.append("old PCB pad under courtyard "+str(p.get("PadNumber")))
    pads=[]
    for label,net,pol in (("N","PGND",-1),("P","VOUT",1)):
        px=x+pol*DX
        land=rect(px,y,L,W)
        for p in old["pads"]:
            if p["Net"]!=net and C.touches(land,K.pad_bbox(p),CLEAR):
                errors.append("foreign-pad "+net+"/"+str(p.get("PadNumber")))
        for t in old["lines"]:
            if t["net"]==net or int(t["layer"])!=1:continue
            fat=t["width"]*.0254/2+CLEAR
            rr=land[0]-fat,land[1]-fat,land[2]+fat,land[3]+fat
            if C.segment_hits_rectangle((t["x1"]*.0254,-t["y1"]*.0254),
                                        (t["x2"]*.0254,-t["y2"]*.0254),rr):
                errors.append("foreign-track "+net+"/"+t["net"]+"/"+str(t["id"]))
        for v in old["vias"]:
            if v["net"]==net:continue
            pos=v["x"]*.0254,-v["y"]*.0254
            if K.distance_to_box(pos,land)<v["diameter"]*.0254/2+CLEAR:
                errors.append("foreign-via "+net+"/"+str(v["id"]))
        pads.append({"pin":label,"net":net,"centre_mm":[round(px,4),round(y,4)],
                     "size_mm":[L,W],"layer":1})
    return sorted(set(errors)),pads

def make():
    old=C.active_native_g1()
    if (len(old["components"]),len(old["pads"]),len(old["lines"]),
        len(old["vias"]),len(old["nets"]))!=(77,299,149,18,65):
        raise ValueError("Not immutable 149-track real G1 board")
    allsites=[]
    for row in range(5):
        for col in range(16):
            x=round(X0+col*PITCH_X,4)
            y=round(Y0+row*PITCH_Y,4)
            problems,land=site(x,y,old)
            allsites.append({"row":row,"column":col,"centre_mm":[x,y],
                             "problems":problems,"proposed_pads":land})
    valid={(q["row"],q["column"]):q for q in allsites if not q["problems"]}
    if len(valid)<72:
        raise ValueError("Fewer than 72 real G1-clear OEM density-B sites")
    # Design choice: 3 full rows + max safe row 4 + 10 even-spaced final row.
    selected=[]
    for row in range(3):
        selected.extend(valid[row,col] for col in range(16))
    selected.extend(valid[3,col] for col in range(16) if (3,col) in valid)
    for col in (0,2,3,5,6,9,10,12,13,15):
        selected.append(valid[4,col])
    if len(selected)!=72:
        raise ValueError("Expected 72 actual positioned OEM sites")
    placement=[]
    for i,q in enumerate(selected):
        ref="CHB%02d"%(i+1)
        pads=[]
        for d in q["proposed_pads"]:
            pads.append({"number":ref+"_"+d["pin"],"ref":ref,**d})
        placement.append({"ref":ref,"row":q["row"],"column":q["column"],
                          "centre_mm":q["centre_mm"],"courtyard_mm":[V1,V2],
                          "body_max_mm":[BODY_X,BODY_Y],
                          "pads":pads,
                          "actual_schematic_component":False,
                          "manufacturer_library_footprint_instantiated":False})
    boxes=[(p["ref"],rect(*p["centre_mm"],V1,V2)) for p in placement]
    failures=[]
    for k,(name,box) in enumerate(boxes):
        for other,quad in boxes[k+1:]:
            if C.touches(box,quad,0.00001):
                failures.append(name+" courtyard overlaps "+other)
    if len({p["number"] for q in placement for p in q["pads"]})!=144:
        failures.append("duplicate pad numbers")
    return {"schema":"G2_T530X477M006ATE004_OEM_DENSITY_B_16x5_PLACEMENT_V1",
            "status":"MANUFACTURER_DERIVED_LAND_GEOMETRY_NOT_ACTUAL_COMPONENT_NOT_FOR_FAB",
            "source_149line_PCB":SOURCE.relative_to(ROOT).as_posix(),
            "source_149line_sha256":sha(SOURCE),
            "manufacturer_datasheet":DATASHEET,
            "manufacturer_datasheet_revision":"T2076_T52X-530 2026-09-09 Table 2 p37",
            "component":"KEMET T530X477M006ATE004",
            "land_case":"X1/7343-43",
            "density":"B",
            "pad_x_length_mm":L,"pad_y_width_mm":W,
            "inner_gap_mm":S,"pad_x_centre_offset_mm":DX,
            "courtyard_x_mm":V1,"courtyard_y_mm":V2,
            "max_body_x_mm":BODY_X,"max_body_y_mm":BODY_Y,
            "prior_18_column_pitch_mm":8.3,
            "prior_18_column_overlaps_density_b_courtyard_by_mm":round(V1-8.3,2),
            "new_cols":16,"new_rows":5,
            "grid_pitch_x_mm":PITCH_X,"grid_pitch_y_mm":PITCH_Y,
            "total_slots":80,"collision_free_slots":len(valid),
            "placement_count":len(placement),
            "trial_pad_count":len(placement)*2,
            "invalid_slots":[{"row":q["row"],"column":q["column"],
                              "reason":q["problems"]} for q in allsites if q["problems"]],
            "placement":placement,"preflight_problems":failures,
            "nominal_land_geometry_derived_from_manufacturer":True,
            "actual_72_components_and_schematic_symbols":False,
            "real_100A_pole_busbars":False,
            "high_temperature_esr_verified":False,
            "fabrication_approved":False}

def main():
    a=argparse.ArgumentParser();g=a.add_mutually_exclusive_group(required=True)
    g.add_argument("--write",action="store_true");g.add_argument("--check",action="store_true")
    opts=a.parse_args()
    report=make()
    if report["preflight_problems"]:
        raise ValueError(report["preflight_problems"])
    if opts.write:
        OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",
                       encoding="utf-8",newline="\n")
    else:
        if not OUT.exists() or json.loads(OUT.read_text(encoding="utf-8"))!=report:
            raise ValueError("OEM 16x5 plan is not checked-in current source-derived geometry")
    print(json.dumps({k:v for k,v in report.items() if k not in ("placement","invalid_slots")},indent=2))
    return 0
if __name__=="__main__":
    raise SystemExit(main())

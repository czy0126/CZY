"""V16 conceptual floorplan against frozen *real* V15 native pad readback.

Creates a source-locked, explicitly NOT_FOR_FAB full-device placement candidate and
a review SVG; NEVER writes EasyEDA projects or modifies original native copper.
All assembly/package and real route/stackup constraints remain gated.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
from shapely.geometry import box, Point
from shapely.affinity import scale

ROOT = Path(__file__).resolve().parents[1]
G = ROOT / "hardware" / "dcx_main" / "g2"
NATIVE = G / "dcx_main_board_g2_V15_T4_POWER_CELL_UP30MM_WIP_NOT_FOR_FAB.eprj2"
READ = G / "g2_v15_after_T4_move_native_readback_NOT_FOR_FAB.json"
SLOTS = G / "g2_v14_through_board_three_leg_slot_DFM_screen_NOT_FOR_FAB.json"
OUT = G / "g2_v16_vertical_partition_candidate_LOCKED_NOT_FOR_FAB.json"
SVG = G / "g2_v16_vertical_partition_candidate_LOCKED_NOT_FOR_FAB.svg"
EXPECTED_V15_SHA256 = "02d59c63c747678849466cc62565c1522bc50586a7dadc06b0829016ab601e75"
MM_PER_MIL = .0254
MIN_NET_CLEARANCE_MM = .19
CORRIDOR = (66., 86., 96., 126.)
CORE_X = (20., 58., 96., 134.)
CORE_Y = 40.

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def load():
    if sha(NATIVE) != EXPECTED_V15_SHA256:
        raise ValueError("Native V15 source changed; do not build a stale placement.")
    d = json.loads(READ.read_text("utf8"))
    n = d["native"]
    if (len(n["components"]), len(n["pads"]), len(n["lines"]), len(n["vias"])) != (149,423,484,104):
        raise ValueError("Unexpected native inventory; review the revision.")
    return n, json.loads(SLOTS.read_text("utf8"))

def initial_xy(c):
    return (c["X"]*MM_PER_MIL, -c["Y"]*MM_PER_MIL)

def layout(n):
    comp = {c["ref"]: c for c in n["components"]}
    target = {}
    for i in range(4):
        k = i+1
        dx = 38*i
        for r in (f"SR{k}A", f"SR{k}B"):
            target[r] = (initial_xy(comp[r])[0], 68.)
        target[f"U{k+2}"] = (19.+dx, 57.)
        target[f"C{k+6}"] = (18.933+dx, 60.)  # 4 reverse-side REG bypasses
        target[f"C{k+104}"] = ((18.,54.,94.,132.)[i],63.)
        target[f"C{k+108}"] = (25.+dx,55.)
        for r in (f"R{20+2*i}", f"R{21+2*i}"):
            target[r] = (initial_xy(comp[r])[0],77.)
        for r in (f"R{28+2*i}", f"R{29+2*i}"):
            target[r] = (initial_xy(comp[r])[0],81.)
    target.update({
        "QH":(48.,14.),"QL":(57.,14.),"Lr":(25.,14.),"Cr":(40.,14.),
        "Cin":(52.5,20.),"U2":(54.,23.5),"C5":(45.,25.),"D_BT":(46.,27.),
        "C101":(63.,23.),"R4":(49.,20.),"R5":(59.,20.),
        "R18":(45.,20.),"R19":(63.,20.),"C103":(75.,26.),"C104":(80.,26.),
        "R7":(63.,27.),"R9":(69.,23.),"R10":(69.,26.),
        "U1":(76.,18.),"C6":(83.,16.),"C13":(85.,19.),
        "R1":(84.,22.),"R2":(84.,25.),"R3":(92.,22.),
        "C102":(105.,13.),"J_IN":(112.,12.),
        "D_CT1":(95.,25.),"D_CT2":(102.,25.),
        "D_CT3":(109.,25.),"D_CT4":(116.,25.),
        "R15":(123.,24.),"R16":(129.,24.),"R17":(135.,24.),
        "C11":(141.,24.),"C12":(147.,24.),"Cout":(76.,93.),
    })
    # High-cost full 72-cap repack: six rows of 12, mirrored about x=77.5.
    # Each side has 7 potential sites at 8.5mm pitch but occupies only six;
    # unfilled sites are staggered for escape/assembly. Preserve 20mm x66..86
    # centre corridor through to the physical output terminal.
    # Actual 93.3mil-wide opposing native pads require >8.80mm pitch
    # for 0.19mm copper net clearance. Preserve original 9.2mm pitch.
    left=[6.+9.2*j for j in range(7)]
    for row,y in enumerate((92.6,99.,105.4,111.8,118.2,124.6)):
        chosen=[x for j,x in enumerate(left) if j!=(0,2,4,1,3,5)[row]]
        row_x=chosen+sorted(152.-x for x in chosen)  # mirror at x=76 (J_OUT)
        for col,x in enumerate(row_x):
            target[f"CHB{12*row+col+1:02d}"]=(x,y)
    unused = set(comp) - set(target) - {"J_OUT"} - {f"CHB{k:02d}" for k in range(1,73)}
    if unused: raise ValueError("Unplaced non-bank components: "+str(sorted(unused)))
    return {r:target.get(r,initial_xy(c)) for r,c in comp.items()},target

def physical_pad(p, old, new):
    dx,dy=new[0]-old[0],new[1]-old[1]
    sh=p["Pad"]
    if sh[0]=="POLYGON":
        # This source represents U2 thermal copper in absolute mil coords.
        nums=[v for v in sh[1] if isinstance(v,(int,float))]
        xs=[nums[i]*MM_PER_MIL+dx for i in range(0,len(nums)-1,2)]
        ys=[-nums[i]*MM_PER_MIL+dy for i in range(1,len(nums),2)]
        return box(min(xs),min(ys),max(xs),max(ys))
    # Mirrored right Cout bank is rotated 180 degrees: terminal/polarity
    # identity must follow pad numbers (not simply shift displayed labels).
    flip = (p["ref"].startswith("CHB") and new[0]>86.)
    if flip:
        x=new[0]-(p["X"]*MM_PER_MIL-old[0])
        y=new[1]-(-p["Y"]*MM_PER_MIL-old[1])
    else:
        x=p["X"]*MM_PER_MIL+dx
        y=-p["Y"]*MM_PER_MIL+dy
    w=sh[1]*MM_PER_MIL
    h=(sh[2]*MM_PER_MIL if len(sh)>2 else w)
    # Native EasyEDA pad orientations are relative to actual copper axes,
    # not the component centre. SR power source / gate pads rotate +/-90.
    # Missing this creates 16 artificial intra-SR shorts in native KiCad.
    padrot=p.get("Rotation",0.)
    if abs((padrot % 180)-90)<1e-5:w,h=h,w
    if sh[0]=="OVAL":
        return scale(Point(x,y).buffer(.5, quad_segs=16), xfact=w, yfact=h)
    if sh[0]=="ELLIPSE":
        return scale(Point(x,y).buffer(.5, quad_segs=16), xfact=w, yfact=h)
    if sh[0]=="RECT":
        return box(x-w/2,y-h/2,x+w/2,y+h/2)
    raise ValueError("Unknown native pad type: "+repr(sh[0]))

def transferred_pad_records(n, targets):
    comp={c["ref"]:c for c in n["components"]}
    records=[]
    for p in n["pads"]:
        ref=p["ref"]
        # Four anonymous source CT pads must be replaced by the actual
        # winding/CT design; they cannot be translated as physical devices.
        if not ref or ref not in comp:
            continue
        original=initial_xy(comp[ref])
        polygon=physical_pad(p,original,targets[ref])
        records.append({"ref":ref,"net":p["Net"],"layer":p["Layer"],"number":p["PadNumber"],"geom":polygon})
    return records

def copper_screen(records, max_examples=30):
    # All pad geometries are read from true V15, translated without deforming pads.
    # Track arcs, real pours, height and multi-layer net continuity are NOT screened.
    failures=[]
    for i,a in enumerate(records):
        for b in records[i+1:]:
            if a["ref"]==b["ref"] or a["net"]==b["net"]:
                continue
            if a["layer"]!=b["layer"] and 12 not in (a["layer"],b["layer"]):
                continue
            d=a["geom"].distance(b["geom"])
            if d<MIN_NET_CLEARANCE_MM:
                failures.append((round(d,4),a["ref"],a["net"],b["ref"],b["net"]))
    return sorted(failures)[:max_examples],len(failures)

def core_screen(records, slots):
    bad=set()
    outlines=[]
    for row in slots["slots"]:
        shifted=box(row["x_min_mm"],row["y_min_mm"]+20,
                    row["x_max_mm"],row["y_max_mm"]+20).buffer(.5)
        outlines.append({"slot":row["id"],"bbox":[round(v,3) for v in shifted.bounds]})
        for p in records:
            if p["layer"] in (1,12) and p["geom"].intersects(shifted):
                bad.add((row["id"],p["ref"],p["net"]))
    return outlines,sorted(bad)

def net_min_distance(records,a,net_a,b,net_b):
    aa=[p for p in records if p["ref"]==a and p["net"]==net_a]
    bb=[p for p in records if p["ref"]==b and p["net"]==net_b]
    if not aa or not bb:raise ValueError("Missing actual power pads: "+str((a,net_a,b,net_b)))
    return round(min(x["geom"].centroid.distance(y["geom"].centroid) for x in aa for y in bb),3)

def resistance_screen(core_x):
    # Screening only: 4 x 25 A DC distributed injections, two equal rails.
    rho=1.724e-8*(1+.00393*(100.-20.))
    width,thickness=20e-3,1e-3
    ohm_per_mm=rho*.001/(width*thickness)
    x0,x1,x2,x3=core_x
    xout=76.
    segments=[(x1-x0,25),(xout-x1,50),(x2-xout,50),(x3-x2,25)]
    horizontal_bipolar_watts=2*sum(i*i*length*ohm_per_mm for length,i in segments)
    common_trunk_bipolar_watts=2*100**2*(116.-85.)*ohm_per_mm
    return {
        "geometry_assumption":"two physically separate 1mm x 20mm Cu inserts, each pole; 100C; ideal joints",
        "rho_100C_ohm_m":round(rho,11),
        "segment_current_A":[x[1] for x in segments],
        "segment_length_mm":[round(x[0],2) for x in segments],
        "two_pole_horizontal_loss_W":round(horizontal_bipolar_watts,3),
        "two_pole_central_trunk_31mm_loss_W":round(common_trunk_bipolar_watts,3),
        "two_pole_ideal_total_W":round(horizontal_bipolar_watts+common_trunk_bipolar_watts,3),
        "two_pole_equiv_R_mohm":round((horizontal_bipolar_watts+common_trunk_bipolar_watts)/100**2*1000,4),
        "has_3D_current_spreading_contacts_vias_inductance":False,
        "thermal_EMI_and_MFG_verified":False
    }

def generate():
    n,slots=load()
    targets,moved=layout(n)
    records=transferred_pad_records(n,targets)
    errors,nerrors=copper_screen(records)
    slot_rects,slot_errors=core_screen(records,slots)
    ncap=len([r for r in targets if r.startswith("CHB")])
    if ncap!=72:raise ValueError("Cout bank count drift")
    # A corridor is reserved for terminal, busbars and parallel through-board
    # via arrays; no capacitor may occupy it. The trunk is NOT designed yet.
    xc1,xc2,yc1,yc2=CORRIDOR
    throat=box(xc1,yc1,xc2,yc2)
    cap_viol=sorted({p["ref"] for p in records if p["ref"].startswith("CHB")
                     and p["geom"].intersects(throat)})
    old_targets={c["ref"]:initial_xy(c) for c in n["components"]}
    base=transferred_pad_records(n,old_targets)
    o_vin=net_min_distance(base,"Cin","VIN_P","QH","VIN_P")
    o_gnd=net_min_distance(base,"Cin","PGND","QL","PGND")
    n_vin=net_min_distance(records,"Cin","VIN_P","QH","VIN_P")
    n_gnd=net_min_distance(records,"Cin","PGND","QL","PGND")
    result={
      "schema":"D1_V16_4X1_VERTICAL_PARTITION_CONCEPT_V1",
      "status":"GEOMETRIC_CONCEPT_ONLY_NOT_FOR_FAB",
      "source_V15_native_sha256":sha(NATIVE),
      "source_V15_readback_sha256":sha(READ),
      "source_V14_slot_DFM_sha256":sha(SLOTS),
      "board_mm":[155,131],"source_native_components":149,
      "source_native_pads":423,"source_native_tracks":484,
      "source_native_vias":104,"capacitor_bank_preserved":ncap,
      "new_magnet_core_centres_mm":[[x,CORE_Y] for x in CORE_X],
      "magnet_slot_shift_y_mm":20,
      "core_slot_keepouts_mm":slot_rects,
      "placement_all_components_mm":{r:[round(x,3),round(y,3)] for r,(x,y) in sorted(targets.items())},
      "relocated_component_count":len(moved),
      "72_output_cap_repack":"6x12 on two sides of 20mm trunk, 9.2mm actual pad pitch, symmetric alternate vacancies",
      "right_bank_180deg_rotated_components":[f"CHB{k:02d}" for k in range(1,73) if targets[f"CHB{k:02d}"][0]>86.],
      "output_terminal_xy_mm":[76,116],
      "reserved_output_throat_xyxy_mm":list(CORRIDOR),
      "input_cin_to_QH_VIN_center_distance_before_mm":o_vin,
      "input_cin_to_QL_PGND_center_distance_before_mm":o_gnd,
      "input_cin_to_QH_VIN_center_distance_candidate_mm":n_vin,
      "input_cin_to_QL_PGND_center_distance_candidate_mm":n_gnd,
      "input_loop_pad_centres_sum_before_mm":round(o_vin+o_gnd,3),
      "input_loop_pad_centres_sum_candidate_mm":round(n_vin+n_gnd,3),
      "Lr_Cr_center_before_mm":round(math.dist(old_targets["Lr"],old_targets["Cr"]),3),
      "Lr_Cr_center_candidate_mm":round(math.dist(targets["Lr"],targets["Cr"]),3),
      "T1_T4_slot_lower_y_candidate_mm":51,
      "T1_T4_SR_SEC_pad_nominal_y_candidate_mm":65.18,
      "T1_T4_slot_to_SR_SEC_y_candidate_mm":14.18,
      "native_pad_only_unlike_net_clearance_limit_mm":MIN_NET_CLEARANCE_MM,
      "unassociated_native_pads_excluded_from_copied_placement_screen":len(n["pads"])-len(records),
      "native_pad_only_unlike_net_clearance_fail_count":nerrors,
      "native_pad_only_unlike_net_fail_examples":errors,
      "new_slot_pad_keepout_conflict_count":len(slot_errors),
      "new_slot_pad_keepout_conflicts":slot_errors,
      "output_capacitor_throat_conflict_refs":cap_viol,
      "copper_insert_distributed_loss_screen":resistance_screen(CORE_X),
      "IMPORTANT": [
        "This is a fresh rebuild geometry, NOT an EasyEDA PCB revision; previous traces/vias cannot be reused.",
        "The old single Cin pad footprint is not validated for 48V bias, HF RMS or bulk capacity: new actual 63V/100V local array with derating is required.",
        "The 72-Cout 6-row 9.2mm pitch is an OEM courtyard/assembly trial; 36 mirrored right parts require true 180-degree pad/polarity rotation.",
        "Old Cr pad footprint is not validated for resonant AC RMS current; select actual part and re-place.",
        "These checks are pad-only, not real component courtyard/3D, and do not certify signal net length or EMC.",
        "Vendor 12-layer 3oz laminate, 3:1:1 DOT, paired busbar joints, 16mm cold plate NOT signed.",
        "Four primary windings are a series chain, not four independent power primaries.",
        "Input PGND and SR/output PGND currently share a net; galvanic-isolation claim is not permitted.",
        "All 112 V15 native DRC connection errors remain open until new native V16 independent DRC."
      ],
      "full_native_SCH_PCB_rebuilt":False,"all_native_electrical_routes_connected":False,
      "native_12layer_stack_vendor_approved":False,"fab_release":False
    }
    return result

def svg(data):
    W,H=775,655
    out=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 155 131">',
      '<rect x="0" y="0" width="155" height="131" fill="#f5f7fa" stroke="#263950" stroke-width=".55"/>']
    zones=[(0,28,"#e9f0fc"),(28,52,"#f4e9fa"),(52,76,"#e5f4fa"),(76,96,"#f6f2e9"),(96,131,"#e8f5ea")]
    for y1,y2,c in zones:
        out.append(f'<rect x="0" y="{y1}" width="155" height="{y2-y1}" fill="{c}"/>')
    for x in CORE_X:
        out.append(f'<rect x="{x-16}" y="29" width="32" height="22" fill="#dad5e7" stroke="#70518b" stroke-width=".35" rx="1"/>')
        for dx,w in [(-14.2875,5.5),(0,7.8),(14.2875,5.5)]:
            out.append(f'<rect x="{x+dx-w/2:.3f}" y="29" width="{w}" height="22" fill="#fff" stroke="#837098" stroke-width=".25"/>')
    xy=data["placement_all_components_mm"]
    def rect(ref,w,h,color,txt=None):
        x,y=xy[ref]
        out.append(f'<rect x="{x-w/2:.2f}" y="{y-h/2:.2f}" width="{w}" height="{h}" rx=".5" fill="{color}" stroke="#293d59" stroke-width=".22"/>')
        out.append(f'<text x="{x}" y="{y+.7}" text-anchor="middle" font-family="Arial" font-size="1.85" fill="#172739">{txt or ref}</text>')
    for ref,w,h in [("Lr",11,8),("Cr",4,4),("QH",6,6),("QL",6,6),("Cin",4,3),
        ("U1",5.5,6),("U2",5.5,6),("J_IN",9,4)]:
        rect(ref,w,h,"#bcd0f2")
    for i in range(4):
        rect(f"U{i+3}",5,6,"#afdcd8")
        rect(f"SR{i+1}A",7.4,6.3,"#6dbdc7")
        rect(f"SR{i+1}B",7.4,6.3,"#6dbdc7")
    for k in range(1,73):
        x,y=xy[f"CHB{k:02d}"]
        out.append(f'<rect x="{x-3.7:.2f}" y="{y-2.25:.2f}" width="7.4" height="4.5" rx=".5" fill="#a8c6a7" stroke="#4d8b55" stroke-width=".16"/>')
    out.append('<rect x="66" y="96" width="20" height="30" fill="#fff" opacity=".75" stroke="#9a651b" stroke-width=".55" stroke-dasharray="1.2,.65"/>')
    out.append('<text x="76" y="104" text-anchor="middle" font-family="Arial" font-size="2.5" fill="#875c18">BUS</text>')
    out.append('<text x="76" y="107" text-anchor="middle" font-family="Arial" font-size="2.5" fill="#875c18">THROAT</text>')
    rect("J_OUT",7,5,"#f8d6a3","OUT")
    for x,label in [(20,"T1"),(58,"T2"),(96,"T3"),(134,"T4")]:
        out.append(f'<text x="{x}" y="39" font-family="Arial" font-size="3" text-anchor="middle" fill="#684486">{label}</text>')
    out.append('<text x="2" y="5" font-family="Arial" font-size="3" fill="#33485f">V16 PROPOSAL - NO NATIVE ROUTES / NOT FOR FAB</text>')
    out.append('<text x="2" y="129" font-family="Arial" font-size="2.5" fill="#8a2424">Illustrative floorplan; not an approved footprint, stackup, or DRC</text>')
    out.append('</svg>')
    return "\n".join(out)+"\n"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--write",action="store_true")
    ap.add_argument("--check",action="store_true")
    ns=ap.parse_args()
    d=generate()
    js=json.dumps(d,ensure_ascii=False,indent=2)+"\n"
    picture=svg(d)
    if ns.write:
        OUT.write_text(js,encoding="utf8",newline="\n")
        SVG.write_text(picture,encoding="utf8",newline="\n")
    if ns.check:
        if OUT.read_text("utf8")!=js or SVG.read_text("utf8")!=picture:
            raise ValueError("V16 generated candidate drift")
    print(json.dumps({
        "geometry":"CONCEPT_NOT_NATIVE",
        "pad_conflicts":d["native_pad_only_unlike_net_clearance_fail_count"],
        "slot_conflicts":d["new_slot_pad_keepout_conflict_count"],
        "corridor_caps":d["output_capacitor_throat_conflict_refs"],
        "input_loop_pad_sum_before_mm":d["input_loop_pad_centres_sum_before_mm"],
        "input_loop_pad_sum_candidate_mm":d["input_loop_pad_centres_sum_candidate_mm"],
        "Lr_Cr_before_mm":d["Lr_Cr_center_before_mm"],
        "Lr_Cr_candidate_mm":d["Lr_Cr_center_candidate_mm"],
        "copper_ideal_R_mohm":d["copper_insert_distributed_loss_screen"]["two_pole_equiv_R_mohm"],
        "fail_examples":d["native_pad_only_unlike_net_fail_examples"][:8]
    },ensure_ascii=True))
if __name__=="__main__":
    main()

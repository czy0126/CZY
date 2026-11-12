"""Generate a REAL editable KiCad 10 six-layer ELP38 PCB-embedded Lr trial.

Three series turns; two mirrored copper layers per turn, *not* six
simultaneous series turns. Two through transition vias link turns 1->2->3,
but those two vias have NOT been ampacity-rated and all six layers must be
isolated there except the adjacent turns. Central and side E-core apertures
are actual Edge.Cuts routed slots. The geometry is DESIGN-OWNED, NOT an
OEM mechanical drawing or a complete circuit layout.

Inputs: original ELP38 concept contract, Lr current basis, and one trial
configuration JSON. No change to existing motherboard/electronics files.

    python tools/pcb_embedded_lr.py --write
    python tools/pcb_embedded_lr.py --check
    python tools/pcb_embedded_lr.py --drc  # needs local kicad-cli 10
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import subprocess
import uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CONFIG=ROOT/"design/v3/maxwell/pcb_embedded_lr_3turn_candidate.json"
OUT=ROOT/"hardware/dcx_main/pcb_winding"
PCB=OUT/"ELP38_Lr_3turn_PCB_EMBEDDED_CONCEPT_NOT_FOR_FAB.kicad_pcb"
REPORT=OUT/"ELP38_Lr_3turn_PCB_EMBEDDED_CONCEPT_NOT_FOR_FAB.json"
DRC=OUT/"ELP38_Lr_3turn_PCB_EMBEDDED_CONCEPT_NOT_FOR_FAB.drc.txt"
FPLIB=OUT/"Lr_Terminal.pretty/Embedded_Lr_External_Terminal.kicad_mod"
FPTABLE=OUT/"fp-lib-table"
ID=uuid.UUID("894bf2c7-a342-436a-bb3b-4a9b821742e3")
MU0=4*math.pi*1e-7
LAYER_NUM={"F.Cu":0,"In1.Cu":1,"In2.Cu":2,"In3.Cu":3,"In4.Cu":4,"B.Cu":31}
GROUPS=(("F.Cu","In1.Cu"),("In2.Cu","In3.Cu"),("In4.Cu","B.Cu"))

def _sha(p:Path)->str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

def _source_lf_sha(path:Path)->str:
    """Normalize text newline only: Windows CRLF vs Linux LF is not a design change."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n",b"\n")).hexdigest()

def _id(label:str)->str:
    return str(uuid.uuid5(ID,label))

def fmt(v:float)->str:
    return f"{float(v):.5f}".rstrip("0").rstrip(".") or "0"

def point_distance_to_segment(q,a,b):
    dx=b[0]-a[0];dy=b[1]-a[1]
    t=max(0.,min(1.,((q[0]-a[0])*dx+(q[1]-a[1])*dy)/(dx*dx+dy*dy)))
    return math.hypot(q[0]-(a[0]+t*dx),q[1]-(a[1]+t*dy))

def _bbox_margin(rect,a,b,half):
    """Minimum Euclidean edge gap from axis-aligned track rectangle to slot."""
    lo_x=min(a[0],b[0])-half
    hi_x=max(a[0],b[0])+half
    lo_y=min(a[1],b[1])-half
    hi_y=max(a[1],b[1])+half
    dx=max(rect[0]-hi_x,lo_x-rect[2],0.)
    dy=max(rect[1]-hi_y,lo_y-rect[3],0.)
    return math.hypot(dx,dy)

def _same_layer_segment_gap(a,b,c,d):
    """Axis-aligned centerline segment distance, 0 at a crossing.

    KiCad's ordinary DRC will NOT detect a winding short to itself because
    all copper is assigned the same schematic net. Therefore this independent
    test must reject 2.5-mm conductor overlaps between *nonconsecutive*
    segments of the same series turn.
    """
    assert (a[0]==b[0] or a[1]==b[1]) and (c[0]==d[0] or c[1]==d[1])
    xlo1,xhi1=sorted((a[0],b[0]))
    ylo1,yhi1=sorted((a[1],b[1]))
    xlo2,xhi2=sorted((c[0],d[0]))
    ylo2,yhi2=sorted((c[1],d[1]))
    dx=max(xlo1-xhi2,xlo2-xhi1,0.)
    dy=max(ylo1-yhi2,ylo2-yhi1,0.)
    return math.hypot(dx,dy)

def _rect_edges(r):
    x0,y0,x1,y1=r
    return [((x0,y0),(x1,y0)),((x1,y0),(x1,y1)),
            ((x1,y1),(x0,y1)),((x0,y1),(x0,y0))]

def design():
    trial=json.loads(CONFIG.read_text(encoding="utf-8"))
    src=ROOT/trial["design_source"];current=ROOT/trial["load_source"]
    cases=json.loads(src.read_text(encoding="utf-8"))["cases"]
    case=next(c for c in cases if c["id"]==trial["case_id"])
    load=json.loads(current.read_text(encoding="utf-8"))
    q=trial["board"];b=trial["routing"];phy=trial["physics"]
    assert trial["schema"]=="D1_ELP38_THREE_TURN_PCB_COIL_CONCEPT_V1"
    assert case["type"]=="LR_ELP38" and case["turns"]==3
    assert case["target_inductance_uH"]==.92
    assert len(q["layers"])==6 and tuple(q["layers"])==tuple(LAYER_NUM)
    assert abs(load["tank"]["external_target_h"]*1e6-.92)<1e-9
    assert load["physical_peaks"]["min_turns_all"]>=3
    width=q["trace_width_mm"]
    assert width>0 and q["copper_to_slot_edge_mm"]>=q["copper_to_copper_clearance_mm"]
    gc=case["geometry"]
    x_leg=gc["center_leg_x_mm"];depth=gc["core_depth_y_mm"]
    side=(gc["core_outer_x_mm"]-x_leg-2*gc["window_width_each_mm"])/2
    clear=q["core_slot_extra_each_side_mm"]
    gap=q["copper_to_slot_edge_mm"]
    hx=x_leg/2+clear+gap+width/2
    hy=depth/2+clear+gap+width/2
    scx=x_leg/2+clear
    scy=depth/2+clear
    side_start=x_leg/2+gc["window_width_each_mm"]
    side_end=gc["core_outer_x_mm"]/2
    slots=[
        (-scx,-scy,scx,scy),
        (-side_end-clear,-scy,-side_start+clear,scy),
        (side_start-clear,-scy,side_end+clear,scy)
    ]
    boardrect=(q["x_min_mm"],q["y_min_mm"],q["x_max_mm"],q["y_max_mm"])
    inputp=tuple(b["input_terminal_xy_mm"]);middle1=tuple(b["turn1_end_turn2_start_via_xy_mm"])
    middle2=tuple(b["turn2_end_turn3_start_via_xy_mm"]);outputp=tuple(b["output_terminal_xy_mm"])
    assert all(len(r)==2 for r in (inputp,middle1,middle2,outputp))
    # 3 x 1-turn open loops: every winding travels left-up-right-down
    # on its own two parallel layers. Only bottom external lead lengths differ.
    left=(-hx,-hy);right=(hx,-hy)
    common=[left,(-hx,hy),(hx,hy),right]
    routes=[
        [inputp,(inputp[0],-hy),left,*common[1:],(middle1[0],-hy),middle1],
        [middle1,(-hx,middle1[1]),left,*common[1:],(middle2[0],-hy),middle2],
        [middle2,(-hx,middle2[1]),left,*common[1:],(outputp[0],-hy),outputp]
    ]
    endpoints=(inputp,middle1,middle2,outputp)
    # Each through hole is visible to EVERY copper layer. The entire route
    # on every *other* turn must be beyond its pad radius + design clearance.
    for i,route in enumerate(routes):
        assert route[0]==endpoints[i] and route[-1]==endpoints[i+1]
        for n in range(len(route)-1):
            a,bb=route[n:n+2]
            assert a!=bb,("zero-length copper",i,n)
            for other in range(n+2,len(route)-1):
                cc,dd=route[other:other+2]
                if _same_layer_segment_gap(a,bb,cc,dd)+1e-8 < (width+q["copper_to_copper_clearance_mm"]):
                    raise ValueError(f"UNINTENTIONAL SAME-LAYER SHORT: turn {i+1}, segments {n} and {other}")
            for cutout in slots:
                if _bbox_margin(cutout,a,bb,width/2)+1e-8<gap:
                    raise ValueError("PCB track violates ELP ferrite slot clearance")
            for edge_idx,axis in enumerate((0,1)):
                lower=boardrect[axis];upper=boardrect[axis+2]
                if min(a[axis],bb[axis])-width/2<lower+1:
                    raise ValueError("Winding copper too close to board edge")
                if max(a[axis],bb[axis])+width/2>upper-1:
                    raise ValueError("Winding copper too close to board edge")
    for i,via in enumerate(endpoints):
        radius=(q["terminal_pth_diameter_mm"] if i in (0,3)
                else q["transition_via_diameter_mm"])/2
        for j,route in enumerate(routes):
            candidates=[point_distance_to_segment(via,a,bb)
                        for k,(a,bb) in enumerate(zip(route,route[1:]))
                        if not (j==i and k==0) and not (j==i-1 and k==len(route)-2)]
            nearest=min(candidates)
            if nearest+1e-8 < radius+width/2+q["copper_to_copper_clearance_mm"]:
                raise ValueError(f"Through via/terminal shorts turn {j+1} at port {i} ({nearest:.3f}mm)")
    for i,a in enumerate(endpoints):
        for j,bb in enumerate(endpoints):
            if j<=i:continue
            ra=(q["terminal_pth_diameter_mm"] if i in (0,3)
                else q["transition_via_diameter_mm"])/2
            rb=(q["terminal_pth_diameter_mm"] if j in (0,3)
                else q["transition_via_diameter_mm"])/2
            if math.dist(a,bb)<ra+rb+q["copper_to_copper_clearance_mm"]:
                raise ValueError("Port/via overlap")
    lengths=[sum(math.dist(a,bb) for a,bb in zip(route,route[1:])) for route in routes]
    thickness=q["copper_thickness_per_layer_mm"]
    a_effective_mm2=width*thickness*2
    rho20=phy["copper_rho20_ohm_m"]
    hot=phy["reference_hot_temp_c"]
    rhohot=rho20*(1+phy["copper_alpha_per_k"]*(hot-phy["nominal_reference_temp_c"]))
    winding_r20=[rho20*l*1e-3/(a_effective_mm2*1e-6) for l in lengths]
    winding_hot=[rhohot*l*1e-3/(a_effective_mm2*1e-6) for l in lengths]
    i100=float(load["copper_loss_basis"]["rated_100a_a"])
    i120=float(load["copper_loss_basis"]["current_a"])
    skin_delta=math.sqrt(rhohot/(math.pi*load["tank"]["clock_khz"]*1e3*MU0))
    freq=load["tank"]["clock_khz"]*1e3
    maglimit=next(
        x for x in __import__("maxwell_magnetics_prescreen").report()["cases"]
        if x["turns"]==3 and x["target_l_uh"]==.92)
    report={
        "schema":"D1_REAL_NATIVE_SIX_LAYER_PCB_WINDING_CONCEPT_V1",
        "status":"PCB_LR_THREE_SERIES_TURNS_TWO_PARALLEL_LAYERS_PER_TURN_PRELIMINARY_NOT_FOR_FAB",
        "main_power_board_modified":False,
        "source_hashes_canonical_lf":{str(z.relative_to(ROOT)).replace("\\","/"):_source_lf_sha(z)
                         for z in (CONFIG,src,current)},
        "source_hash_method":"SHA256(UTF-8 text with CRLF normalized to LF)",
        "case_id":case["id"],
        "geometry":{
            "central_leg_slot_mm":list(slots[0]),
            "outer_leg_slots_mm":[list(x) for x in slots[1:]],
            "board_edge_mm":list(boardrect),
            "coil_centreline_x_mm":hx,"coil_centreline_y_mm":hy,
            "winding_copper_width_mm":width,
            "core_window_each_side_mm":gc["window_width_each_mm"],
            "copper_core_cutout_clearance_mm":gap,
            "copper_pair_layers":[list(x) for x in GROUPS],
            "serial_turn_endpoint_nodes_mm":[list(v) for v in endpoints],
            "track_lengths_mm":[round(x,4) for x in lengths],
            "through_current_nodes":4,
            "transition_via_count":2,
            "through_via_barrel_peak_and_rms_current_qualified":False,
            "topological_no_accidental_cross_layer_short_screen_passed":True
        },
        "dc_copper_only_estimate":{
            "rated_output_current_a":100,
            "Lr_coil_rms_a_at_rated_output":i100,
            "Lr_coil_rms_a_at_120a_output":i120,
            "not_coil_rms_100a":True,
            "pcb_copper_oz_assumed":round(thickness/0.035,2),
            "copper_t_per_layer_mm":thickness,
            "effective_copper_section_per_turn_mm2":a_effective_mm2,
            "total_three_turns_cu_path_mm":round(sum(lengths),4),
            "r_20c_ohm":round(sum(winding_r20),9),
            "r_100c_ohm":round(sum(winding_hot),9),
            "Pdc_100c_100a_output_w":round(i100*i100*sum(winding_hot),6),
            "Pdc_100c_120a_output_w":round(i120*i120*sum(winding_hot),6),
            "skin_depth_at_100c_and_clock_mm":round(skin_delta*1000,5),
            "fundamental_freq_hz":freq,
            "skin_only_not_full_proximity_loss":True,
            "via_and_end_connection_resistance_omitted":True,
            "fringing_and_AC_Rac_Rdc_omitted":True,
            "relative_copper_thermal_limit_not_proven":True
        },
        "magnetic_and_z_screen":{
            "nominal_target_inductance_uH":case["target_inductance_uH"],
            "analytical_gap_mm":case["gap_mm"],
            "linear_flux_at_121p515A_T":maglimit["b_at_rfq_current_t"],
            "flux_screen_limit_T":maglimit["screen_b_t"],
            "magnetic_screen_only_not_actual_L_I":True,
            "ELP38_slot_window_height_min_mm_from_catalogue":trial["assembly"]["manufacturer_core_window_min_height_mm"],
            "pcb_thickness_nominal_mm":trial["assembly"]["board_nominal_height_mm"],
            "pcb_plus_two_face_insulation_trial_mm":round(
                trial["assembly"]["board_nominal_height_mm"]+
                2*trial["assembly"]["min_insulation_each_face_mm_trial"],3),
            "core_plus_PCB_coldplate_height_verified":False
        },
        "qualification":trial["qualification"],
        "limitations":[
            "Standalone KiCad PCB test artifact; NOT an EasyEDA production motherboard ECO.",
            "No OEM approved slots, copper layer manufacturing stack-up or ferrite seating.",
            "Three real series turns require two transition through vias; physical plating and current crowding NOT rated.",
            "DC copper resistance is a geometry model, AC proximity/fringe and interlayer loss NOT simulated.",
            "Additional coldplate/PCB mounting, isolation, N97 100C nonlinear L(I), 200kHz losses and fault SOA required.",
            "Four 3:1:1 transformers and CT require a separate turn/DOT/layer/isolation design."
        ]
    }
    return trial,case,routes,slots,endpoints,report

def _kicad(trial,routes,slots,endpoints):
    q=trial["board"];t=[]
    t+=['(kicad_pcb','  (version 20260206)',
         '  (generator "CZY_ELP38_PCB_LR_CONCEPT")','  (generator_version "10.0")',
         f'  (general (thickness {fmt(q["nominal_thickness_mm"])}))',
         '  (paper "A4")',
         '  (title_block (title "ELP38 Lr 3 turn x 2 layer PCB winding STUDY")',
         '      (comment 1 "NOT_FOR_FAB - 9.45A tank RMS at 100A DC output, not 100A winding RMS")',
         '      (comment 2 "Through vias, CORE slots, AC proximity, L(I), DOT, 16mm assembly unqualified"))',
         '  (layers']
    for name,index in LAYER_NUM.items():
        t.append(f'    ({index} "{name}" signal)')
    t.extend(['    (37 "F.SilkS" user "F.Silkscreen")',
              '    (44 "Edge.Cuts" user)','    (49 "F.Fab" user)','  )',
              '  (setup (pad_to_mask_clearance 0.05))','  (net 0 "")',
              '  (net 1 "LR_CONDUCTOR_CONTINUOUS")'])
    outline=(q["x_min_mm"],q["y_min_mm"],q["x_max_mm"],q["y_max_mm"])
    for loop,rect in enumerate((outline,*slots)):
        for i,(a,b) in enumerate(_rect_edges(rect)):
            t.append(f'  (gr_line (start {fmt(a[0])} {fmt(a[1])}) '
                     f'(end {fmt(b[0])} {fmt(b[1])}) '
                     f'(stroke (width 0.05) (type default)) '
                     f'(layer "Edge.Cuts") (uuid "{_id(f"edge/{loop}/{i}")}"))')
    for turn,(path,layers) in enumerate(zip(routes,GROUPS),1):
        for layer in layers:
            for step,(a,b) in enumerate(zip(path,path[1:]),1):
                t.append(f'  (segment (start {fmt(a[0])} {fmt(a[1])}) '
                         f'(end {fmt(b[0])} {fmt(b[1])}) '
                         f'(width {fmt(q["trace_width_mm"])}) (layer "{layer}") '
                         f'(net 1) (uuid "{_id(f"turn/{turn}/{layer}/{step}")}"))')
    for i,xy in enumerate(endpoints):
        if i in (0,3):
            side="A" if i==0 else "B"
            ref="J_LR_"+side
            t+=['  (footprint "Lr_Terminal:Embedded_Lr_External_Terminal" (layer "F.Cu")',
                f'    (at {fmt(xy[0])} {fmt(xy[1])}) (uuid "{_id(ref)}")',
                f'    (property "Reference" "{ref}" (at 0 2) (layer "F.SilkS")',
                '      (effects (font (size 1 1) (thickness 0.15))))',
                f'    (property "Value" "PCB_Lr_2LAYERS_PER_TURN" (at 0 3.5) (layer "F.Fab")',
                '      (effects (font (size 0.8 0.8) (thickness 0.12))))',
                '    (attr through_hole)',
                f'    (fp_circle (center 0 0) (end 1.45 0) (stroke (width 0.05) (type default)) (fill none) (layer "F.CrtYd") (uuid "{_id(ref+"/courtyard")}"))',
                f'    (pad "1" thru_hole circle (at 0 0) '
                f'(size {fmt(q["terminal_pth_diameter_mm"])} '
                f'{fmt(q["terminal_pth_diameter_mm"])}) '
                f'(drill {fmt(q["terminal_pth_drill_mm"])}) '
                f'(layers "*.Cu" "*.Mask") (net 1 "LR_CONDUCTOR_CONTINUOUS") '
                f'(uuid "{_id(ref+"/pad")}") )',
                '  )']
        else:
            t.append(f'  (via (at {fmt(xy[0])} {fmt(xy[1])}) '
                     f'(size {fmt(q["transition_via_diameter_mm"])}) '
                     f'(drill {fmt(q["transition_via_drill_mm"])}) '
                     f'(layers "F.Cu" "B.Cu") (net 1) '
                     f'(uuid "{_id(f"transition/{i}")}"))')
    t+=[')']
    return "\n".join(t)+"\n"

def _footprint(trial):
    q=trial["board"]
    w=fmt(q["terminal_pth_diameter_mm"])
    dr=fmt(q["terminal_pth_drill_mm"])
    return f'''(footprint "Embedded_Lr_External_Terminal"
  (version 20260206) (generator "CZY_PCB_LR_TRIAL")
  (layer "F.Cu")
  (property "Reference" "REF**" (at 0 2) (layer "F.SilkS")
    (effects (font (size 1 1) (thickness 0.15))))
  (property "Value" "PCB_Lr_2LAYERS_PER_TURN" (at 0 3.5) (layer "F.Fab")
    (effects (font (size 0.8 0.8) (thickness 0.12))))
  (attr through_hole)
  (fp_circle (center 0 0) (end 1.45 0)
    (stroke (width 0.05) (type default)) (fill none) (layer "F.CrtYd"))
  (pad "1" thru_hole circle (at 0 0) (size {w} {w})
    (drill {dr}) (layers "*.Cu" "*.Mask"))
)
'''
def _fptable():
    return '(fp_lib_table (lib (name "Lr_Terminal")(type "KiCad")(uri "${KIPRJMOD}/Lr_Terminal.pretty")(options "")(descr "Local P0 Lr PCB trial terminal")))\n'

def contents():
    trial,case,routes,slots,endpoints,report=design()
    return (_kicad(trial,routes,slots,endpoints),
            json.dumps(report,ensure_ascii=False,indent=2)+"\n",
            _footprint(trial), _fptable())

def native_drc()->int:
    from main_board_mechanical import find_kicad_cli
    cli=find_kicad_cli()
    if cli is None:
        raise RuntimeError("kicad-cli is not installed; native DRC was NOT run")
    process=subprocess.run([str(cli),"pcb","drc","--all-track-errors",
                            "-o",str(DRC),str(PCB)],
                           capture_output=True,text=True,encoding="utf-8",errors="replace",
                           timeout=130)
    print("KiCad native PCB DRC status",process.returncode,
          "stdout:",process.stdout[-1200:],
          "stderr:",process.stderr[-1200:])
    if process.returncode!=0:
        print("DRC report",str(DRC))
    return process.returncode

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    opts=parser.add_mutually_exclusive_group(required=True)
    opts.add_argument("--write",action="store_true")
    opts.add_argument("--check",action="store_true")
    opts.add_argument("--drc",action="store_true")
    a=parser.parse_args()
    if a.drc:
        if not PCB.exists():raise SystemExit("generate native PCB first: --write")
        return native_drc()
    b,r,fp,table=contents()
    if a.write:
        OUT.mkdir(parents=True,exist_ok=True)
        FPLIB.parent.mkdir(parents=True,exist_ok=True)
        PCB.write_text(b,encoding="utf-8",newline="\n")
        REPORT.write_text(r,encoding="utf-8",newline="\n")
        FPLIB.write_text(fp,encoding="utf-8",newline="\n")
        FPTABLE.write_text(table,encoding="utf-8",newline="\n")
        print("KiCad native",PCB,"bytes",len(b.encode()),"SHA",_sha(PCB))
        print("screen",json.loads(r)["dc_copper_only_estimate"])
        return 0
    if not all(q.is_file() for q in (PCB,REPORT,FPLIB,FPTABLE)):
        raise SystemExit("missing native PCB, report, local footprint or library table; generate --write")
    if (PCB.read_text(encoding="utf-8")!=b or REPORT.read_text(encoding="utf-8")!=r
        or FPLIB.read_text(encoding="utf-8")!=fp or FPTABLE.read_text(encoding="utf-8")!=table):
        raise SystemExit("stale PCB or source; rerun --write and revalidate")
    print("Native PCB geometry/report match frozen inputs",_sha(PCB))
    return 0

if __name__=="__main__":
    raise SystemExit(main())

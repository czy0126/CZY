"""D1 G2 V14: source-locked four ELP32/N97 three-leg through-PCB slot screen.

Produces a real millimetre DXF twelve-NPTH-slot CAD import master, human
SVG with all 20 displaced raw pads, CSV, 12-layer winding/electrothermal
quantification and fail-closed JSON from independently saved V11 native PCB.

IMPORTANT: DXF is a DESIGN/DFM REQUEST, NOT verified native EasyEDA
board cutouts/Gerbers/approved manufacturer drawing. The existing 20 bare
T1-T4 magnetic pads all overlap the slot copper exclusion zones. NEVER
machine the actual V11 or V13 native PCB with this DXF without rebuilding
the winding/netlist, copper and EDA native DRC on a separate V14 board.

python tools/g2_v14_through_board_magnetics.py --write
python tools/g2_v14_through_board_magnetics.py --check
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import sys

from shapely.geometry import box, Point, LineString

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from g2_board_keepout import pad_bbox
G2=ROOT/"hardware/dcx_main/g2"
V11=G2/"dcx_main_board_g2_V11_NATIVE_SR_GATE_ESCAPE_NOT_FOR_FAB.eprj2"
NATIVE=G2/"g2_v11_independent_native_full_readback_NOT_FOR_FAB.json"
PINS=G2/"g2_five_magnetics_24_logical_pin_native_parity_NOT_FOR_FAB.json"
COMPONENT_SIDES=G2/"g2_v14_V13_native_component_layers_readonly_NOT_FOR_FAB.json"
OUT=G2/"g2_v14_through_board_three_leg_slot_DFM_screen_NOT_FOR_FAB.json"
DXF=G2/"g2_v14_ELP32_four_core_12_NPTH_slot_toolpaths_NOT_FOR_FAB.dxf"
SVG=G2/"g2_v14_double_sided_slot_winding_overlay_NOT_FOR_FAB.svg"
CSV=G2/"g2_v14_ELP32_12_NPTH_slot_coordinates_NOT_FOR_FAB.csv"
SOURCE_SHA="d90ca22079ad7245e8c3904eb8369da58c705ae39b56574bf7843dad34cad89b"
MM_PER_MIL=.0254
BOARD=(155.0,131.0)
REFS=("T1","T2","T3","T4")
CENTERS=(20.,58.,96.,134.)
Y=20.
TDK_DATASHEET="https://www.tdk-electronics.tdk.com/inf/80/db/fer/elp_32_6_20.pdf"
# TDK ELP32 clamp-recess E-I physical constraints, drawing on datasheet p4.
CORE_X_NOM_MM=31.75
CORE_X_TOL_MM=.65
OUTER_LEG_SPAN_NOM_MM=25.4
OUTER_SPAN_TOL_MM=.5
CENTER_LEG_WIDTH_NOM_MM=6.35
CENTER_LEG_TOL_MM=.15
CORE_Y_NOM_MM=20.35
CORE_Y_TOL_MM=.4
# This is a project engineering prototype, not TDK's slot drawing.
# Include fabrication (-0.2mm each routed opening) and a generous
# leg center registration allowance, rather than just nominal leg size.
ROUTER_HALF_TOL_MM=.2
DESIRED_PER_SIDE_FIT_MM=.25
CNC_CORNER_R_MM=.6
COPPER_ROUTER_EDGE_GAP_MM=.5
OUTER_SLOT_W_MM=5.5
INNER_SLOT_W_MM=7.8
SLOT_LENGTH_MM=22.0
E_CORE_HEIGHT_MM=6.35
I_PLATE_HEIGHT_MM=3.15
WINDOW_NOM_MM=3.2
PCB_THICKNESS_CANDIDATE_MM=2.0
# 12-layer 4oz copper is an unconfirmed exotic manufacturing scenario.
COPPER_WIDTH_MM=5.0
WINDING_X_SIDE_MM=6.9
WINDING_Y_TOP_MM=6.0
WINDING_Y_BOTTOM_MM=34.0
WINDING_LENGTH_MM=2*(WINDING_Y_BOTTOM_MM-WINDING_Y_TOP_MM)+2*WINDING_X_SIDE_MM
RHO_20=1.724e-8
COPPER_TEMP_COEFF=.00393
TEMP_C=100.0
I_PRIMARY_RMS_A=9.45014
I_OUTPUT_DC_A=100.0
NUMBER_OF_TRANSFORMERS=4
SOURCE_COPPER_TOTAL_W=2.1345487382830086
SOURCE_PRIMARY_COPPER_W=.8934179898819625
SOURCE_SECONDARY_COPPER_W=1.2411307484010459


def sha(p:Path):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def data():
    if sha(V11)!=SOURCE_SHA:
        raise ValueError("Independently reopened V11 source SHA changed")
    d=json.loads(NATIVE.read_text("utf8"))
    if (d["source_native_sha256"]!=SOURCE_SHA or
        d["native_counts"]!={"components":149,"pads":443,"lines":465,"vias":93,"nets":65}):
        raise ValueError("Native V11 validated geometry baseline changed")
    p=json.loads(PINS.read_text("utf8"))
    if (p["source_sha256"]["native_V11_saved_eprj2"]!=SOURCE_SHA or
        p["real_electrical_pin_count"]!=24 or
        p["vendor_mechanical_pin_numbers_confirmed"]!=0):
        raise ValueError("Five magnetics native pad evidence changed or vendor signed")
    sides=json.loads(COMPONENT_SIDES.read_text("utf8"))["source_V13_native"]
    if sides["components"]!=149 or sides["layers"]!={"1":149}:
        raise ValueError("Baseline board already has bottom-side components; re-audit")
    return d["real_native_data"],p


def capsule_roundrect(x1,y1,x2,y2,r,segments=5):
    """CCW closed polyline points with independently specified corner radius."""
    points=[]
    for cx,cy,angles in ((x2-r,y1+r,(-90,0)),
                         (x2-r,y2-r,(0,90)),
                         (x1+r,y2-r,(90,180)),
                         (x1+r,y1+r,(180,270))):
        a,b=angles
        for j in range(segments+1):
            theta=math.radians(a+(b-a)*j/segments)
            points.append((round(cx+r*math.cos(theta),6),
                           round(cy+r*math.sin(theta),6)))
    return points


def slot_geometry():
    # The outer-leg nominal projected center is half the E length minus
    # half its nominal outer wall thickness. Actual factory registration
    # remains a mandatory first-article check.
    leg_width=(CORE_X_NOM_MM-OUTER_LEG_SPAN_NOM_MM)/2.
    offset=CORE_X_NOM_MM/2.-leg_width/2.
    assert math.isclose(offset,14.2875,abs_tol=1e-6)
    # Worst case leg span if independent tolerances grow opposite ways.
    largest_outer=(CORE_X_NOM_MM+CORE_X_TOL_MM-
                   (OUTER_LEG_SPAN_NOM_MM-OUTER_SPAN_TOL_MM))/2.
    largest_center=CENTER_LEG_WIDTH_NOM_MM+CENTER_LEG_TOL_MM
    longest=CORE_Y_NOM_MM+CORE_Y_TOL_MM
    for nominal,largest in ((OUTER_SLOT_W_MM,largest_outer),
                            (INNER_SLOT_W_MM,largest_center),
                            (SLOT_LENGTH_MM,longest)):
        if nominal-(2*ROUTER_HALF_TOL_MM+2*DESIRED_PER_SIDE_FIT_MM)<largest:
            raise ValueError("NPTH slot insufficient for worst-case core+router tolerance")
    slots=[]
    for ref,cx in zip(REFS,CENTERS):
        for leg,shift,w in (("LEFT",-offset,OUTER_SLOT_W_MM),
                            ("CENTRE",0.,INNER_SLOT_W_MM),
                            ("RIGHT",offset,OUTER_SLOT_W_MM)):
            centerx=cx+shift
            x1,x2=centerx-w/2,centerx+w/2
            y1,y2=Y-SLOT_LENGTH_MM/2,Y+SLOT_LENGTH_MM/2
            if min(x1,y1)<.6 or x2>BOARD[0]-.6 or y2>BOARD[1]-.6:
                raise ValueError("Core slot outside guaranteed PCB outline")
            slots.append({"id":f"{ref}_{leg}","device":ref,
               "leg":leg,"center_x_mm":round(centerx,4),"center_y_mm":Y,
               "width_mm":w,"length_mm":SLOT_LENGTH_MM,
               "corner_radius_mm":CNC_CORNER_R_MM,
               "x_min_mm":round(x1,5),"x_max_mm":round(x2,5),
               "y_min_mm":round(y1,5),"y_max_mm":round(y2,5)})
    return slots


def geom(slot):
    return box(slot["x_min_mm"],slot["y_min_mm"],
               slot["x_max_mm"],slot["y_max_mm"])


def electrical_clashes(slots,pcb,pin_doc):
    clashes=[]
    for slot in slots:
        keep=geom(slot).buffer(COPPER_ROUTER_EDGE_GAP_MM,join_style=2)
        for pad in pcb["pads"]:
            px=float(pad["X"])*MM_PER_MIL; py=-float(pad["Y"])*MM_PER_MIL
            # Native pad_bbox also handles POLYGON pads and pad rotation.
            if keep.intersects(box(*pad_bbox(pad))):
                clashes.append({"slot":slot["id"],"kind":"PAD",
                       "pcb_ref":pad.get("ref") or "UNLINKED_MAGNETIC_RAW_PAD",
                       "pad_number":str(pad["PadNumber"]),"net":pad["Net"],
                       "point_mm":[round(px,4),round(py,4)]})
        for line in pcb["lines"]:
            a=(float(line["x1"])*MM_PER_MIL,-float(line["y1"])*MM_PER_MIL)
            b=(float(line["x2"])*MM_PER_MIL,-float(line["y2"])*MM_PER_MIL)
            thick=float(line["width"])*MM_PER_MIL
            if LineString([a,b]).buffer(thick/2).intersects(keep):
                clashes.append({"slot":slot["id"],"kind":"COPPER_TRACK",
                        "native_line_uuid":line["id"],"net":line["net"]})
        for via in pcb["vias"]:
            point=(float(via["x"])*MM_PER_MIL,-float(via["y"])*MM_PER_MIL)
            radius=float(via["diameter"])*MM_PER_MIL/2
            if Point(*point).buffer(radius).intersects(keep):
                clashes.append({"slot":slot["id"],"kind":"VIA",
                    "native_via_uuid":via["id"],"net":via["net"]})
    raw={(p["reference"],p["logical_terminal"]) for p in pin_doc["pin_rows"]
         if p["reference"] in REFS}
    old_pad_collisions={(x["net"],x["pad_number"],x["point_mm"][0],x["point_mm"][1])
                for x in clashes if x["kind"]=="PAD" and
                x["pcb_ref"]=="UNLINKED_MAGNETIC_RAW_PAD"}
    if len(raw)!=20 or len(old_pad_collisions)!=20:
        raise ValueError("12-slot plan no longer collides with exactly 20 old magnetic pads; re-screen")
    if any(x["kind"]=="PAD" and x["pcb_ref"]!="UNLINKED_MAGNETIC_RAW_PAD" for x in clashes):
        raise ValueError("New cutouts collide with additional active native components")
    if any(x["kind"] not in ("PAD","COPPER_TRACK","VIA") for x in clashes):
        raise ValueError("Unknown native copper obstruction")
    return clashes


def winding_screen():
    # Copper winding U-turn is deliberately NOT an electrically finished
    # via/antipad topology: 3 primary turns require actual series blind/
    # buried via transitions. Same-net secondary parallel layers must also
    # be verified for phase, conductor heating and proximity losses.
    span=OUTER_SLOT_W_MM/2 # not used in copper width; reserve explicit
    inner_half=INNER_SLOT_W_MM/2
    outer_inner=(CORE_X_NOM_MM/2-((CORE_X_NOM_MM-OUTER_LEG_SPAN_NOM_MM)/2)/2)-OUTER_SLOT_W_MM/2
    channel=outer_inner-inner_half
    available=channel-2*COPPER_ROUTER_EDGE_GAP_MM
    assert available>COPPER_WIDTH_MM
    min_side=inner_half+COPPER_ROUTER_EDGE_GAP_MM+COPPER_WIDTH_MM/2
    max_side=outer_inner-COPPER_ROUTER_EDGE_GAP_MM-COPPER_WIDTH_MM/2
    if not min_side<=WINDING_X_SIDE_MM<=max_side:
        raise ValueError("One turn U-shaped PCB trace does not fit cutout channels")
    centerline_top=Y-(SLOT_LENGTH_MM/2+COPPER_ROUTER_EDGE_GAP_MM+COPPER_WIDTH_MM/2)
    centerline_bottom=Y+(SLOT_LENGTH_MM/2+COPPER_ROUTER_EDGE_GAP_MM+COPPER_WIDTH_MM/2)
    if not (math.isclose(centerline_top,WINDING_Y_TOP_MM) and
            math.isclose(centerline_bottom,WINDING_Y_BOTTOM_MM)):
        raise ValueError("Top/bottom overpass clearance is lost")
    # Per device Iout = Iout_all/4, for symmetric half cycle
    # half-winding I_rms = (Iout_device) / sqrt(2).
    i_transformer=I_OUTPUT_DC_A/NUMBER_OF_TRANSFORMERS
    i_half=i_transformer/math.sqrt(2)
    scenarios=[]
    for name,layer_total,thickness_um,nSA,nSB,primary_parallel in [
        ("8L_2OZ_secondary2_each",8,70,2,2,1),
        ("12L_2OZ_secondary4_each",12,70,4,4,1),
        ("12L_4OZ_secondary4_each",12,140,4,4,1),
        ("16L_4OZ_secondary6_each",16,140,6,6,1)]:
        primary_turns=3
        required=primary_turns*primary_parallel+nSA+nSB
        if required>layer_total:
            raise ValueError("Electromagnetic layer stack exceeding layer count")
        rho=RHO_20*(1+COPPER_TEMP_COEFF*(TEMP_C-20))
        single=rho*(WINDING_LENGTH_MM*.001)/(COPPER_WIDTH_MM*.001*thickness_um*1e-6)
        r_primary=primary_turns*single/primary_parallel
        # Two secondary 1-turn half windings, each parallel-layer count.
        r_half_a=single/nSA
        r_half_b=single/nSB
        one_primary=I_PRIMARY_RMS_A**2*r_primary
        one_secondary=i_half**2*(r_half_a+r_half_b)
        scenarios.append({
          "scenario":name,"pcb_layer_count":layer_total,
          "assumed_every_winding_layer_copper_um":thickness_um,
          "primary_series_turns":3,"primary_parallel_layers_per_turn":primary_parallel,
          "secondary_half_A_one_turn_parallel_layers":nSA,
          "secondary_half_B_one_turn_parallel_layers":nSB,
          "occupied_ideal_winding_layers":required,
          "remaining_ideal_layers":layer_total-required,
          "single_winding_U_centerline_length_mm":WINDING_LENGTH_MM,
          "single_layer_hot_100C_dc_resistance_mOhm":round(single*1e3,5),
          "four_core_primary_dc_copper_loss_100C_W":round(one_primary*4,4),
          "four_core_secondary_dc_copper_loss_100C_W":round(one_secondary*4,4),
          "four_core_total_dc_copper_loss_100C_W":round((one_primary+one_secondary)*4,4),
          "vs_original_100A_20C_model_W":round((one_primary+one_secondary)*4-SOURCE_COPPER_TOTAL_W,4),
          "underestimates_actual_AC_proximity_via_DOT_and_hotspots":True,
          "fabricator_can_build_this_stackup_approved":False
        })
    # Reserve explicit phase/series topology, never treat ideal layer allocation as netlist.
    mapping=[
      {"layer":1,"functional_name":"P1", "net_start":"PRI_A","net_end":"P12_VIA_BURIED_TBD"},
      {"layer":2,"functional_name":"SA1","net_start":"SEC_A","net_end":"CTAP"},
      {"layer":3,"functional_name":"SB1","net_start":"SEC_B","net_end":"CTAP"},
      {"layer":4,"functional_name":"P2","net_start":"P12_VIA_BURIED_TBD","net_end":"P23_VIA_BURIED_TBD"},
      {"layer":5,"functional_name":"SA2","net_start":"SEC_A","net_end":"CTAP"},
      {"layer":6,"functional_name":"SB2","net_start":"SEC_B","net_end":"CTAP"},
      {"layer":7,"functional_name":"P3","net_start":"P23_VIA_BURIED_TBD","net_end":"PRI_B"},
      {"layer":8,"functional_name":"SA3","net_start":"SEC_A","net_end":"CTAP"},
      {"layer":9,"functional_name":"SB3","net_start":"SEC_B","net_end":"CTAP"},
      {"layer":10,"functional_name":"SA4","net_start":"SEC_A","net_end":"CTAP"},
      {"layer":11,"functional_name":"SB4","net_start":"SEC_B","net_end":"CTAP"},
      {"layer":12,"functional_name":"RESERVED","net_start":None,"net_end":None},
    ]
    return {
      "channel_between_center_and_outer_slot_mm":round(channel,4),
      "usable_channel_copper_width_mm":round(available,4),
      "screened_copper_trace_width_mm":COPPER_WIDTH_MM,
      "U_turn_centerline_side_offset_mm":WINDING_X_SIDE_MM,
      "U_turn_centerline_y_mm":[WINDING_Y_TOP_MM,WINDING_Y_BOTTOM_MM],
      "conductor_U_turn_length_mm":WINDING_LENGTH_MM,
      "upper_copper_path_clearance_to_slot_mm":COPPER_ROUTER_EDGE_GAP_MM,
      "primary_rms_assumed_A":I_PRIMARY_RMS_A,
      "secondary_each_transformer_output_dc_A":i_transformer,
      "secondary_each_half_rms_concept_A":round(i_half,4),
      "TDK_3p2mm_core_window_mechanical_fit":PCB_THICKNESS_CANDIDATE_MM<WINDOW_NOM_MM,
      "PCB_thickness_candidate_mm":PCB_THICKNESS_CANDIDATE_MM,
      "nominal_E_plus_I_core_total_height_mm":E_CORE_HEIGHT_MM+I_PLATE_HEIGHT_MM,
      "nominal_per_side_ferrite_protrusion_with_centered_2mm_board_mm":
          round((E_CORE_HEIGHT_MM+I_PLATE_HEIGHT_MM-PCB_THICKNESS_CANDIDATE_MM)/2,3),
      "existing_native_component_top_count":149,
      "existing_native_component_bottom_count":0,
      "actual_board_has_12layer_stackup_configured_and_vendor_signed":False,
      "required_interlayer_anti_pad_microvia_layout_done":False,
      "primary_3turns_magnetic_dot_and_CTAP_polarity_verified":False,
      "12layer_copper_feasibility_and_16mm_coldplate_full_stackup_verified":False,
      "candidate_12layer_4oz_winding_assignment_not_routed":mapping,
      "scenarios":scenarios
    }


def build():
    pcb,pin_doc=data()
    slots=slot_geometry()
    clashes=electrical_clashes(slots,pcb,pin_doc)
    winding=winding_screen()
    counts={}
    for k in ("PAD","COPPER_TRACK","VIA"):
        counts[k]=len([x for x in clashes if x["kind"]==k])
    if len(slots)!=12 or counts["PAD"]!=20 or counts["COPPER_TRACK"]!=7 or counts["VIA"]!=3:
        raise ValueError("V14 slot baseline interference drift")
    # Triple E legs are holes; do not cut away whole 31.75x20.35mm core.
    return {
      "schema":"G2_D1_V14_FOUR_ELP32_12_NPTH_SLOT_WITH_PCB_WINDING_V1",
      "status":"12_SLOT_20_PAD_7_TRACK_3_VIA_REDESIGN_REQUIRED_NOT_FOR_FAB",
      "sources":{"TDK_ELP32_2022_datasheet":TDK_DATASHEET,
        "JLCPCB_PCB_capabilities":"https://jlcpcb.com/capabilities/pcb-capabilities",
        "native_V11_saved_eprj2_sha256":SOURCE_SHA,
        "native_V11_independent_PCB_readback_sha256":sha(NATIVE),
        "five_magnetics_24pin_logical_native_evidence_sha256":sha(PINS),
        "native_V13_same_existing_GUI_component_side_receipt_sha256":sha(COMPONENT_SIDES)},
      "board_dimensions_mm":list(BOARD),
      "ELP32_E_and_I_N97_TDK":{
         "ELP_ordering_code":"B66287G0000X197",
         "I_plate_ordering_code":"B66287K0000X197",
         "outer_x_nom_mm":CORE_X_NOM_MM,"outer_x_plusminus_mm":CORE_X_TOL_MM,
         "outer_leg_inner_span_nom_mm":OUTER_LEG_SPAN_NOM_MM,
         "outer_leg_inner_span_plusminus_mm":OUTER_SPAN_TOL_MM,
         "center_leg_x_nom_mm":CENTER_LEG_WIDTH_NOM_MM,
         "center_leg_x_plusminus_mm":CENTER_LEG_TOL_MM,
         "core_y_nom_mm":CORE_Y_NOM_MM,
         "core_y_plusminus_mm":CORE_Y_TOL_MM,
         "magnetic_window_height_nom_mm":WINDOW_NOM_MM,
         "ELP_E_height_nom_mm":E_CORE_HEIGHT_MM,
         "I_plate_height_nom_mm":I_PLATE_HEIGHT_MM,
         "core_e_plus_I_nominal_total_mm":E_CORE_HEIGHT_MM+I_PLATE_HEIGHT_MM,
         "all_3_legs_electric_grounded_and_metalized":False,
       },
      "PCB_slot_design_assumptions":{
         "nonplated_routed_slots_only":True,
         "slot_centers_are_nominal_not_oem_assembly_datums":True,
         "max_router_tolerance_per_side_mm":ROUTER_HALF_TOL_MM,
         "desired_core_to_actual_routed_wall_gap_each_side_mm":DESIRED_PER_SIDE_FIT_MM,
         "routed_slot_copper_keepout_mm":COPPER_ROUTER_EDGE_GAP_MM,
         "minimum_non_plated_slot_width_from_JLCPCB_mm":1.0,
         "standard_milling_corner_radius_mm":CNC_CORNER_R_MM,
         "supplier_slot_vendor_DFM_and_3D_signed":False
       },
      "slot_count":len(slots),
      "slots":slots,
      "actual_native_V11_overlap_counts":counts,
      "actual_native_V11_overlap_details":clashes,
      "requires_remove_or_rebuild_all_20_old_magnetics_raw_pads":True,
      "requires_rewire_output_VOUT_lines_and_vias_around_slots":True,
      "ELP38_Lr_same_layout_suitable_for_throughboard_cutdown":False,
      "CT_remains_separate_real_4terminal_sensing_device_pending_vendor_PIN_DOT":True,
      "winding_electrothermal_and_double_sided_preliminary":winding,
      "required_before_fab":[
         "Change V14 native outline with 12 real internal NPTH routs; delete/relocate 20 raw pads and 7 original VOUT lines/3 vias through copper exclusion; verify independent saved native DRC",
         "Electromagnetically and physically route 3 series primary turns and two 1-turn centered secondary half-windings for each of four cores with verified plated vs NPTH barriers, blind/buried via antipads, copper and 200kHz Maxwell nonlinear losses",
         "Factory approve high layer count and inner 140um Cu manufacturability/insulation; no unapproved 12L 4oz assumption",
         "Reintegrate 100A separate VOUT & PGND physical current bar and SR; validate 100A copper thermals and current sharing",
         "Reverse-side component layout only after real part heights, placement/assembly access, cooling plate machining and full 16mm worst case",
         "Supplier ELP32 E/I orientation, radius, fixture 3D, torque, gap, thermal stress and Core DOT/CT physical 4 terminal signed",
         "Native PCB Connection/Netlist/Physical DRC all zero, GUI reopened, first article V48/2V 100A safe protection and thermal test",
      ],
      "released_copper_stackup":False,"native_cutouts_already_applied":False,
      "native_winding_tracks_already_applied":False,
      "fabrication_approved":False,"fab_release":"NOT_FOR_FAB"
    }


def _pairs(*v):
    out=[]
    for x in v:
        if isinstance(x,(int,float)):
            out.extend([str(x)])
        else:out.append(x)
    return "\n".join(out)+"\n"


def _dxf_polyline(points,layer):
    output=["0","POLYLINE","8",layer,"66","1","70","1"]
    for x,y in points:
        output+=["0","VERTEX","8",layer,"10",f"{x:.6f}","20",f"{y:.6f}","30","0"]
    output+=["0","SEQEND","8",layer]
    return output


def dxf(model):
    o=["0","SECTION","2","HEADER","9","$ACADVER","1","AC1009",
       "9","$MEASUREMENT","70","1","0","ENDSEC",
       "0","SECTION","2","ENTITIES"]
    o+=_dxf_polyline([(0,0),(BOARD[0],0),(BOARD[0],BOARD[1]),(0,BOARD[1])],"EXISTING_BOARD_155X131_REFERENCE")
    for s in model["slots"]:
        rounded=capsule_roundrect(s["x_min_mm"],s["y_min_mm"],s["x_max_mm"],s["y_max_mm"],CNC_CORNER_R_MM,segments=8)
        o+=_dxf_polyline(rounded,"V14_NPTH_SLOT_12_PRELIM")
        expanded=geom(s).buffer(COPPER_ROUTER_EDGE_GAP_MM,join_style=2)
        x1,y1,x2,y2=expanded.bounds
        o+=_dxf_polyline([(x1,y1),(x2,y1),(x2,y2),(x1,y2)],"V14_COPPER_KEEP_OUT_0P5_PRELIM")
    for ref,cx in zip(REFS,CENTERS):
        o+=_dxf_polyline([(cx-CORE_X_NOM_MM/2,Y-CORE_Y_NOM_MM/2),
                          (cx+CORE_X_NOM_MM/2,Y-CORE_Y_NOM_MM/2),
                          (cx+CORE_X_NOM_MM/2,Y+CORE_Y_NOM_MM/2),
                          (cx-CORE_X_NOM_MM/2,Y+CORE_Y_NOM_MM/2)],
                         "TDK_ELP32_NOMINAL_3D_OUTLINE")
        o+=_dxf_polyline([(cx-WINDING_X_SIDE_MM,WINDING_Y_BOTTOM_MM),
                          (cx-WINDING_X_SIDE_MM,WINDING_Y_TOP_MM),
                          (cx+WINDING_X_SIDE_MM,WINDING_Y_TOP_MM),
                          (cx+WINDING_X_SIDE_MM,WINDING_Y_BOTTOM_MM)],
                         "WINDING_U_CENTRELINE_CONCEPT_NOT_COPPER")
    o+=["0","ENDSEC","0","EOF"]
    return "\n".join(o)+"\n"


def slot_csv(model):
    output=io.StringIO()
    columns=["id","device","leg","center_x_mm","center_y_mm","width_mm","length_mm",
             "corner_radius_mm","x_min_mm","x_max_mm","y_min_mm","y_max_mm"]
    w=csv.DictWriter(output,fieldnames=columns,lineterminator="\n")
    w.writeheader()
    for item in model["slots"]:w.writerow(item)
    return output.getvalue()


def svg(model):
    scale=5.0
    w=BOARD[0]*scale
    h=BOARD[1]*scale
    style="""<style>
    .bg{fill:#f9fbff}.pcb{fill:#eff4f9;stroke:#1c4664;stroke-width:.9}
    .core{fill:none;stroke:#244ea0;stroke-width:.35;stroke-dasharray:1.5 1.5}
    .slot{fill:#f8ebe8;stroke:#cd493d;stroke-width:.45}
    .keep{fill:none;stroke:#ed8f22;stroke-width:.22;stroke-dasharray:.8 .5}
    .winding{fill:none;stroke:#14967f;stroke-width:1.1;stroke-linecap:round;stroke-linejoin:round}
    .old{fill:#cd493d;stroke:#fff;stroke-width:.3}
    .label{fill:#23394b;font:2.8px sans-serif;text-anchor:middle}
    .small{fill:#23394b;font:2.2px sans-serif}
    </style>"""
    out=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-3 -18 {BOARD[0]+6} {BOARD[1]+23}" width="{w}" height="{h+60}">',style,
         f'<rect class="bg" x="-3" y="-18" width="{BOARD[0]+6}" height="{BOARD[1]+23}"/>',
         '<text class="small" x="2" y="-12" style="font-weight:bold;font-size:4px">D1 G2 V14 — ELP32 12 slot concept · NOT FOR FAB</text>',
         '<text class="small" x="2" y="-7">Red = NPTH  |  Orange = 0.5 mm copper keepout  |  Green = 1-turn U track concept  |  Red dots = obsolete 20 native pads</text>',
         f'<rect class="pcb" x="0" y="0" width="{BOARD[0]}" height="{BOARD[1]}"/>']
    for ref,cx in zip(REFS,CENTERS):
        x0=cx-CORE_X_NOM_MM/2;y0=Y-CORE_Y_NOM_MM/2
        out.append(f'<rect class="core" x="{x0}" y="{y0}" width="{CORE_X_NOM_MM}" height="{CORE_Y_NOM_MM}"/>')
        out.append(f'<text class="label" x="{cx}" y="2.5">{ref}</text>')
        points=[(cx-WINDING_X_SIDE_MM,WINDING_Y_BOTTOM_MM),
                (cx-WINDING_X_SIDE_MM,WINDING_Y_TOP_MM),
                (cx+WINDING_X_SIDE_MM,WINDING_Y_TOP_MM),
                (cx+WINDING_X_SIDE_MM,WINDING_Y_BOTTOM_MM)]
        stroke=" ".join(f"{a:.3f},{b:.3f}" for a,b in points)
        out.append(f'<polyline class="winding" points="{stroke}"/>')
    for slot in model["slots"]:
        s=slot;left=s["x_min_mm"];top=s["y_min_mm"]
        out.append(f'<rect class="keep" x="{left-COPPER_ROUTER_EDGE_GAP_MM}" y="{top-COPPER_ROUTER_EDGE_GAP_MM}" width="{s["width_mm"]+2*COPPER_ROUTER_EDGE_GAP_MM}" height="{s["length_mm"]+2*COPPER_ROUTER_EDGE_GAP_MM}"/>')
        out.append(f'<rect class="slot" x="{left}" y="{top}" width="{s["width_mm"]}" height="{s["length_mm"]}" rx="{CNC_CORNER_R_MM}"/>')
    old=sorted({tuple(x["point_mm"]) for x in model["actual_native_V11_overlap_details"]
                if x["kind"]=="PAD"})
    if len(old)!=20:raise ValueError("Obsolete raw magnetic pads not 20")
    for x,y in old:out.append(f'<circle class="old" cx="{x}" cy="{y}" r=".95"/>')
    out+=['<text class="small" x="2" y="41">⚠ 20 old pads, 7 VOUT tracks and 3 vias must move</text>',
          '<text class="small" x="2" y="124">155 × 131 mm saved G2 outline · bottom-side layout not yet routed · DXF is NOT a PCB fabrication file</text>',
          '</svg>']
    return "\n".join(out)+"\n"


def deliverables():
    model=build()
    return {
       OUT:json.dumps(model,ensure_ascii=False,indent=2)+"\n",
       DXF:dxf(model),
       SVG:svg(model),
       CSV:slot_csv(model)
    }


def main():
    p=argparse.ArgumentParser()
    mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write",action="store_true")
    mode.add_argument("--check",action="store_true")
    args=p.parse_args()
    generated=deliverables()
    for dest,raw in generated.items():
        if args.check:
            if not dest.exists() or dest.read_text("utf8")!=raw:
                raise ValueError("V14 native source-bound geometry/CAD artifact missing or stale "+str(dest))
        else:
            if dest.exists() and dest.read_text("utf8")!=raw:
                raise ValueError("Refuse destructive overwrite of existing V14 CAD candidate "+str(dest))
            dest.write_text(raw,encoding="utf8",newline="\n")
    report=build()
    print(json.dumps({"status":report["status"],
      "NPTH_slot_count":report["slot_count"],
      "pad_line_via_interference_counts":report["actual_native_V11_overlap_counts"],
      "winding_channel_usable_mm":report["winding_electrothermal_and_double_sided_preliminary"]["usable_channel_copper_width_mm"],
      "fabrication_approved":False},ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()

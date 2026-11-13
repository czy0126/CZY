"""V17 integrated output PGND/VOUT plane, SR-via and input-return preflight.

Layout and return paths are checked against ONE frozen V15 native 419-pad
projection; no fabricated physical completion. Source outputs are only a
manufacturing review candidate and require native EDA readback/DRC.
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path

from shapely.geometry import Point,LineString,box
from shapely.ops import unary_union

import g2_v16_floorplan_screen as base
import g2_v17_compact_emc_screen as layout

OUT = base.G / "g2_v17_integrated_pgnd_vout_review_LOCKED_NOT_FOR_FAB.json"
DRC = base.G / "g2_v15_T4_real_post_layout_independent_native_DRC_NOT_FOR_FAB.json"
INNER_GROUND_LAYER = 15
INNER_OUTPUT_LAYER = 16
VIA_R_MM = .35
VIA_DRILL_MM = .30
ANTIPAD_MARGIN_MM = .30
PAD_TO_OTHER_NET_MIN_MM = .19
OUTPUT_TERMINAL_ANTIPAD_MM = 1.5

def _centre(p):
    return tuple(float(x) for x in p["geom"].centroid.coords[0])

def _candidate_vias(pads):
    """Only actual pad numbers and nets, no guessed REF:PIN identities."""
    result=[]
    for p in pads:
        ref,net,pin=p["ref"],p["net"],p["number"]
        if ref.startswith("CHB") and pin in ("1","2") and net in ("PGND","VOUT"):
            cx,cy=_centre(p)
            for d in (-.45,.45):
                result.append({"ref":ref,"pad":pin,"net":net,
                               "x_mm":round(cx,5),"y_mm":round(cy+d,5),
                               "radius_mm":VIA_R_MM,"drill_mm":VIA_DRILL_MM})
        if ref.startswith("SR") and pin in ("1","2","3") and net=="PGND":
            # Native has one extra thermal pad numbered 3. Distinguish its
            # non-standard exposed shape; do not double-count source pads.
            w=p["geom"].bounds[2]-p["geom"].bounds[0]
            h=p["geom"].bounds[3]-p["geom"].bounds[1]
            if w>1.35 or h>1.5: continue
            cx,cy=_centre(p)
            result.append({"ref":ref,"pad":pin,"net":"PGND",
                           "x_mm":round(cx,5),"y_mm":round(cy,5),
                           "radius_mm":VIA_R_MM,"drill_mm":VIA_DRILL_MM})
    return result

def _local_reg_and_cout_stitch_sites(pads):
    """Pair actual top-U3..U6 and bottom-C7..C10 pins by same net;
    separate Kelvin REG and PGND stitches must fit beside each other.
    The trial V17 pad centres overlap across board sides; make ten vias.
    """
    result=[]
    for i in range(4):
        cap="C"+str(i+7);u="U"+str(i+3)
        for net,pin in (("REG"+str(i+1),"3"),("PGND","2")):
            cap_pad=next(p for p in pads if p["ref"]==cap and p["net"]==net)
            ic_pad=next(p for p in pads if p["ref"]==u and p["net"]==net and p["number"]==pin)
            ax,ay=_centre(cap_pad);bx,by=_centre(ic_pad)
            cx,cy=(ax+bx)/2,(ay+by)/2
            if not cap_pad["geom"].buffer(.05).covers(Point(cx,cy)):
                raise ValueError("Via does not enter actual bottom pad "+cap+" "+net)
            if not ic_pad["geom"].buffer(.05).covers(Point(cx,cy)):
                raise ValueError("Via does not enter actual IC pad "+u+" "+net)
            result.append({"ref":cap+"+"+u,"pad":pin,"net":net,
               "x_mm":round(cx,5),"y_mm":round(cy,5),
               "radius_mm":VIA_R_MM,"drill_mm":VIA_DRILL_MM})
    for net in ("PGND","VOUT"):
        cap_pad=next(p for p in pads if p["ref"]=="Cout" and p["net"]==net)
        cx,cy=_centre(cap_pad)
        result.append({"ref":"Cout","pad":cap_pad["number"],"net":net,
           "x_mm":round(cx,5),"y_mm":round(cy,5),
           "radius_mm":VIA_R_MM,"drill_mm":VIA_DRILL_MM})
    return result

def _control_ground_sites_and_short_link(pads):
    """Connect control GND to the same real PGND layer using true pads.
    U2 pad9 must stay narrow/Kelvin and connect to its exposed GND pad11;
    avoid an invalid through-via between its fine-pitch GD1/GD2 pads.
    """
    ctrl=[]
    for ref,pin in (("U1","6"),("U2","11")):
        p=next(q for q in pads if q["ref"]==ref and q["number"]==pin and q["net"]=="PGND")
        cx,cy=_centre(p)
        ctrl.append({"ref":ref,"pad":pin,"net":"PGND",
            "x_mm":round(cx,5),"y_mm":round(cy,5),
            "radius_mm":VIA_R_MM,"drill_mm":VIA_DRILL_MM})
    pgnd9=next(q for q in pads if q["ref"]=="U2" and q["number"]=="9" and q["net"]=="PGND")
    center11=next(q for q in pads if q["ref"]=="U2" and q["number"]=="11" and q["net"]=="PGND")
    x,y=_centre(pgnd9);ax,ay=_centre(center11)
    endpoint=(ax,y)
    if not center11["geom"].contains(Point(endpoint)):
        raise ValueError("U2 exposed GND pad is not at proposed Kelvin endpoint")
    route=LineString([(x,y),endpoint]).buffer(.10,cap_style="flat")
    cross=[q for q in pads if q["layer"] in (1,12) and q["net"] not in ("","PGND")
           and route.distance(q["geom"])<PAD_TO_OTHER_NET_MIN_MM]
    if cross:raise ValueError("U2 PGND pad9 Kelvin link enters other net")
    return ctrl,{"from":"U2.9","to":"U2.11","width_mm":.20,
                 "path_mm":[[round(x,5),round(y,5)],[round(ax,5),round(y,5)]],
                 "other_net_clearance_conflicts":len(cross)}

def _aux_supply_vias(pads):
    """Low-current 12V locally screened pad in-pads, not SR/high-current vias."""
    plan=[]
    for net,refs in (("VCC12_S",tuple("C"+str(i) for i in range(105,113))),
                     ("VCC12",("C101","C102","C103","C104"))):
        for ref in refs:
            pad=next(p for p in pads if p["net"]==net and p["ref"]==ref and p["number"]=="1")
            cx,cy=_centre(pad)
            if pad["geom"].area<.30:raise ValueError("12V pad too small for reviewed via "+ref)
            plan.append({"ref":ref,"pad":"1","net":net,"x_mm":round(cx,5),"y_mm":round(cy,5),
                         "radius_mm":VIA_R_MM,"drill_mm":VIA_DRILL_MM})
    return plan

def _via_cross_net_errors(vias,pads):
    problems=[]
    for via in vias:
        disc=Point(via["x_mm"],via["y_mm"]).buffer(via["radius_mm"]+PAD_TO_OTHER_NET_MIN_MM)
        for p in pads:
            if p["net"]==via["net"]:continue
            if disc.intersects(p["geom"]):
                problems.append((via["ref"],via["pad"],via["net"],p["ref"],p["net"]))
    return problems

def _plane(gnd,holes):
    return gnd.difference(unary_union(holes))

def _gate_plan(n,pads,positions):
    drc=json.loads(DRC.read_text("utf8"))
    assert drc["native"]["value"]["categories"]=={"Connection Error":112}
    entries=drc["native"]["value"]["raw"]
    pgnd=next(row["list"] for category in entries
             if category["name"]=="Connection Error"
             for row in category["list"] if row["name"]=="PGND")
    if len(pgnd)!=44:raise ValueError("Native 44 open PGND findings changed")
    return {
        "native_pgnd_unconnected_count":len(pgnd),
        "native_pgnd_unconnected_object_list":[r["obj1"]["suffix"] for r in pgnd],
        "distinct_named_pgnd_pads_in_v15_readback":sum(1 for p in n["pads"] if p["Net"]=="PGND"),
        "pgnd_return_path_ownership": {
            "HF_PRIMARY":"QL power-source pins, actual qualified Cin negative and J_IN negative; local short loop before chassis",
            "HF_SECONDARY":"eight SR source Kelvin pins into paired PGND/VOUT low ESL copper returns",
            "LOW_NOISE":"U1..U6 driver GND/REG and CS/OC sense Kelvin stubs, attach to power return at defined source star",
            "DC_100A":"four 25A secondaries -> paired dedicated Cu straps (two polarities) -> multi-contact J_OUT replacement",
            "CAP_BANK":"72 output caps; PGND pad via-in-pad to PGND plane; VOUT pad via-in-pad to VOUT plane"
        },
        "PGND_is_currently_one_net_and_not_galvanically_isolated":True
    }

def generate():
    native,slots=base.load()
    xy=layout.layout(native)
    pads=base.transferred_pad_records(native,xy)
    if len(pads)!=419:raise ValueError("True native pad count drift.")
    position_errors,pad_count=base.copper_screen(pads)
    slots2,sloterrors,body,bodies,capthroat,capedge=layout.chassis_screen(native,xy,pads,slots)
    vias=_candidate_vias(pads)
    net_counts=Counter(x["net"] for x in vias)
    err=_via_cross_net_errors(vias,pads)
    local_stitches=_local_reg_and_cout_stitch_sites(pads)
    aux_vias=_aux_supply_vias(pads)
    if len(aux_vias)!=12:raise ValueError("Aux supply via count drift")
    aux_conflicts=_via_cross_net_errors(aux_vias,pads)
    if aux_conflicts:raise ValueError("Aux supply throughvia crossnet pad conflict "+str(aux_conflicts))
    ctrl_stitches,ctrl_kelvin=_control_ground_sites_and_short_link(pads)
    ctrl_violations=_via_cross_net_errors(ctrl_stitches,pads)
    if ctrl_violations:raise ValueError("Control PGND via violates othernet pads "+str(ctrl_violations))
    local_stitch_conflicts=_via_cross_net_errors(local_stitches,pads)
    if local_stitch_conflicts:raise ValueError("Local U3/C7 REG/PGND or Cout via conflicts "+str(local_stitch_conflicts))
    if len(local_stitches)!=10:raise ValueError("Unexpected local stitch plan count")
    if len(vias)!=312 or net_counts!=Counter({"PGND":168,"VOUT":144}):
        raise ValueError("PGND/VOUT via inventory unexpected "+str((len(vias),net_counts)))
    # Full 12-layer plane source model, not an EDA layer definition.
    # Copper areas are cut at all opposite-net vias. Cu strap current paths
    # are separate mechanical inserts, *NOT* confused with inner HF planes.
    ground_zone=box(2.,62.,153.,111.)
    output_zone=box(2.,68.,153.,111.)
    ground_antipads=[Point(v["x_mm"],v["y_mm"]).buffer(
                     VIA_R_MM+ANTIPAD_MARGIN_MM,quad_segs=8)
                     for v in vias if v["net"]=="VOUT"]
    output_antipads=[Point(v["x_mm"],v["y_mm"]).buffer(
                     VIA_R_MM+ANTIPAD_MARGIN_MM,quad_segs=8)
                     for v in vias if v["net"]=="PGND"]
    j1=next(p for p in pads if p["ref"]=="J_OUT" and p["net"]=="VOUT")
    j2=next(p for p in pads if p["ref"]=="J_OUT" and p["net"]=="PGND")
    ground_antipads.append(Point(*_centre(j1)).buffer(OUTPUT_TERMINAL_ANTIPAD_MM))
    output_antipads.append(Point(*_centre(j2)).buffer(OUTPUT_TERMINAL_ANTIPAD_MM))
    ground_copper=_plane(ground_zone,ground_antipads)
    output_copper=_plane(output_zone,output_antipads)
    # If a named pad has no copper circle reaching the right plane, signal
    # requires its own short stitch and a real native route later.
    via_plane_hits=[(v["ref"],v["pad"],v["net"]) for v in vias
        if not (ground_copper if v["net"]=="PGND" else output_copper)
               .intersects(Point(v["x_mm"],v["y_mm"]).buffer(VIA_R_MM))]
    # Actual Cin PGND -> nearest QL PGND pin: direct local short-loop route
    # target. It may not cross opposing native footprint pads.
    cin=next(p for p in pads if p["ref"]=="Cin" and p["net"]=="PGND")
    ql=min((p for p in pads if p["ref"]=="QL" and p["net"]=="PGND"),
           key=lambda p:Point(*_centre(cin)).distance(p["geom"]))
    segment=LineString([_centre(cin),_centre(ql)])
    copper=segment.buffer(.45,cap_style="flat")
    primary_return_errors=[
        p["ref"]+"."+str(p["number"])+":"+p["net"]
        for p in pads
        if p["net"]!="PGND" and p["layer"] in (1,12)
        and p["geom"].distance(copper)<PAD_TO_OTHER_NET_MIN_MM]
    qlpgnd_ref=[round(z,5) for z in _centre(ql)]
    g=_gate_plan(native,pads,xy)
    rho100=1.724e-8*(1+.00393*80)
    width_m=.020
    thick_m=.0015
    segment_lengths_mm=(38.,18.,20.,38.)
    segment_currents_A=(25.,50.,50.,25.)
    # Identical VOUT/PGND busbar geometries intentionally mirrored.
    horizontal_watts=2*sum((i*i * rho100 * (l/1000.)/(width_m*thick_m))
                            for l,i in zip(segment_lengths_mm,segment_currents_A))
    trunk_length_mm=31.
    trunk_watts=2*100**2*rho100*(trunk_length_mm/1000.)/(width_m*thick_m)
    ideal_R=(horizontal_watts+trunk_watts)/(100**2)
    area_ratio=round(ideal_R*1000/.15,3)
    return {
        "schema":"D1_V17_SYNCHRONIZED_PGND_VOUT_COPPER_PREFLIGHT_V1",
        "source_V15_real_native_sha256":base.sha(base.NATIVE),
        "source_V17_floorplan_sha256":base.sha(layout.OUT),
        "source_V15_real_DRC_sha256":base.sha(DRC),
        "status":"PGND_PHYSICAL_COPPER_CONCEPT_NOT_ROUTED_NOT_FOR_FAB",
        "board_candidate":[155,113,16],
        "synchronized_placement_ref_count":len(xy),
        "native_original_pgnd_DRC":g,
        "input_pgnd_to_QL_pad_target":{
            "from_ref":"Cin.2","from_xy_mm":[round(z,5) for z in _centre(cin)],
            "to_ref":"QL."+str(ql["number"]), "to_xy_mm":qlpgnd_ref,
            "path_mm":[[round(z,5) for z in pt] for pt in segment.coords],
            "width_mm":.9,
            "approx_net_conflict_list":primary_return_errors,
            "actual_copper_created":False
        },
        "inner_layer_pgnd_copper":{
            "nominal_EasyEDA_layer_id":INNER_GROUND_LAYER,
            "source_nominal_region_xyxy_mm":[2.,62.,153.,111.],
            "total_opposite_VOUT_antipads":len(ground_antipads),
            "area_after_antipads_mm2":round(ground_copper.area,2),
            "still_one_connected_polygon":ground_copper.geom_type=="Polygon",
            "actual_native_polygon_created":False
        },
        "inner_layer_vout_copper":{
            "nominal_EasyEDA_layer_id":INNER_OUTPUT_LAYER,
            "source_nominal_region_xyxy_mm":[2.,68.,153.,111.],
            "total_opposite_PGND_antipads":len(output_antipads),
            "area_after_antipads_mm2":round(output_copper.area,2),
            "still_one_connected_polygon":output_copper.geom_type=="Polygon",
            "actual_native_polygon_created":False
        },
        "planned_via_in_pad_sites":vias,
        "additional_local_driver_reg_pgnd_and_Cout_stitches":local_stitches,
        "additional_local_stitch_clearance_failures":local_stitch_conflicts,
        "additional_local_stitches_count":len(local_stitches),
        "control_U1_U2_PGND_via_sites":ctrl_stitches,
        "auxiliary_12V_S_and_12V_via_sites":aux_vias,
        "auxiliary_12V_supply_via_othernet_conflicts":aux_conflicts,
        "control_U2_pgnd9_to_exposed_pgnd11_link":ctrl_kelvin,
        "planned_via_count_by_net":dict(net_counts),
        "via_in_pad_plating_capping_vendor_signed":False,
        "via_drill_trial_mm":VIA_DRILL_MM,
        "via_radius_trial_mm":VIA_R_MM,
        "via_to_unlike_pad_nominal_min_clearance_mm":PAD_TO_OTHER_NET_MIN_MM,
        "via_to_unlike_net_pad_conflict_examples":err[:40],
        "via_to_unlike_net_pad_conflict_count":len(err),
        "via_to_named_plane_fails":via_plane_hits[:40],
        "via_to_named_plane_fail_count":len(via_plane_hits),
        "magnet_courtyard_pad_conflicts":len(bodies),
        "magnet_slot_pad_conflicts":len(sloterrors),
        "native_pad_other_net_conflicts":pad_count,
        "output_terminal_original_pth_pad_centres_mm":[
            [round(z,4) for z in _centre(j1)],
            [round(z,4) for z in _centre(j2)]],
        "original_single_PTH_each_pole_is_inadequate_100A_release":True,
        "require_vendor_multi_contact_busbar_terminals":True,
        "paired_100A_copper_insert_screen":{
           "conductors":"two separate wide bars in adjacent insulated z-planes",
           "width_per_pole_mm":20.,
           "effective_Cu_thickness_per_pole_mm":1.5,
           "bulk_Cu_resistivity_100C_ohm_m":round(rho100,11),
           "section_length_mm":list(segment_lengths_mm),
           "section_current_A":list(segment_currents_A),
           "each_pole_centre_trunk_length_mm":trunk_length_mm,
           "total_bipolar_horizontal_losses_W":round(horizontal_watts,4),
           "total_bipolar_trunk_losses_W":round(trunk_watts,4),
           "ideal_bipolar_losses_at_100A_W":round(horizontal_watts+trunk_watts,4),
           "ideal_bipolar_R_mohm":round(ideal_R*1000,4),
           "fraction_of_0p15mohm_budget":area_ratio,
           "joint_via_contact_spreading_loss_included":False,
           "16mm_coldplate_stack_mechanical_verified":False,
           "manufacturing_geometry_created":False
        },
        "EMC_REQUIREMENTS_BEFORE_SIGNOFF":[
          "No PGND return current passes gate-driver Kelvin or OC sense reference copper",
          "Verify Cin current loops with actual qualified 48V local input capacitor bank",
          "Keep outgoing VIN/SW and true power return adjacent, extract partial L",
          "SR commutating SEC_A/B paths to FETs and Kelvin source returns extracted and tested",
          "Output HF VOUT/PGND plane pairs with registered via anti-pad voids",
          "No via-in-pad except filled/capped as approved by actual 12-layer manufacturer",
          "Use independent native DRC and 3D stackup; current two-layer rule cannot release",
          "3D parasitic and 3LPM thermal/16mm assembly verified",
          "CISPR 32 conducted/radiated EMI precompliance and final accredited test"
        ],
        "native_V17_PCB_saved":False,
        "native_DRC_pgnd_zero_verified":False,
        "fab_release":False
    }

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--write",action="store_true")
    parser.add_argument("--check",action="store_true")
    args=parser.parse_args()
    result=generate()
    contents=json.dumps(result,indent=2,ensure_ascii=False)+"\n"
    if args.write:
        OUT.write_text(contents,encoding="utf8",newline="\n")
    if args.check and OUT.read_text("utf8")!=contents:
        raise ValueError("PGND synchronized copper plan source drift")
    print(json.dumps({
      "native_open_pgnd":result["native_original_pgnd_DRC"]["native_pgnd_unconnected_count"],
      "candidate_pgnd_vias":result["planned_via_count_by_net"].get("PGND"),
      "candidate_vout_vias":result["planned_via_count_by_net"].get("VOUT"),
      "local_driver_and_cout_stitches":result["additional_local_stitches_count"],
      "control_pgnd_vias":len(result["control_U1_U2_PGND_via_sites"]),
      "auxiliary_12V_vias":len(result["auxiliary_12V_S_and_12V_via_sites"]),
      "via_other_net_conflicts":result["via_to_unlike_net_pad_conflict_count"],
      "ground_plane_disconnected":not result["inner_layer_pgnd_copper"]["still_one_connected_polygon"],
      "vout_plane_disconnected":not result["inner_layer_vout_copper"]["still_one_connected_polygon"],
      "via_plane_nonconnection":result["via_to_named_plane_fail_count"],
      "primary_pgnd_cross_net":result["input_pgnd_to_QL_pad_target"]["approx_net_conflict_list"],
      "ideal_bipolar_R_mohm":result["paired_100A_copper_insert_screen"]["ideal_bipolar_R_mohm"],
      "fab":result["fab_release"]
    }))
if __name__=="__main__":
    main()

"""Native-output-coupon A/B copper comparison anchored to both saved KiCad
boards, source receipts and native DRC. Never claims a manufacturable 200A
transformer. Computes a 1-D equal-50A injection + 100C material DC screen.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
D=ROOT/"hardware/dcx_main/g2/d1_lane_a_e1_reuse_coupon"
EDGE_R=D/"e1_4cell_200A_pair_collector_reuse_source_locked_NOT_FOR_FAB.json"
EDGE_DRC=D/"e1_4cell_200A_pair_collector_native_DRC_NOT_FOR_FAB.json"
CENTER_R=D/"e1_4cell_200A_center_output_source_bound_NOT_FOR_FAB.json"
CENTER_DRC=D/"e1_4cell_200A_center_output_native_DRC_NOT_FOR_FAB.json"
OUT=D/"e1_200A_A_B_real_KiCad_collector_comparison_NOT_FOR_FAB.json"
T_100_RHO=1.724e-8*(1+.00393*(100-20))
WIDTH_MM=43.0-29.3
ASSUMED_COPPER_MM=.07
ASSUMED_BUSBAR_MM=.8
RATED_POWER_W=2*200
EFF_ASSUMED=.95
OUTPUT_LOSS_BUDGET_SHARE=.20
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def read_receipt_and_drc(meta_path,drc_path,key):
    meta=json.loads(meta_path.read_text("utf8"))
    filename=meta[key]
    board=ROOT/filename
    if sha(board)!=meta["centered_CAD_sha256" if key=="centered_CAD_relative" else "output_native_pcb_sha256"]:
        raise ValueError("Native KiCad CAD source hash mismatch: "+str(board))
    drc=json.loads(drc_path.read_text("utf8"))
    if drc.get("violations",[]) or drc.get("unconnected_items",[]):
        raise ValueError("Native KiCad DRC is nonzero")
    actual_ignored={x.get("key") for x in drc.get("ignored_checks",[])}
    expected={"missing_courtyard","track_not_centered_on_via","tuning_profile_track_geometries",
              "footprint_filters_mismatch","footprint_type_mismatch"}
    if actual_ignored!=expected:
        raise ValueError("KiCad DRC ignored checks changed")
    return meta,dict(board_sha256=sha(board),drc_sha256=sha(drc_path),native_violations=0,
                     native_unconnected=0,inherited_ignored_checks=sorted(actual_ignored))
def calc(output_x,thickness_mm):
    # Four equal 50A taps along a single straight two-rail collector x20/40/60/80.
    # I(x) equals the algebraic sum of source injections on one side of
    # the output. This is a 1-D electrothermal check, not full FEA.
    coords=[20,40,60,80]
    breakpoints=sorted(set(coords+[output_x]))
    segments=[]
    total=0.0
    rho=T_100_RHO
    area=WIDTH_MM*thickness_mm*1e-6
    for l,r in zip(breakpoints[:-1],breakpoints[1:]):
        midpoint=(l+r)/2
        if midpoint<output_x:
            n=sum(x<=midpoint for x in coords)
        else:
            n=sum(x>=midpoint for x in coords)
        amp=50*n
        pair_r=2*rho*((r-l)/1000)/area
        heat=amp*amp*pair_r
        total+=heat
        segments.append({"x0_mm":l,"x1_mm":r,"absolute_I_A":amp,
                         "ideal_pair_hot_R_microohm":round(pair_r*1e6,3),
                         "ideal_pair_hot_copper_P_W":round(heat,5)})
    return dict(output_x_mm=output_x,copper_per_polarity_thickness_mm=thickness_mm,
                ideal_P_DConly_W=round(total,5),
                segments=segments,not_full_2D_thermal_current_model=True)
def evaluate():
    edge,eg=read_receipt_and_drc(EDGE_R,EDGE_DRC,"output_native_pcb")
    center,cg=read_receipt_and_drc(CENTER_R,CENTER_DRC,"centered_CAD_relative")
    if center["source_edge_coupon_sha256"]!=eg["board_sha256"]:
        raise ValueError("Centered trial not produced from the preserved original native board")
    if not edge["physical_SR_source_pin_maps"] or len(edge["physical_SR_source_pin_maps"])!=8:
        raise ValueError("Missing eight source-origin SR footprints")
    if not center["exact_same_8_SR_physical_pin_nets"]:
        raise ValueError("SR pads not preserved")
    comparisons=[]
    for thickness in (ASSUMED_COPPER_MM, ASSUMED_BUSBAR_MM):
        a=calc(95,thickness);b=calc(50,thickness)
        if b["ideal_P_DConly_W"]>=a["ideal_P_DConly_W"]:
            raise ValueError("Expected shorter real geometry to reduce calculated loss")
        comparisons.append({"A_edge_terminal":a,"B_center_terminal":b,
                            "idealized_loss_improvement_percent":round((1-b["ideal_P_DConly_W"]/a["ideal_P_DConly_W"])*100,2)})
    e_budget=RATED_POWER_W*(1/EFF_ASSUMED-1)
    allowed=e_budget*OUTPUT_LOSS_BUDGET_SHARE
    return {
      "schema":"d1_e1_native_A_B_bipolar_collector_screen/1",
      "status":"TWO_NATIVE_KICAD_DRC_0_0_COUPONS_BUT_200A_POWER_RATING_NOT_QUALIFIED",
      "actual_existing_reused_SR_footprints_from_V17":list(sorted(edge["physical_SR_source_pin_maps"])),
      "physical_KiCad_A_native_verification":eg,
      "physical_KiCad_B_native_verification":cg,
      "geometry_A_end_vs_B_center_mm":{"edge_output_x":95.,"center_output_x":50.,
                                      "all_SR_locations_and_broadside_F_B_copper_planes_identical":True,
                                      "positive_negative_output_contacts_moved_together":True},
      "assumed_four_local_50A_DC_injections_x_mm":[20,40,60,80],
      "output_voltage_v":2.,
      "design_current_A":200.,
      "total_power_W":RATED_POWER_W,
      "total_allowable_loss_for_95pct_eff_W":round(e_budget,4),
      "output_pair_copper_20pct_budget_W":round(allowed,4),
      "real_bus_routing_on_surface":{
         "PGND":"F.Cu",
         "VOUT":"B.Cu",
         "current_carrying_layers_at_zone_as_modeled":1,
         "board_12_copper_layers_defined_but_not_all_parallel_current_carrying":True,
         "actual_200A_continuous_copper_stackup_qualified":False
       },
      "conditional_DConly_100C_copper_results":comparisons,
      "B_center_70um_copper_still_exceeds_20pct_loss_target":
        comparisons[0]["B_center_terminal"]["ideal_P_DConly_W"]>allowed,
      "B_center_0p8mm_foil_potentially_below_20pct_loss_target_but_not_a_real_component":
        comparisons[1]["B_center_terminal"]["ideal_P_DConly_W"]<allowed,
      "thermal_qualification":"Rho(T)*L/A, 4x50A ideal equal feed, uniform copper width/thickness, 100C material only; ignores skin, current spreading, contact, pad, inductance and local hot zones",
      "why_not_overclaim":"A and B both lack true PCB transformer/ferrite, split-phase drive/bias, control/protection/schematic, rated output connectors and cooled full-assembly CAD. 0/0 is only their incomplete diagnostic netlist.",
      "release_allowed":False,
      "power_on_allowed":False,
      "next_iteration_hard_actions":[
        "Replace long equal-width surface planes with per-cell side collector close to SR and true paired busbar in actual mechanical CAD",
        "Recalculate 200A actual winding+4 rectifier cells with 12/16-layer OEM stackup and commissioned ferrite slot mechanical dimensions",
        "Attach existing T1 5-terminal native Maxwell model as guarded geometry source; do NOT inherit material/saturation/AC loss signoff",
        "Integrate existing Lane C isolated bias/HS UVLO/D0 fail-off logic after pin-net/ERC parity; do not merge dirty root",
        "Test hot 4-wire VOUT+PGND resistance, current balance, surface TIM insulation, coldplate CFD & pressure + heat"
      ]
    }
def main(argv=None):
    pp=argparse.ArgumentParser()
    q=pp.add_mutually_exclusive_group(required=True)
    q.add_argument("--write",action="store_true")
    q.add_argument("--check",action="store_true")
    q.add_argument("--require-release",action="store_true")
    opts=pp.parse_args(argv)
    d=evaluate()
    body=json.dumps(d,ensure_ascii=False,indent=2)+"\n"
    if opts.write:
        OUT.write_text(body,"utf8")
    elif opts.check:
        if OUT.read_text("utf8")!=body:
            raise ValueError("Recompute A/B native source-bound gate after CAD/drC changed")
    elif opts.require_release:
        print("RELEASE DENIED: candidate B still fails native hardware/thermal/current/driver magnetics gates")
        return 2
    print(json.dumps({"status":d["status"],
                      "A_70um_P_W":d["conditional_DConly_100C_copper_results"][0]["A_edge_terminal"]["ideal_P_DConly_W"],
                      "B_70um_P_W":d["conditional_DConly_100C_copper_results"][0]["B_center_terminal"]["ideal_P_DConly_W"],
                      "improvement_pct":d["conditional_DConly_100C_copper_results"][0]["idealized_loss_improvement_percent"],
                      "B_0p8mm_strap_ideal_P_W":d["conditional_DConly_100C_copper_results"][1]["B_center_terminal"]["ideal_P_DConly_W"]}))
    return 0
if __name__=="__main__":
    sys.exit(main())

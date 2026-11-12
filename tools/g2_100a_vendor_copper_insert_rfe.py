"""Source-locked machine-readable engineering inquiry for 100A copper insert supplier.

NOT A FAB QUOTE ORDER. Real PCB power pin locations from V9 native GUI are
included; contact/insulation/stackup/screw/magnetics are intentionally open.
Supplier must propose a signable mechanical/electrical construction first.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
G2=ROOT/"hardware/dcx_main/g2"
sys.path.insert(0,str(ROOT/"tools"))
import g2_v9_100a_copper_pillar_screen as VIA
import g2_v9_bipolar_mechanical_gate as PHYS

OUT=ROOT/"hardware/dcx_main/manufacturing/d1_100a_two_pole_copper_insert_rfe_NOT_FOR_FAB.json"


def build():
    v=VIA.report()
    p=PHYS.report()
    if v["source_native_sha256"]!=p["source_native_sha256"]:
        raise ValueError("Mechanical/electrical CAD source mismatch")
    anchors=p["contact_anchors"]
    if len(anchors["CTAP"])!=4 or len(anchors["SR_SOURCE"])!=16:
        raise ValueError("Native power interface inventory drift")
    # 16 SR.3 copper footprints are 2 physical lands per actual SR package;
    # 8 separate SR branches, not 16 independent power current sources.
    return {
       "schema":"D1_100A_BIPOLAR_EMBEDDED_COPPER_COIN_VENDOR_ENGINEERING_REQUEST_V1",
       "package_state":"FOR_VENDOR_DESIGN_AND_DFM_QUOTE_NOT_FOR_FAB",
       "native_parent_board":"G2_V9_REAL_72_DEVICE",
       "native_board_sha256":v["source_native_sha256"],
       "project":"48V_to_2V_fixed_ratio_D1",
       "electrical_target":{"vin_nominal_V":48,"vout_nominal_V":2,
           "continuous_output_total_A":100,
           "vout_and_return_poles":["VOUT","PGND"],
           "ideal_transformer_CTAP_branch_A":25,
           "ideal_synchronous_rectifier_branch_A":12.5,
           "equal_current_sharing_NOT_YET_PROVEN":True,
           "allowed_interconnect_hotspot_K":"VENDOR_PROPOSE_AND_MEASURE",
           "metal_contact_four_wire_microohm":"VENDOR_SPECIFY_AND_MEASURE",
           "current_derating_high_ambient":"VENDOR_SPECIFY"},
       "mechanical_target":{
           "board_XY_nominal_mm":[155,131],
           "board_outline_independently_measured":False,
           "complete_assembly_height_limit_mm":16.,
           "bare_1p2mm_bar_old_trial_height_without_TIM_clamp_mm":15.45,
           "old_trial_with_assumed_TIM_clamp_and_tolerance_mm":16.45,
           "old_trial_exceeds_height":True,
           "interface_to_cold_plate_and_clamping":"VENDOR_CO_DESIGN_REQUIRED",
           "actual_magnetics_terminal_3D_and_DOT":"NOT_SIGNED",
           "top_to_bottom_contact_method":"VENDOR_PROPOSE_EMBEDDED_COIN_OR_COPPER_PILLAR",
           "fastener_location_and_thread":"NOT_DESIGNED_MUST_AVOID_NATIVE_COPPER",
           "insulation_dielectric_and_creepage":"NOT_QUALIFIED"},
       "original_real_native_terminals":{
           "CTAP":anchors["CTAP"],"SR_source_lands":anchors["SR_SOURCE"],
           "magnetics_24_placeholder_pad_reference":"g2_v9_p1_magnetic_terminal_gap_NOT_FOR_FAB.json",
           "component_owned_magnetic_terminal_land":False},
       "why_ordinary_small_via_array_not_accepted":{
           "method":"1.0mm OD / 0.4mm hole, 1.6mm pitch; all native unlike-net and top existing connection geometry screened",
           "plating_mm_assumed":v["assumed_via_plating_mm"],
           "limited_top_contact_candidate_count_VOUT":v["results"]["VOUT"]["candidate_count"],
           "limited_top_contact_candidate_count_PGND":v["results"]["PGND"]["candidate_count"],
           "hypothetical_via_loss_budget_per_pole_w":v["hypothetical_100C_via_only_loss_budget_per_pole_W"],
           "required_VOUT_at_100C_ideal_only":v["results"]["VOUT"]["target_contact_sites_for_one_hypothetical_via_strategy"],
           "required_PGND_at_100C_ideal_only":v["results"]["PGND"]["target_contact_sites_for_one_hypothetical_via_strategy"],
           "current_copper_insufficient_to_native_layout_target":True},
       "old_busbar_clearance_screen":{
           "VOUT_opposite_net_vias_needing_isolation":len(p["opposite_net_native_vias_needing_bottom_bar_insulation"]["VOUT"]),
           "PGND_opposite_net_vias_needing_isolation":len(p["opposite_net_native_vias_needing_bottom_bar_insulation"]["PGND"]),
           "legacy_bar_not_a_valid_manufacturing_solid":True},
       "supplier_required_outputs":[
            "Signed PCB native land/pad-number/DOT drawing for T1-T4 and CT with toleranced 3D package envelope",
            "Copper coin, pillar or stamped power-strap geometry with actual VOUT/PGND isolated mechanical contacts, including annotated source and terminal pad map",
            "PCB stackup, local cavity/recess, drill/fill/plating processes and IPC accept/reject dimensional tolerances",
            "Two-pole separation, surface contamination/ionics, dielectric/creepage, underside insulation and cold-plate isolation drawing",
            "Full worst-case 16mm Z-stack including magnetics, standoff, clamp, TIM, tolerance and deflection",
            "Continuously-rated 100A current/thermal simulation with unequal branch currents and contact resistance distribution",
            "Fabrication-compatible step/2D CAD, Gerbers, drill/PTH and assembly drawings after approved native PCB revision",
            "Four-wire contact resistance test points, 100A steady state thermal test method and pass thresholds agreed before order",
            "DFM objections, approval revisions and written acknowledgement of not-for-fabrication until corrected"
       ],
       "manufacturer_rfq_ready_to_send_for_engineering_review":True,
       "fabrication_files_ready_to_send":False,
       "vendor_signature_recorded":False,
       "native_cad_output_bar_contact_created":False,
       "actual_100a_cold_plate_test_passed":False,
       "hardware_safety_D0_10channel_shutdown_passed":False,
       "design_and_fab_approved":False
    }


def main():
    p=argparse.ArgumentParser()
    g=p.add_mutually_exclusive_group(required=True)
    g.add_argument("--write",action="store_true")
    g.add_argument("--check",action="store_true")
    a=p.parse_args()
    body=json.dumps(build(),ensure_ascii=False,indent=2)+"\n"
    if a.write:OUT.write_text(body,encoding="utf8",newline="\n")
    elif not OUT.exists() or OUT.read_text("utf8")!=body:
        raise ValueError("Native 100A vendor engineering RFE stale")
    print(json.dumps({"rfe":str(OUT.relative_to(ROOT)),
             "native_source_sha256":build()["native_board_sha256"],
             "vendor_DFM_requested":True,"fabrication_approved":False},indent=2))
if __name__=="__main__":
    main()

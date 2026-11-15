"""Evidence gate for the E1 200A design-intent collector coupon.

Reads the actual KiCad output, the saved KiCad native DRC, its real parent
footprints and the preexisting PCB-embedded ELP38 Lr demonstrator.
The DRC 0/0 is only for the COPPER TEST COUPON. It intentionally REJECTS any
claim that the copper is 200A continuous rated or a functioning 48V/2V DCX.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
p=ROOT/"hardware/dcx_main/g2/d1_lane_a_e1_reuse_coupon"
FINGERPRINT=p/"e1_4cell_200A_pair_collector_reuse_source_locked_NOT_FOR_FAB.json"
BOARD=p/"e1_4cell_200A_pair_collector_copper_coldplate_interface_NOT_FOR_FAB.kicad_pcb"
DRC=p/"e1_4cell_200A_pair_collector_native_DRC_NOT_FOR_FAB.json"
OUT=p/"e1_4cell_200A_pair_collector_electrical_gate_NOT_FOR_FAB.json"
RHO20=1.724e-8
CU_ALPHA=.00393
TEMP_C=100.0
ASSUMED_CU_THICKNESS_UM=70.
BUSBAR_IDEAL_THICKNESS_MM=.8
ZONE_WIDTH_MM=43-29.3
REFERENCE_OUTPUT_A=200.
CELL_INCREMENT_A=50.
ETA_BENCHMARK=.95

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def ohmic_piecewise(thickness_mm):
    """Ideal isothermal 1D two-rail fully-equal 4x50A incremental collector.
    The *actual* 2D pad/zone geometry is more complex and can only add/
    redistribute loss; this simplified loss is diagnostic, not FEM.
    """
    width_m=ZONE_WIDTH_MM*.001
    thick_m=thickness_mm*.001
    rho_hot=RHO20*(1+CU_ALPHA*(TEMP_C-20))
    intervals=[(20,40,50.),(40,60,100.),(60,80,150.),(80,95,200.)]
    losses=[]
    for x0,x1,amp in intervals:
        r_per_rail=rho_hot*(x1-x0)*.001/(width_m*thick_m)
        losses.append({"segment_from_x_mm":x0,"to_x_mm":x1,
                       "conditional_current_a":amp,
                       "ideal_pair_R_microohm":round(2*r_per_rail*1e6,3),
                       "ideal_pair_P_w":round(2*r_per_rail*amp*amp,3)})
    return {
      "copper_thickness_assumed_per_polarity_mm":thickness_mm,
      "width_assumed_mm":ZONE_WIDTH_MM,
      "material_temperature_c":TEMP_C,
      "all_4_cells_50A_each_same_direction":True,
      "approximate_equal_cell_incremental_current_assumption":True,
      "ideal_loss_w_two_polarities":round(sum(z["ideal_pair_P_w"] for z in losses),3),
      "intervals":losses,
      "pad_and_contact_spreading_AC_losses_included":False,
      "actual_2D_power_copper_field_solved":False
    }
def make():
    import pcbnew as k
    if not FINGERPRINT.exists() or not BOARD.exists() or not DRC.exists():
        raise ValueError("Expected native coupon + native DRC missing")
    meta=json.loads(FINGERPRINT.read_text("utf8"))
    if sha(BOARD)!=meta["output_native_pcb_sha256"]:
        raise ValueError("Native KiCad PCB modified without rechecking DRC and SHA")
    r=json.loads(DRC.read_text("utf8"))
    violations=r.get("violations",[])
    unrouted=r.get("unconnected_items",[])
    if violations or unrouted:
        raise ValueError(f"Native E1 coupon DRC not clean: {len(violations)} rules / {len(unrouted)} unconnected")
    existing_ignored={x.get("key") for x in r.get("ignored_checks",[])}
    expected_ignored={"missing_courtyard","track_not_centered_on_via","tuning_profile_track_geometries",
                      "footprint_filters_mismatch","footprint_type_mismatch"}
    if existing_ignored!=expected_ignored:
        raise ValueError(f"Native KiCad inherited ignored-check policy drift: {sorted(existing_ignored)}")
    b=k.LoadBoard(str(BOARD))
    if b.GetCopperLayerCount()!=12 or len(b.GetFootprints())!=22:
        raise ValueError("Actual KiCad layer/footprint count changed")
    pads={}
    for f in b.GetFootprints():
        if f.GetReference() in meta["physical_SR_source_pin_maps"]:
            vv=sorted((x.GetNumber(),x.GetNetname()) for x in f.Pads())
            if vv!=[tuple(x) for x in meta["physical_SR_source_pin_maps"][f.GetReference()]]:
                raise ValueError("Source-origin SR pin/net parity broken: "+f.GetReference())
        pads[f.GetReference()]=[(q.GetNumber(),q.GetNetname(),
                                   "F.Cu" if q.IsOnLayer(k.F_Cu) and not q.IsOnLayer(k.B_Cu) else
                                   "B.Cu" if q.IsOnLayer(k.B_Cu) and not q.IsOnLayer(k.F_Cu) else "MULTILAYER")
                                  for q in f.Pads()]
    sr_names=set(meta["physical_SR_source_pin_maps"])
    if sr_names!={f"SR{i}{c}" for i in range(1,5) for c in ("A","B")}:
        raise ValueError("Four real SR pairs must be present")
    # Zone.GetLayerName() is not board-aware on this KiCad Python version;
    # use exact numeric layer membership instead (B.Cu is layer enum 2).
    zones={("F.Cu" if z.GetLayer()==k.F_Cu else
            "B.Cu" if z.GetLayer()==k.B_Cu else "OTHER",z.GetNetname()) for z in b.Zones()}
    if ("F.Cu","PGND") not in zones or ("B.Cu","VOUT") not in zones:
        raise ValueError("Physical paired return/positive planes absent")
    for ref,layer,net in (("OUT_POS","B.Cu","VOUT"),("OUT_NEG","F.Cu","PGND")):
        if ref not in pads or pads[ref][0][1]!=net or pads[ref][0][2]!=layer:
            raise ValueError("Wrong opposite surface output terminal network/layer")
    for i in range(1,5):
        if f"CTAP_{i}" not in pads or pads[f"CTAP_{i}"][0][1]!="VOUT":
            raise ValueError("Physical center-tap proxy landing missing")
    copper=ohmic_piecewise(ASSUMED_CU_THICKNESS_UM/1000)
    strap=ohmic_piecewise(BUSBAR_IDEAL_THICKNESS_MM)
    max_loss=2*REFERENCE_OUTPUT_A*(1/ETA_BENCHMARK-1)
    if not (copper["ideal_loss_w_two_polarities"]>max_loss and strap["ideal_loss_w_two_polarities"]<max_loss):
        raise ValueError("Loss assumption/design-intent budget equation drift")
    return {
        "schema":"d1_e1_reuse_coupon_gate/1",
        "status":"NATIVE_E1_COUPON_PASS_BUT_200A_CURRENT_RATING_FAILS_DC_SCREEN_NOT_FOR_FAB",
        "physical_kicad_source":meta["output_native_pcb"],
        "physical_kicad_sha256":sha(BOARD),
        "native_drc_sha256":sha(DRC),
        "actual_native_drc_report_violations":len(violations),
        "actual_native_drc_report_unconnected":len(unrouted),
        "inherited_five_native_ignored_check_types_not_claimed_full_manufacturing_DRC":sorted(existing_ignored),
        "native_board_12_layers_and_22_footprints_confirmed":True,
        "eight_V17_SR_real_physical_pin_maps_preserved":True,
        "paired_FCu_PGND_BCu_VOUT_actual_copper_zones":sorted([list(q) for q in zones]),
        "output_pair_surface_contacts_validated":True,
        "nominal_4x50A_cells_and_no_actual_windings":True,
        "200A_95pct_efficiency_total_loss_budget_w":round(max_loss,3),
        "hypothetical_70um_two_polarity_collector_dc_loss":copper,
        "hypothetical_0p8mm_TWO_bonded_copper_straps_dc_loss":strap,
        "80percent_of_total_loss_is_other_blocks_reserve_required":True,
        "output_copper_fails_200A_continuous_design_requirement":True,
        "external_straps_real_CAD_and_factory_solder_metal_current_rating_verified":False,
        "MAXWELL_actual_per_layer_AC_loss_completed":False,
        "manufacturer_12Cu_stackup_thermal_and_solder_verified":False,
        "coldplate_fluid_CFD_done":False,
        "complete_primary_magnetics_24to1_CT_protection_available":False,
        "fabrication_allowed":False,
        "energization_allowed":False,
        "recommendation":"Stop this long 4x50A edge-collector as final high-current layout; shorten per-cell output path to few mm and integrate low-resistance positive/negative side metal + ferrite/side SR/coldplate; treat this CAD as reusable geometric/DRC/control A/B measurement coupon only.",
        "reusable_model_sources":{
            "V17_KiCad_12layer_SRs":meta["source_reusable_V17_sha256"],
            "ELP38_6layer_4vias_rounded_window_copper":meta["source_reusable_ELP38_4via_sha256"],
            "external_root_T1_native_fem_partial_sha_canonical":"9692cf53bdd1e30f5c29bf18baed8c8abc69afff65858a141f7db2655b8d62ba",
            "external_root_T1_saturation_stop_sha_canonical":"a614dca727edc8f0ee4194b862a7110915866a162791bda3ab7fde9c2f79d49c",
            "external_root_CT_real_100turn_partial_sha_canonical":"abca015781fdb85910c6ea5451cd6ba2a7263568b8f2647ef0bcbefefdb800b3"
        },
        "external_root_results_checked_read_only_not_imported_to_branch":True
    }
def main(argv=None):
    pp=argparse.ArgumentParser()
    g=pp.add_mutually_exclusive_group(required=True)
    g.add_argument("--write",action="store_true")
    g.add_argument("--check",action="store_true")
    g.add_argument("--require-release",action="store_true")
    aa=pp.parse_args(argv)
    info=make()
    body=json.dumps(info,indent=2,ensure_ascii=False)+"\n"
    if aa.write:OUT.write_text(body,"utf8")
    elif aa.check:
        if OUT.read_text("utf8")!=body:
            raise ValueError("Coupon source-bound report stale")
    elif aa.require_release:
        print("E1 COUPON RELEASE DENIED: not 200A current qualified or complete power converter")
        return 2
    print(json.dumps({"status":info["status"],"DRC":[info["actual_native_drc_report_violations"],info["actual_native_drc_report_unconnected"]],
                      "copper_70um_pair_loss_w":info["hypothetical_70um_two_polarity_collector_dc_loss"]["ideal_loss_w_two_polarities"],
                      "ideal_0p8mm_strap_pair_loss_w":info["hypothetical_0p8mm_TWO_bonded_copper_straps_dc_loss"]["ideal_loss_w_two_polarities"]}))
    return 0
if __name__=="__main__":
    sys.exit(main())

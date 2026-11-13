"""D1 magnetic core *physical-release* decision gate from canonical project data.

A high fault-current screen is NOT the same as the existing 104.17A
transient-coupled design check. A 1A generic-material Maxwell solve is
not N97 100C nonlinear L(I), even if its mesh is numerically converged.

    python tools/d1_magnetic_core_release_gate.py --write
    python tools/d1_magnetic_core_release_gate.py --check

No EDA/CAD mutation and no factory-release permission.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "design/v3"
LR = SOURCE / "bom/lr_design.json"
MAG = SOURCE / "magnetics/magnetics_design.json"
CAT = SOURCE / "power_priority/lr_tdk_catalog_core_source.json"
POLICY = SOURCE / "power_priority/d1_staged_target_policy.json"
CONTRACT = SOURCE / "maxwell/elp38_lr_maxwell_contract.json"
CT = SOURCE / "bom/ct_design.json"
OUT = ROOT / "hardware/dcx_main/manufacturing/d1_magnetic_hotbias_and_Z_release_gate_NOT_FOR_FAB.json"
MU0 = 4*math.pi*1e-7


def _load(path: Path) -> dict:
    return json.loads(path.read_text("utf8"))


def _hash(path: Path) -> str:
    """Source-lock using canonical LF so Windows default CRLF is stable."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _r(x: float, places=5) -> float:
    return round(float(x), places)


def gap_analytic_mm(turns: int, L_uH: float, ae_mm2: float, al_nH: float) -> float:
    # Reluctance approximation; neglects airgap fringing, nonlinear mu and
    # split gap. Never pass a machined airgap as qualified from this expression.
    L = L_uH*1e-6
    L0 = turns**2*al_nH*1e-9
    return 1e3*MU0*turns**2*ae_mm2*1e-6*(1/L-1/L0)


def b_linear_t(L_uH: float, current_a: float, turns: int, amin_mm2: float) -> float:
    return (L_uH*1e-6*current_a)/(turns*amin_mm2*1e-6)


def build() -> dict:
    lr,mag,cat,policy,contract,ct = (_load(p) for p in (LR,MAG,CAT,POLICY,CONTRACT,CT))
    d1 = next(s for s in policy["stages"] if s["id"]=="D1_100A")
    core = next(c for c in cat["cores"] if c["id"]=="ELP38_I38")
    if d1["preferred_magnetic_core"]!=core["id"] or d1["height_limit_mm"]!=16:
        raise ValueError("D1 magnetic core/height baseline changed; require explicit review")
    if core["material"]!="N97" or core["amin_mm2"]!=192 or core["ae_mm2"]!=194:
        raise ValueError("The intended EILP38 N97 catalogue is not the reviewed core")
    if core["al_ungapped_nh"]!=8400 or core["gapping_constants_published_for"]!=["N87"]:
        raise ValueError("Do not silently assume N97 OEM airgap empirical constants")
    design = next(c for c in lr["catalogue_cores"]["cores"] if c["id"]==core["id"])
    if design["amin_mm2"]!=core["amin_mm2"] or design["al_ungapped_nh"]!=core["al_ungapped_nh"]:
        raise ValueError("Lr catalogue and design source disagree")
    stack = {row["id"]:row for row in mag["catalogue_core_stack"]["cores"]}
    if stack["ELP38_I38"]["d1_budget_left_for_tim_cold_plate_fasteners_mm"]!=3.51:
        raise ValueError("The clamping/TIM/coldplate assembly allowance has changed")
    target_total = lr["tank"]["total_target_h"]*1e6
    leakage = lr["tank"]["leakage_model_h"]*1e6
    target_external = lr["tank"]["external_target_h"]*1e6
    if abs(target_total-target_external-leakage)>1e-10:
        raise ValueError("Lr resonant-total and external targets are inconsistent")
    max_current = max(contract["solved_currents_a"])
    source_limit = cat["requirements"]["magnetic_b_limit_t"]
    if max_current!=121.515 or source_limit!=.248:
        raise ValueError("Published project high-current RFQ/screen contract changed")
    bsat = core["bsat_mt_100c"]*1e-3
    if bsat!=.31:
        raise ValueError("N97 nominal 100C saturation catalogue estimate changed")
    catalogue_rows=[]
    for k in cat["cores"]:
        z=stack[k["id"]]
        B = b_linear_t(target_external,max_current,2,k["amin_mm2"])
        margin = z["d1_budget_left_for_tim_cold_plate_fasteners_mm"]
        catalogue_rows.append({
           "id":k["id"],"name":k["core"]+" + "+k["plate"],
           "Amin_mm2":k["amin_mm2"],"two_turn_B_at_max_Rfq_T":_r(B,6),
           "passes_0p248T_arithmetic":B<=source_limit,
           "known_worst_stack_mm":z["stack_flat_no_clamp_worst_mm"],
           "remaining_Z_for_TIM_coldplate_screws_mm":margin,
           "passes_assumed_2mm_remaining_Z":z["d1_clears_the_non_core_reserve"],
           "passes_joint_fault_flux_and_Z_reserve":B<=source_limit and z["d1_clears_the_non_core_reserve"],
           "oem_hotbias_verified":False
        })
    if any(z["passes_joint_fault_flux_and_Z_reserve"] for z in catalogue_rows):
        raise ValueError("New safe catalog core found; re-evaluate released route")
    cases=[]
    for turns in (2,3):
        for value in (target_external,1.0):
            airgap=gap_analytic_mm(turns,value,core["ae_mm2"],core["al_ungapped_nh"])
            current_B=b_linear_t(value,max_current,turns,core["amin_mm2"])
            cases.append({
               "turns":turns,"target_Lr_uH":_r(value,5),
               "reluctance_estimated_total_airgap_mm":_r(airgap,5),
               "inside_TDK_N87_empirical_example_range_NOT_an_N97_proof":
                   core["gapping_validity_s_mm"][0]<airgap<core["gapping_validity_s_mm"][1],
               "linear_B_at_121p515A_T":_r(current_B,6),
               "passes_optional_conservative_80pct_Bsat":current_B<=source_limit,
               "passes_existing_design_90pct_Bsat":current_B<=.9*bsat,
               "N97_100C_nonlin_BH_highbias_verified":False,
               "physical_machined_gap_verified":False
            })
    nominal=next(x for x in cases if x["turns"]==2 and math.isclose(x["target_Lr_uH"],target_external,abs_tol=1e-9))
    nominal_1u=next(x for x in cases if x["turns"]==2 and x["target_Lr_uH"]==1.)
    limitation = source_limit*2*core["amin_mm2"]*1e-6/(target_external*1e-6)
    core_req=target_external*1e-6*max_current/(2*source_limit)/1e-6
    if nominal["passes_optional_conservative_80pct_Bsat"] or nominal["passes_existing_design_90pct_Bsat"]:
        raise ValueError("Expected 121.515A high-bias screen was accidentally turned into a pass")
    # Source Lr catalogue rounds gap to 4 decimals; do not demand 5-place equality.
    if abs(nominal_1u["reluctance_estimated_total_airgap_mm"]-design["turns"][0]["gap_mm"])>1e-4:
        raise ValueError("Manufacturing 1uH gap and computed AL disagree")
    ctcore=ct["core_candidate"]
    return {
       "schema":"D1_100A_MAGNETIC_100C_121A_FAULT_AND_16MM_DFM_GATE_V1",
       "status":"NO_STOCK_CORE_PASSES_D1_FAULT_FLUX_AND_MECHANICAL_RESERVE",
       "source_sha256_lf":{str(p.relative_to(ROOT)).replace("\\","/"):_hash(p)
                        for p in (LR,MAG,CAT,POLICY,CONTRACT,CT)},
       "requirements":{
          "D1_load_current_A":d1["load_current_class_a"],
          "height_limit_mm":d1["height_limit_mm"],
          "provisional_noncore_margin_mm":mag["catalogue_core_stack"]["non_core_reserve_mm"],
          "Lr_tank_total_uH":_r(target_total),
          "Lr_leakage_prior_model_uH":_r(leakage),
          "Lr_external_target_from_unmeasured_leakage_uH":_r(target_external),
          "tank_nominal_frequency_kHz":lr["tank"]["resonant_khz"],
          "max_RFQ_current_A":max_current,
          "max_deck_fault_peak_A":max(x["current_a"] for x in lr["physical_peaks"]["cases"].values()),
          "optional_high_conservatism_B_limit_T":source_limit,
          "prior_90pct_Bsat_limit_T":_r(.9*bsat,4),
          "N97_nominal_100C_Bsat_T":bsat,
          "a_100A_output_is_not_100A_in_Lr":True
       },
       "transformer_T1_to_T4":{
          "quantity":4,
          "original_design_core":mag["core"]["name"],
          "original_core_Ae_mm2":mag["core"]["Ae_m2"]*1e6,
          "primary_turns":3,
          "two_secondary_half_turns_each":1,
          "each_Lm_uH":10.,
          "original_gap_analytic_mm":_r(mag["gap_mm"],4),
          "reported_48V_Bpp_mT":_r(mag["flux"]["48v_delta_b_t"]*1e3,3),
          "original_loss_model_100A_total_copper_W":_r(mag["copper_100a"]["total_w"],4),
          "original_loss_model_core_per_set_50v_W":_r(mag["core_loss_w_per_set_50v"],4),
          "actual_all_four_vendor_3D_terminal_DOT_verified":False,
          "Maxwell_N97_100C_and_AC_loss_final_verified":False
       },
       "Lr_original_design": {
          "core":"TDK EILP38 N97, B66459G0000X197 ELP + B66459K0000X197 I",
          "catalogue_Ae_mm2":core["ae_mm2"],
          "catalogue_Amin_mm2":core["amin_mm2"],
          "ungapped_AL_nH_per_turn2":core["al_ungapped_nh"],
          "nominal_core_plate_height_mm":core["core_height_nom_mm"]+core["plate_height_nom_mm"],
          "worst_known_stack_including_glue_label_mm":stack["ELP38_I38"]["stack_flat_no_clamp_worst_mm"],
          "Z_remaining_mm":stack["ELP38_I38"]["d1_budget_left_for_tim_cold_plate_fasteners_mm"],
          "recommended_first_article_branch":"2turn_0p92uH_only_if_protection_or_custom_BH_passes",
          "prototype_1uH_RfQ_sizing_gap_mm":nominal_1u["reluctance_estimated_total_airgap_mm"],
          "net_external_0p92uH_gap_analytic_mm":nominal["reluctance_estimated_total_airgap_mm"],
          "oversized_1uH_when_0p08uH_leakage_is_added_total_uH":_r(1+leakage,5),
          "estimated_tank_frequency_ratio_for_1p08_vs_1p00":_r(math.sqrt(target_total/(1+leakage)),6),
          "airgap_must_be_measured_after_actual_transformer_leakage":True,
          "tdk_gap_curve_published_for_N87_not_N97":True,
          "candidate_cases":cases,
          "vendor_real_100C_N97_BH_LI_and_AC_200kHz_loss_passed":False
       },
       "catalogue_eilp_candidate_screen":catalogue_rows,
       "design_resolution_options":{
           "A_2turn_keep_ELP38":
              {"need_limit_Lr_fault_peak_A_at_0p248T":_r(limitation,3),
               "compared_to_current_121p515A_rfq_A":max_current,
               "requires_true_fast_D0_protection_timing_and_cold_fault_real_data":True,
               "accept_before_fast_OC_measured":False},
           "B_custom_enlarged_low_Z_N97_core":
              {"min_Amin_mm2_for_2turn_0p92uH_at_121p515A":_r(core_req,3),
               "increase_vs_stock_ELP38_Amin_percent":_r((core_req/core["amin_mm2"]-1)*100,2),
               "custom_geometry_must_keep_verified_16mm_full_assembly":True,
               "manufacturer_quote_and_hot_bias_Maxwell_pending":True},
           "C_custom_gap_3turn":
              {"gap_analytic_mm":next(x for x in cases if x["turns"]==3 and math.isclose(x["target_Lr_uH"],target_external,abs_tol=1e-9))["reluctance_estimated_total_airgap_mm"],
               "outside_published_N87_empirical_2mm_range":True,
               "new_Cu_ac_fringe_and_gap_tolerance_FEA_required":True}
       },
       "CT_primary_current_sensing":{
           "sensed_primary_peak_model_A":ct["measured"]["i_pk_a"],
           "primary_secondary_turns_ratio":ct["as_built"]["turns_ratio"],
           "burden_ohm":ct["as_built"]["burden_ohm"],
           "concept_Ae_mm2":ctcore["ae_m2"]*1e6,
           "concept_Bsat_T":ctcore["bsat_t"],
           "material_MPN_3D_footprint_vendor_DOT_verified":False,
           "independent_fault_hardware_D0_verified":False
       },
       "hardware_fab_gates":{
          "native_magnetic_24_pad_schematic_footprint_component_linked":False,
          "all_5_physical_3D_core_clamps_and_DOT_manufacturer_signed":False,
          "N97_100C_nonlinear_L_of_I_to_121p515A_passed":False,
          "Maxwell_1A_generic_ferrite_cannot_satisfy_material_or_bias_gate":True,
          "200kHz_core_Cu_loss_hot_and_fringing_FEM_passed":False,
          "D0_10channel_fault_shutdown_physical_passed":False,
          "real_100A_voltage_temperature_and_4wire_interconnect_tested":False,
          "manufacturer_DFM_16mm_Z_and_assembly_approved":False,
          "release_approved":False
       },
       "fab_release":"NOT_FOR_FAB"
    }


def main() -> None:
    p=argparse.ArgumentParser()
    m=p.add_mutually_exclusive_group(required=True)
    m.add_argument("--write",action="store_true")
    m.add_argument("--check",action="store_true")
    a=p.parse_args()
    result=build()
    raw=json.dumps(result,ensure_ascii=False,indent=2)+"\n"
    if a.write:
        OUT.write_text(raw,encoding="utf8",newline="\n")
    elif not OUT.exists() or OUT.read_text("utf8")!=raw:
        raise SystemExit("Magnetic physical-release gate is stale; run --write after reviewing source")
    print(json.dumps({
      "status":result["status"],
      "primary_path_A_I_limit":result["design_resolution_options"]["A_2turn_keep_ELP38"]["need_limit_Lr_fault_peak_A_at_0p248T"],
      "custom_path_B_Amin_req_mm2":result["design_resolution_options"]["B_custom_enlarged_low_Z_N97_core"]["min_Amin_mm2_for_2turn_0p92uH_at_121p515A"],
      "safe_catalogue_combinations":sum(q["passes_joint_fault_flux_and_Z_reserve"] for q in result["catalogue_eilp_candidate_screen"]),
      "fab_release":result["fab_release"]},ensure_ascii=False,indent=2))
if __name__=="__main__":
    main()

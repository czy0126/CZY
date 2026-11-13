"""EILP32 3.2±0.15mm window versus high layer copper stackup fail-closed.

The board winding is not safe merely because its 12-layer 4oz DC copper
loss appears acceptable. Stack thickness itself must fit ferrite window
with tolerances, insulation, resin fill and real clamping allowance.
This calculation is NOT a supplier-approved layer stack.

    python tools/g2_v14_window_stackup_gate.py --write
    python tools/g2_v14_window_stackup_gate.py --check
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
G2=ROOT/"hardware/dcx_main/g2"
IN=G2/"g2_v14_through_board_three_leg_slot_DFM_screen_NOT_FOR_FAB.json"
OUT=G2/"g2_v14_ELP32_PCB_window_stackup_16mm_fit_GATE_NOT_FOR_FAB.json"

def source():
    doc=json.loads(IN.read_text("utf8"))
    if (doc["status"]!="12_SLOT_20_PAD_7_TRACK_3_VIA_REDESIGN_REQUIRED_NOT_FOR_FAB"
        or doc["slot_count"]!=12 or doc["ELP32_E_and_I_N97_TDK"]["magnetic_window_height_nom_mm"]!=3.2
        or doc["ELP32_E_and_I_N97_TDK"]["ELP_E_height_nom_mm"]!=6.35):
        raise ValueError("Native ELP32 mechanical baseline no longer matches V14")
    return doc


def one_case(name,layers,copper_um,dielectric_mm, pcb_tolerance_mm=.15):
    core_window_nom=3.2
    core_window_negative_tol=.15
    core_window_min=core_window_nom-core_window_negative_tol
    clearance_each=.25
    additional_engineering_reserve=.10
    top_bottom_finish=.04 # two soldermask surfaces provisional, no coverlay
    # This lower bound neglects plating build-up and pattern fill effects;
    # final detailed fab stackup could be thicker.
    copper=layers*copper_um*.001
    dielectric=(layers-1)*dielectric_mm
    nominal=copper+dielectric+top_bottom_finish
    worst=nominal+pcb_tolerance_mm
    allowed=core_window_min-2*clearance_each-additional_engineering_reserve
    result={
       "case":name,
       "copper_layers":layers,
       "per_layer_copper_um":copper_um,
       "min_assumed_dielectric_mm_each":dielectric_mm,
       "total_assumed_copper_thickness_mm":round(copper,5),
       "total_assumed_dielectric_mm":round(dielectric,5),
       "both_surface_mask_thickness_mm":top_bottom_finish,
       "estimated_board_nominal_stack_mm":round(nominal,5),
       "assumed_board_positive_thickness_tolerance_mm":pcb_tolerance_mm,
       "estimated_board_worst_stack_mm":round(worst,5),
       "ferrite_window_min_mm":core_window_min,
       "fit_clearance_each_face_mm":clearance_each,
       "required_margin_to_actual_window_mm":additional_engineering_reserve,
       "maximum_worst_board_stack_mm":round(allowed,5),
       "fits_provisional_ferrite_window":worst<=allowed+1e-9,
       "manufacturer_approved":False,
       "wire_winding_fill_and_isolation_also_passed":False,
    }
    return result


def build():
    src=source()
    cases=[
        one_case("8L_2OZ_0P10MM_DIELECTRIC",8,70,.10),
        one_case("12L_2OZ_0P10MM_DIELECTRIC",12,70,.10),
        one_case("12L_3OZ_0P10MM_DIELECTRIC",12,105,.10),
        one_case("12L_3OZ_0P09MM_DIELECTRIC_CUSTOM",12,105,.09),
        one_case("12L_4OZ_0P10MM_DIELECTRIC",12,140,.10),
        one_case("16L_4OZ_0P10MM_DIELECTRIC",16,140,.10),
    ]
    m={x["case"]:x for x in cases}
    if (m["12L_4OZ_0P10MM_DIELECTRIC"]["fits_provisional_ferrite_window"]
        or not m["12L_2OZ_0P10MM_DIELECTRIC"]["fits_provisional_ferrite_window"]):
        raise ValueError("12layer core window gate unexpected")
    # 3oz copper is neither a routine supplier stack nor enough proof of
    # hot loss, but a thinner dielectric could make it nominally fit.
    if not m["12L_3OZ_0P09MM_DIELECTRIC_CUSTOM"]["fits_provisional_ferrite_window"]:
        raise ValueError("12layer 3oz custom dielectric param result drift")
    v=src["winding_electrothermal_and_double_sided_preliminary"]
    length=v["conductor_U_turn_length_mm"]
    width=v["screened_copper_trace_width_mm"]
    i_primary=v["primary_rms_assumed_A"]
    i_half=v["secondary_each_half_rms_concept_A"]
    rho=1.724e-8*(1+.00393*(100-20))
    one=rho*(length*1e-3)/(width*1e-3*105e-6)
    primary_total=4*i_primary**2*(3*one)
    secondary_total=4*i_half**2*((one/4)+(one/4))
    corrected={
      "case":"12L_3OZ_4PAR_SEC_EACH_3SER_PRIMARY",
      "estimated_100C_4core_copper_DC_loss_W":round(primary_total+secondary_total,4),
      "part_primary_4core_W":round(primary_total,4),
      "part_secondary_4core_W":round(secondary_total,4),
      "actual_200kHz_copper_AC_loss_and_blind_vias_NOT_included":True,
      "layer_count_12_with_one_unused_shield_candidate":True,
      "factory_12L_3OZ_inner_Cu_and_90um_P_to_S_dielectric_signed":False,
      "passes_only_parametric_thickness_if_0p09mm_custom_layers_available":
          m["12L_3OZ_0P09MM_DIELECTRIC_CUSTOM"]["fits_provisional_ferrite_window"],
    }
    return {
     "schema":"G2_V14_ELP32_DOUBLE_SIDED_PCB_WINDING_3P05MM_MIN_WINDOW_FIT_GATE_V1",
     "status":"12L_4OZ_DOES_NOT_FIT_3P05MM_MIN_WINDOW_CONSERVATIVE_ASSEMBLY",
     "source_v14_slots_sha256":hashlib.sha256(IN.read_bytes()).hexdigest(),
     "core_E_window_TDK_nominal_mm":3.2,
     "core_E_window_TDK_negative_tolerance_mm":.15,
     "core_E_window_guaranteed_min_mm":3.05,
     "assembly_fit_each_side_mm":.25,
     "extra_engineering_clearance_mm":.10,
     "estimated_board_worst_allowed_mm":2.45,
     "native_PCB_bottom_assembled_parts_actual_count":0,
     "reused_existing_V13_eda_gui":True,
     "cases":cases,
     "custom_12L_3OZ_copper_hot_DC_screen":corrected,
     "manufacturing_constraints":[
       "Confirm ELP32 actual window and PCB Cu+prepreg maximum thickness on 1st article: nominal core window 3.2 ±0.15mm",
       "Obtain full signed 12L/3oz custom copper and <=0.09mm dielectric per interface stack and 48V functional insulation",
       "Verify interlayer blind/buried vias and antipads do not connect primary to secondary; 1 turn per secondary half, primary3 series turns",
       "AC resistance, proximity fields, core loss and worst-case hotbias solved with Maxwell and verified 200kHz AC impedance test",
       "Mechanical E/I fixture force, ferrite crack, soldermask and cold plate worst-case upper/lower protrusions <16mm",
     ],
     "manufacturer_full_DFM_approved":False,
     "native_winding_applied_to_PCB":False,
     "fabrication_approved":False,
     "fab_release":"NOT_FOR_FAB",
    }


def main():
    a=argparse.ArgumentParser()
    p=a.add_mutually_exclusive_group(required=True)
    p.add_argument("--write",action="store_true")
    p.add_argument("--check",action="store_true")
    args=a.parse_args()
    d=build()
    data=json.dumps(d,ensure_ascii=False,indent=2)+"\n"
    if args.write:
        if OUT.exists() and OUT.read_text("utf8")!=data:
            raise ValueError("Do not overwrite prior accepted V14 layer stack gate")
        OUT.write_text(data,encoding="utf8",newline="\n")
    elif not OUT.exists() or OUT.read_text("utf8")!=data:
        raise ValueError("V14 mechanical window test missing/stale")
    print(json.dumps({"status":d["status"],
       "max_safely_allowed_board_stack_mm":d["estimated_board_worst_allowed_mm"],
       "12L4oz_fit":next(x for x in d["cases"] if x["case"].startswith("12L_4OZ"))["fits_provisional_ferrite_window"],
       "12L3oz_with_90um_dielectric_fit":next(x for x in d["cases"] if x["case"].startswith("12L_3OZ_0P09"))["fits_provisional_ferrite_window"],
       "fabrication_approved":False},ensure_ascii=False,indent=2))
if __name__=="__main__":
    main()

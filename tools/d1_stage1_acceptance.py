"""D1 stage-one real-delivery acceptance from same-checkout source evidence.

This is the physical 48V 24:1 / 100A / <=16mm first-article gate, NOT a
synthesis of nominal results. Reports what genuine primary files establish,
with each missing engineering/hardware proof named. "More tests pass" can
never substitute a 100C B-H/L(I), real OEM footprints, 10 VGS or a bench.

python tools/d1_stage1_acceptance.py --write
python tools/d1_stage1_acceptance.py --check
python tools/d1_stage1_acceptance.py --require-stage1 # expected nonzero now
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import d1_fabrication_gate
import maxwell_magnetics_prescreen as magnetic

ROOT=Path(__file__).resolve().parents[1]
HW=ROOT/"hardware/dcx_main"
POLICY=ROOT/"design/v3/power_priority/d1_staged_target_policy.json"
FEM=HW/"maxwell/ELP38_Lr_1A_EXTERNAL_LEADS_30PASS_CONVERGED_CONCEPT_NOT_FOR_FAB.evidence.json"
BOARD=HW/"g2/dcx_main_board_g2_t530_72_BIPOLAR_ARRAY_NOT_FOR_FAB.eprj2"
G2=HW/"g2/g2_t530_bipolar_drc_delta.json"
FIRST=HW/"protection_p0_fault_matrix_TEMPLATE.json"
OUT=HW/"d1_stage1_acceptance.json"
BLOCKERS=(
    "real_protection_built_and_ten_VGS_across_faults",
    "magnetics_100C_non_linear_L_I_and_five_physical_PIN_DOT",
    "oem_cout_component_symbol_footprint_and_native_parity",
    "100A_two_pole_copper_contact_soA_and_full_thermal",
    "real_native_gui_erc_drc_and_manufacturing_package",
    "height_including_board_bond_clamp_cold_plate_under_16mm",
    "25_50_75_100A_measured_staged_46_48_50V",
    "same_revision_fabrication_safety_gate",
)

def _hash(path:Path)->str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def _read(path:Path)->dict:
    return json.loads(path.read_text(encoding="utf-8"))

def _source(path:Path)->dict:
    return {"path":path.relative_to(ROOT).as_posix(),
            "sha256":_hash(path)}

def evaluate()->dict:
    policy=_read(POLICY)
    stage=next(x for x in policy["stages"] if x["id"]=="D1_100A")
    assert stage["vin_nominal_v"]==48 and stage["load_current_class_a"]==100
    assert stage["height_limit_mm"]==16
    design=magnetic.report()
    all_candidates=design["cases"]
    two=[x for x in all_candidates if x["turns"]==2]
    three=[x for x in all_candidates if x["turns"]==3]
    assert len(two)==2 and len(three)==2
    fem=_read(FEM)
    for row in fem["provenance"]:
        path=ROOT/row["path"]
        if path.stat().st_size!=row["bytes"] or _hash(path)!=row["sha256"]:
            raise ValueError("physical Maxwell solver source/hash mismatched "+str(path))
    g2=_read(G2)
    if _hash(BOARD)!=g2["candidate_sha256"]:
        raise ValueError("G2 native PCB and accepted DRC are from different revisions")
    fab=d1_fabrication_gate.build()
    checks={
        "real_protection_built_and_ten_VGS_across_faults":False,
        "magnetics_100C_non_linear_L_I_and_five_physical_PIN_DOT":False,
        "oem_cout_component_symbol_footprint_and_native_parity":(
            g2["oem_package_added_as_real_components"] is True),
        "100A_two_pole_copper_contact_soA_and_full_thermal":(
            g2["100a_current_carrying_and_contacts_qualified"] is True),
        "real_native_gui_erc_drc_and_manufacturing_package":(
            fab["checks"]["native_erc_evidence"] is True
            and fab["checks"]["routed_pcb_to_schematic_evidence"] is True
            and fab["checks"]["manufacturing_package_evidence"] is True),
        "height_including_board_bond_clamp_cold_plate_under_16mm":(
            g2["manufacturer_height_thermal_and_hot_esr_qualified"] is True),
        "25_50_75_100A_measured_staged_46_48_50V":False,
        "same_revision_fabrication_safety_gate":fab["release_approved"] is True,
    }
    assert set(checks)==set(BLOCKERS)
    hard_stops={
        "two_turn_092uH_fails_121p515A_flux_prescreen":(
            next(x for x in two if math.isclose(x["target_l_uh"],.92))
            ["passes_flux_screen_at_fixed_l"] is False),
        "two_turn_1uH_fails_121p515A_flux_prescreen":(
            next(x for x in two if math.isclose(x["target_l_uh"],1.0))
            ["passes_flux_screen_at_fixed_l"] is False),
        "published_3turn_example_gap_out_of_screen_range":(
            all(x["gap_inside_published_empirical_range"] is False for x in three)),
        "converged_trial_is_unqualified_1A_stock_ferrite":(
            fem["native_convergence"]["passes"]==18
            and fem["oem_n97_100c_bh_verified"] is False
            and fem["model_has_two_artificial_long_current_leads"] is True
            and fem["operating_point_ac_and_high_bias_sweeps_verified"] is False),
        "converged_trial_does_not_meet_nominal_0p92uH":(
            abs(fem["static_dc_energy_equivalent_L_uH_unqualified"] -
                fem["target_Lr_uH"])>0.1),
        "G2_native_board_still_unrouted":(
            g2["actual_drc"]["Connection Error"]>0
            or g2["actual_drc"]["Netlist Error"]>0),
        "D0_six_scenario_hardware_evidence_absent":(
            not (HW/"protection_p0_fault_matrix_REAL.json").is_file()),
    }
    if not all(hard_stops.values()):
        # Fresh physical evidence can only promote an item after the
        # corresponding engineering gate is modified, with new tests.
        raise ValueError("stage-one baseline changed; re-review actual evidence")
    result={
        "schema":"D1_FIRST_ARTICLE_48V_100A_16MM_ACCEPTANCE_V1",
        "status":"NOT_STAGE1_DELIVERED",
        "target":{"vin_nominal_v":48,"ratio":24,"load_class_a":100,
                  "assembled_height_limit_mm":16},
        "physical_hardware_delivery_approved":False,
        "power_stage_fabrication_approved":False,
        "acceptance_checks":checks,
        "missing_acceptance":sorted(k for k,v in checks.items() if not v),
        "hard_stop_facts":hard_stops,
        "engineering_observations":{
            "native_G2_connections_remaining":g2["actual_drc"]["Connection Error"],
            "native_G2_netlist_errors":g2["actual_drc"]["Netlist Error"],
            "two_turn_0p92uH_121p515A_flux_T":
                next(x for x in two if math.isclose(x["target_l_uh"],.92))
                ["b_at_rfq_current_t"],
            "screen_flux_limit_T":design["screen_b_t"],
            "three_turn_0p92uH_121p515A_flux_T":
                next(x for x in three if math.isclose(x["target_l_uh"],.92))
                ["b_at_rfq_current_t"],
            "maxwell_1A_energy_equivalent_uH_NOT_QUALIFIED":
                fem["static_dc_energy_equivalent_L_uH_unqualified"],
            "maxwell_1A_target_uH":fem["target_Lr_uH"],
            "manufacturing_gate_blocker_categories":fab["blockers"],
        },
        "source_hashes":[_source(p) for p in (POLICY,magnetic.SOURCE,FEM,G2,BOARD)],
        "note":"All results are source-reproducible engineering checks, NOT a laboratory 100A first-article validation. Do not promote stage-one or start high-current operation.",
    }
    if all(checks.values()):
        # This version has no mechanism to claim approval from a synthetic
        # source set; a signed new test scheme must be independently reviewed.
        raise ValueError("Unexpected full stage-one pass: manually review actual hardware")
    return result

def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--write",action="store_true")
    p.add_argument("--check",action="store_true")
    p.add_argument("--require-stage1",action="store_true")
    options=p.parse_args()
    r=evaluate()
    body=json.dumps(r,ensure_ascii=False,indent=2)+"\n"
    if options.write:OUT.write_text(body,encoding="utf-8",newline="\n")
    if options.check and (not OUT.is_file() or OUT.read_text(encoding="utf-8")!=body):
        raise SystemExit("D1 stage-one evidence report stale: --write")
    print("D1 stage-one:",r["status"],
          f"{len(r['missing_acceptance'])} acceptance categories missing")
    return 1 if options.require_stage1 and r["status"]!="DELIVERED" else 0

if __name__=="__main__":
    raise SystemExit(main())

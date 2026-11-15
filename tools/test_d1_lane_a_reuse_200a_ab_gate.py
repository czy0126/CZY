"""Smoke/engineering regression for two *actual* KiCad 12-layer copper coupons.
DRC zero is deliberately not manufacturing permission. Cannot fake 200A.
"""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
import d1_lane_a_reuse_200a_ab_gate as ab

def test_native_coupons_true_source_sha_and_drc_zero():
    d=ab.evaluate()
    assert d["status"].startswith("TWO_NATIVE_KICAD_DRC_0_0")
    assert len(d["actual_existing_reused_SR_footprints_from_V17"])==8
    for name in ("physical_KiCad_A_native_verification","physical_KiCad_B_native_verification"):
        o=d[name]
        assert o["native_violations"]==0 and o["native_unconnected"]==0
        assert len(o["inherited_ignored_checks"])==5
        assert o["board_sha256"]
    assert d["geometry_A_end_vs_B_center_mm"]["positive_negative_output_contacts_moved_together"]

def test_real_center_move_improves_physics_only_not_rated():
    d=ab.evaluate()
    a=d["conditional_DConly_100C_copper_results"][0]
    assert a["A_edge_terminal"]["ideal_P_DConly_W"]>60
    assert 14<a["B_center_terminal"]["ideal_P_DConly_W"]<15
    assert a["idealized_loss_improvement_percent"]==76.92
    assert d["output_pair_copper_20pct_budget_W"]<a["B_center_terminal"]["ideal_P_DConly_W"]
    assert d["B_center_70um_copper_still_exceeds_20pct_loss_target"] is True
    assert d["real_bus_routing_on_surface"]["board_12_copper_layers_defined_but_not_all_parallel_current_carrying"] is True

def test_external_bonded_foil_not_claimed_real():
    d=ab.evaluate()
    option=d["conditional_DConly_100C_copper_results"][1]
    assert option["B_center_terminal"]["ideal_P_DConly_W"]<1.25
    assert option["B_center_terminal"]["ideal_P_DConly_W"]>1.2
    assert d["B_center_0p8mm_foil_potentially_below_20pct_loss_target_but_not_a_real_component"] is True
    assert d["power_on_allowed"] is False and d["release_allowed"] is False

def test_gate_reproducible_no_approval():
    d=ab.evaluate()
    committed=json.loads(ab.OUT.read_text("utf8"))
    assert committed==d
    assert ab.main(["--check"])==0
    assert ab.main(["--require-release"])==2

def test_reports_provenance_to_real_later_rated_magnetics():
    report=json.loads((ab.D/"e1_4cell_200A_pair_collector_electrical_gate_NOT_FOR_FAB.json").read_text("utf8"))
    assert report["actual_native_drc_report_unconnected"]==0
    assert report["output_copper_fails_200A_continuous_design_requirement"] is True
    assert report["external_straps_real_CAD_and_factory_solder_metal_current_rating_verified"] is False
    assert report["complete_primary_magnetics_24to1_CT_protection_available"] is False
    assert report["energization_allowed"] is False

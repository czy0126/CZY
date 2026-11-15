"""Regression tests use actual saved PCB and KiCad DRC evidence, not model estimates."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
import d1_lane_a_gate as a
def test_source_locked_real_drc_zero_and_no_missing_in_current_partial_board():
    d=a.run_audit()
    assert (d["enabled_rule_violations"],d["unconnected_in_current_partial_model"])==(0,0)
    assert d["candidate_native_counts"]["track_and_via_objects"]==580
    assert d["source_native_counts"]["track_and_via_objects"]==529
    assert set(d["routed_net_names"])=={"SW","VIN_P","GH","GH_DRV","HB","OC"}
def test_release_denied_incomplete_power_converter():
    d=a.run_audit()
    assert d["magnetics_missing"]==["CT","T1","T2","T3","T4"]
    assert d["easyeda_g1_native_146_connection_errors_resolved"] is False
    assert d["fabrication_approved"] is False and d["power_on_approved"] is False
    assert d["U1_3_OC_via_in_pad_filled_capped_process_signed"] is False
def test_ignored_checks_remain_explicit():
    assert len(a.run_audit()["ignored_drc_checks"])==5
def test_deterministic_report_and_release_command_fail_closed():
    assert a.run_audit()==a.run_audit()
    assert a.main(["--check"])==0
    assert a.main(["--require-release"])==2

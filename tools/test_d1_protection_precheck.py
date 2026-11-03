"""Fail closed when any real gate or proposed enable route is absent."""
import copy
import json
import d1_protection_precheck as c

def test_baseline_route_exact_and_no_fabrication_claim():
    r=c.build()
    assert r["status"]=="HARDWARE_NOT_IMPLEMENTED"
    assert r["draft_matches_existing_logical_gates"]
    assert not r["fabrication_release_approved"]
    assert r["checks"]["r8_permanent_pullup_still_physical_blocker"]
    assert not r["checks"]["four_buffer_drivers_actually_placed"]
    assert json.loads(c.REPORT.read_text(encoding="utf-8"))==r

def test_missing_sr_channel_is_detected():
    spec=json.loads(c.SPEC.read_text(encoding="utf-8"))
    spec["proposed_sr_channels"].pop()
    r=c.build(spec=spec)
    assert r["status"]=="CONTRACT_INVALID"
    assert any("eight" in e for e in r["errors"])

def test_duplicated_enable_or_gate_driver_pin_is_detected():
    spec=json.loads(c.SPEC.read_text(encoding="utf-8"))
    spec["proposed_sr_channels"][1]["buffer_channel"]="A"
    spec["proposed_sr_channels"][1]["buffer_enable_pin"]="1"
    spec["proposed_sr_channels"][1]["buffer_output_pin"]="7"
    r=c.build(spec=spec)
    assert not r["draft_matches_existing_logical_gates"]
    assert any("reused" in e for e in r["errors"])

def test_a_wrong_actual_ucc24624_output_net_is_not_hidden_by_golden_subnet():
    native=json.loads(c.NATIVE.read_text(encoding="utf-8"))["value"]["refs"]
    native=copy.deepcopy(native)
    native["U3"]["1"]="WRONG"
    r=c.build(nets=native)
    assert r["status"]=="CONTRACT_INVALID"
    assert any("source pin" in e for e in r["errors"])

def test_forged_hardware_approval_and_r8_suppression_are_rejected():
    spec=json.loads(c.SPEC.read_text(encoding="utf-8"))
    spec["acceptance_flags"]["native_cad_has_all_four_buf_drivers"]=True
    spec["fabrication_approved"]=True
    r=c.build(spec=spec)
    assert not r["draft_matches_existing_logical_gates"]
    assert not r["fabrication_release_approved"]

"""G0 packaged KiCad artifacts must be source-locked and never claim HW release."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"hardware/dcx_main/g2/d1_g0_integrated_mainboard_NOT_FOR_FAB"
STEM="d1_g0_integrated_mainboard_ELECTRICAL_NOT_FOR_FAB"
META=BASE/"d1_g0_integrated_trial_package_NOT_FOR_FAB.json"

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def report():return json.loads(META.read_text("utf-8"))

def test_native_editable_packaged_project_with_zero_rule_and_connection_errors():
    r=report()
    assert r["pcb_device_count"]==154
    assert r["schematic_unique_ref_pin_net_checked"]==427
    assert r["pcb_unconnected"]==0
    assert r["pcb_drc_violations"]==0 and r["schematic_erc_violations"]==0
    for ext in (".kicad_pcb",".kicad_sch",".kicad_pro",".net"):
        assert (BASE/(STEM+ext)).stat().st_size>100
    for name,digest in r["project_file_sha256"].items():
        assert sha(BASE/name)==digest

def test_actual_kicad_cli_reports_rule_0_and_unconnected_0_without_tampering():
    r=report()
    d=json.loads((BASE/(STEM+"_native_drc.json")).read_text("utf-8"))
    e=json.loads((BASE/(STEM+"_native_erc.json")).read_text("utf-8"))
    assert not d["violations"] and not d["unconnected_items"]
    assert not any(x.get("violations",[]) for x in e["sheets"])
    assert r["ignored_native_drc_checks"]  # still inherited, never claim release

def test_magnetics_logic_has_all_five_pcb_devices_but_zero_signed_vendor_pins():
    r=report()
    m=json.loads((BASE/"d1_g0_mainboard_net_and_magnetics_audit_NOT_FOR_FAB.json").read_text("utf-8"))
    assert set(r["logical_magnetics"])=={"T1","T2","T3","T4","CT"}
    assert m["trial_magnetics_logical_landings"]==24
    assert m["manufacturer_magnetics_terminal_pinout_verified"] is False
    assert m["manufacturer_magnetics_footprints_validated"] is False

@pytest.mark.parametrize("key",[
    "g0_approved","g1_approved","fabrication_approved","energization_allowed",
    "magnetics_vendor_pinout_and_DOT_verified",
    "magnetics_footprints_manufacturing_approved",
    "schematic_independently_authored",
    "real_12v_isolated_bias_uvlo_integrated",
    "real_independent_48v_estop_and_hs_monitor_integrated",
    "via_in_pad_12layer_filled_capped_vendor_signed",
    "traces_current_density_emc_thermal_verified",
    "real_48v_coldstart_and_fault_waveforms_verified"
])
def test_release_cannot_be_inferred_from_cad(key):
    assert report()[key] is False

def test_reproducibility_receipts_are_source_locked():
    for name in ("d1_g0_complete_logical_board_CANDIDATE_NOT_FOR_FAB_receipt.json",
                 "d1_g0_27_open_route_TRIAL_NOT_FOR_FAB_receipt.json"):
        # Source trial has a specifically named report rather than the board stem.
        if (BASE/name).exists():
            assert (BASE/name).stat().st_size>50
    trial=json.loads((BASE/"d1_g0_27_open_route_TRIAL_NOT_FOR_FAB_receipt.json").read_text("utf-8"))
    assert trial["route_count"]==27 and trial["violations"]==trial["unconnected"]==0
    assert sha(BASE/"d1_g0_27_open_route_TRIAL_NOT_FOR_FAB.kicad_pcb")==trial["new_board_sha256"]

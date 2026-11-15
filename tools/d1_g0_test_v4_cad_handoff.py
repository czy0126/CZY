"""G0 V4 native KiCad full-board and independent-source handoff checks."""
from __future__ import annotations
import csv,hashlib,json,zipfile
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
G2=ROOT/"hardware/dcx_main/g2"
V4=G2/"d1_g0_INDEPENDENT_SOURCE_V4_MAINBOARD_NOT_FOR_FAB"
REPORT=V4/"V4_mainboard_acceptance_NOT_FOR_FAB.json"
V1=G2/"d1_g0_integrated_mainboard_NOT_FOR_FAB"
MIGRATE=V4/"secondary_129_physical_pads_FROM_PGND.csv"
BOM=V4/"G0_V4_157_PART_MANUFACTURING_STOPLINE_BOM.csv"
INDEPENDENT=V4/"independent_design_to_native_433_pins_receipt.json"
BIAS=V4/"physical_2_bias_port_native_evidence.json"
SPLIT=V4/"actual_129_pads_181_tracks_return_split_receipt.json"

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def obj(p):return json.loads(p.read_text("utf-8"))

def test_v4_is_source_authored_and_native_drc_erc_green_but_not_approved():
    x=obj(REPORT)
    assert x["PCB_footprints"]==157
    assert x["independent_schematic_ref_pin_net_parity"]==433
    assert x["native_PCB_DRC_violations"]==x["native_PCB_unconnected"]==x["native_PCB_ERC_violations"]==0
    assert x["independent_SCH_generated_from_PCB"] is False
    assert x["independent_SCH_generated_from_SPICE_golden_and_peripherals"] is True
    assert x["secondary_physically_reassigned_pads"]==129
    assert x["secondary_pgnd_tracks_or_vias_reassigned"]==181
    assert x["external_isolated_12v_input_ports"]==2

def test_independent_schematic_evidence_is_NOT_a_mirrored_pcb_claim():
    x=obj(INDEPENDENT)
    assert x["has_independent_electrical_net_basis_NOT_mirrored_from_PCB"] is True
    assert x["independent_ref_pin_net_count"]==433
    assert x["native_erc_violations"]==0
    assert x["real_functional_schematic_hardware_signed_off"] is False
    assert x["UVLO_interlock_emergency_disconnect_realized"] is False

def test_physical_isolation_ECO_changes_actual_tracks_and_ground_zones():
    x=obj(SPLIT)
    assert x["converted_physical_pads"]==129
    assert x["converted_pgnd_secondary_tracks_or_vias"]==181
    assert x["PCB_copper_zones_primary_secondary_split"] is True
    assert x["pad_level_primary_secondary_return_net_common"] is False
    assert x["native_DRC_violations"]==x["native_DRC_unconnected"]==0
    assert not x["real_isolation_clearance_qualification"]
    assert x["primary_return_T4_path"].startswith("T4 PRI_B")

def test_bias_connectors_are_separate_but_not_actual_bias_generators():
    b=obj(BIAS)
    assert b["physical_board_footprints"]==157
    assert b["port_ref_pad_net"]["J_BIAS_P"]=={"1":"VCC12","2":"PGND"}
    assert b["port_ref_pad_net"]["J_BIAS_S"]=={"1":"VCC12_S","2":"SR_SOURCE_RETURN"}
    assert b["primary_secondary_return_nets_shared"] is False
    assert b["source_12v_supply_modules_integrated"] is False
    assert b["independent_12v_supplies_present_for_actual_bench"] is False

def test_129_physical_secondary_ground_mapping_has_no_primary_T4():
    with MIGRATE.open(newline="",encoding="utf-8") as f:
        rows=list(csv.DictReader(f))
    assert len(rows)==129
    assert len({(r["reference"],r["physical_pad_number"],r["duplicate_package_pad_instance"])
                for r in rows})==129
    assert all(r["required_isolated_secondary_return_net"]=="SR_SOURCE_RETURN" for r in rows)
    assert all(r["current_net"]=="PGND" for r in rows)
    assert not any(r["reference"] in ("T4","U1","U2","QL","J_IN") for r in rows)
    assert sum(r["reference"].startswith("CHB") for r in rows)==72

def test_bom_contains_only_R8_DNP_and_2_independent_ports():
    with BOM.open(newline="",encoding="utf-8") as f:
        parts=list(csv.DictReader(f))
    assert len(parts)==157
    assert {r["Designator"] for r in parts if r["DNP"]=="yes"}=={"R8"}
    p={r["Designator"]:r for r in parts}
    assert "SR_SOURCE_RETURN" in p["J_BIAS_S"]["NativeRefPinNet"]
    assert "PGND" in p["J_BIAS_P"]["NativeRefPinNet"]
    assert "SR_SOURCE_RETURN" in p["J_OUT"]["NativeRefPinNet"]
    assert "PGND" in p["T4"]["NativeRefPinNet"]

def test_justified_DRC_ignored_checks_remain_visible_not_automatically_suppressed():
    report=obj(REPORT)
    assert len(report["fabrication_drc_ignored_checks"])==5
    assert "missing_courtyard" in report["fabrication_drc_ignored_checks"]

def test_package_sources_hashes_and_zip_are_current():
    report=obj(REPORT)
    assert len(report["package_sha256"])>=12
    for filename,expected in report["package_sha256"].items():
        assert sha(V4/filename)==expected
    path=V4/"G0_V4_157_PART_INDEPENDENT_SCHEMATIC_EDITABLE_KICAD_NOT_FOR_FAB.zip"
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None
        assert len(z.namelist())>=14
        assert set(report["package_sha256"])<=set(z.namelist())
        for filename,digest in report["package_sha256"].items():
            assert hashlib.sha256(z.read(filename)).hexdigest()==digest

@pytest.mark.parametrize("flag",[
  "manufacturing_magnetics_physical_pin_DOT_approved",
  "physical_isolation_clearance_and_dielectric_verified",
  "real_dual_12v_supply_and_uvlo_integrated",
  "hardware_48v_estop_and_hs_vgs_monitor_integrated",
  "high_current_copper_losses_EMC_thermal_verified",
  "60_gate_fault_witness_waveforms_measured",
  "G0_signed","G1_signed","fab_release","energization_allowed",
])
def test_pcb_and_ERC_green_never_release_unverified_power_stage(flag):
    assert obj(REPORT)[flag] is False

def test_g0_gate_receipt_stays_blocked_despite_latest_V4_green():
    g=obj(ROOT/"design/v3/stage_f/d1_lane_c_g0/g0_integration_acceptance_NOT_FOR_FAB.json")
    assert g["latest_native_mainboard_G0_V4"]["pcb_unconnected"]==0
    assert g["latest_native_mainboard_G0_V4"]["g0_remains_blocked"] is True
    assert g["gate_0_approved"] is False and g["energization_allowed"] is False
    assert len(g["obligations"])==9 and all(v["status"]=="PENDING" for v in g["obligations"])

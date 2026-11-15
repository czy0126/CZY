"""Native Traco THN30 2-module 2-layer bias carrier, fail-closed CAD acceptance."""
from __future__ import annotations
import csv,hashlib,json,zipfile,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"hardware/dcx_main/g2/d1_g0_dual_THN30_bias_carrier_NOT_FOR_FAB"
NAME="d1_g0_2xTHN30_48V_to_isolated_12V_P_S_CARRIER_NOT_FOR_FAB"
PCB=OUT/(NAME+".kicad_pcb")
RECEIPT=OUT/"G0_dual_30W_isolated_bias_CAD_acceptance_NOT_FOR_FAB.json"
NET=OUT/(NAME+".net")
PHYSICAL=OUT/(NAME+"_physical_pin_and_copper_receipt.json")
ZIP=OUT/"G0_TWO_THN30_4812_REAL_BIAS_CARRIER_EDITABLE_KICAD_NOT_FOR_FAB.zip"
BOM=OUT/"G0_dual_30W_bias_carrier_vendor_MPN_UNQUALIFIED.csv"

def obj(p):return json.loads(p.read_text("utf-8"))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def test_native_oem_pin_positions_match_kicad_installed_vendor_geometry():
    d=obj(PHYSICAL)
    assert d["OEM_module_pin_layout"]=={
       "1":[0.,0.],"2":[5.08,0.],"3":[-7.62,20.32],
       "4":[2.54,20.32],"5":[12.7,20.32],"6":[12.7,0.]}
    assert d["module_P_N"]=="THN 30-4812"
    assert d["native_footprints"]==13
    assert d["native_KiCad_DRC_violations"]==0
    assert d["native_KiCad_unconnected"]==0

def test_dual_48v_fuses_have_no_input_bypass_nor_crossed_returns():
    d=obj(PHYSICAL)["independent_ref_pin_net"]
    assert d["J_IN"]=={"1":"VIN48_PRE","2":"PGND"}
    assert d["F1"]=={"1":"VIN48_PRE","2":"VIN48P_F"}
    assert d["F2"]=={"1":"VIN48_PRE","2":"VIN48S_F"}
    assert d["U1"]=={"1":"VIN48P_F","2":"PGND","3":"VCC12",
                     "4":"","5":"PGND","6":""}
    assert d["U2"]=={"1":"VIN48S_F","2":"PGND","3":"VCC12_S",
                     "4":"","5":"SR_SOURCE_RETURN","6":""}
    assert d["J_P"]=={"1":"VCC12","2":"PGND"}
    assert d["J_S"]=={"1":"VCC12_S","2":"SR_SOURCE_RETURN"}
    assert d["C_S1"]==d["C_S2"]=={"1":"VCC12_S","2":"SR_SOURCE_RETURN"}
    assert d["C_P1"]==d["C_P2"]=={"1":"VCC12","2":"PGND"}

def test_native_sch_independent_pin_parity_34_and_integrity_erc_zero():
    r=obj(RECEIPT)
    assert r["status"].startswith("TWO_REAL_THN30")
    assert r["native_board_footprints"]==13
    assert r["native_schematic_independent_pin_parity"]==34
    assert r["native_ERC_violations"]==0
    assert r["native_PCB_unconnected"]==r["native_PCB_DRC_violations"]==0
    assert r["module_6_PIN_pad_geometry_verified_against_installed_KiCad"] is True

def test_physical_bias_board_not_equated_with_safety_power_disconnect():
    r=obj(RECEIPT)
    assert r["fuses_recommended_2A_slow_but_MPN_breaking_inrush_QUALIFIED"] is False
    assert r["Traco_remote_NC_opencircuit_defaults_ON"] is True
    assert r["physical_48v_main_power_contact_ESTOP_present"] is False
    assert r["remote_power_fault_shutdown_and_UVLO_implemented"] is False
    assert r["G0_bias_verified_physical_30W_each_and_heat"] is False
    assert r["outer_1200V_isolation_creepage_EMC_and_input_surge_certified"] is False
    assert r["main_V5_bias_connector_mating_verified"] is False
    assert r["fabrication_approved"] is r["energization_allowed"] is r["G0_approved"] is False

def test_two_modules_and_2p5a_terminal_data_in_bom():
    with BOM.open(newline="",encoding="utf-8") as f:
        rows={r["Ref"]:r for r in csv.DictReader(f)}
    assert len(rows)==13
    assert rows["U1"]["Intended_MPN"]==rows["U2"]["Intended_MPN"]=="THN 30-4812"
    assert all("TRACO_THN30" in rows[u]["KiCad_OEM_Footprint"] for u in ("U1","U2"))
    assert all("SLOW" in rows[f]["Intended_MPN"] for f in ("F1","F2"))
    assert "VCC12_S" in rows["J_S"]["PinNet"]
    assert "SR_SOURCE_RETURN" in rows["J_S"]["PinNet"]

def test_zip_and_CAD_hashes_not_changed_since_verified_original():
    r=obj(RECEIPT)
    assert len(r["native_data_SHA256"])>=10
    assert all(sha(OUT/name)==h for name,h in r["native_data_SHA256"].items())
    with zipfile.ZipFile(ZIP) as z:
        assert z.testzip() is None
        assert len(z.infolist())>=11
        for name,h in r["native_data_SHA256"].items():
            assert hashlib.sha256(z.read(name)).hexdigest()==h

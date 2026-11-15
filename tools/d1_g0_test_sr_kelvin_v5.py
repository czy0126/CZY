"""G0 V5 real KiCad SR Kelvin + manufacturer REG cap CAD verification."""
from __future__ import annotations
import csv,hashlib,json,zipfile,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
G2=ROOT/"hardware/dcx_main/g2"
V5=G2/"d1_g0_UCC24624_KELVIN_V5_INTEGRATED_MAINBOARD_NOT_FOR_FAB"
RAW=G2/"d1_g0_UCC24624_KELVIN_V5_NOT_FOR_FAB"
BOARD=V5/"d1_g0_161_PART_SR_KELVIN_SOURCE_AUTHORED_NOT_FOR_FAB.kicad_pcb"
RECEIPT=V5/"V5_integrated_KiCad_ERC_DRC_isolation_gate_NOT_FOR_FAB.json"
BOM=V5/"G0_V5_161_NATIVE_PINNET_BOM_UNQUALIFIED.csv"
SRC=V5/"V5_source_authored_441_PIN_SCH_receipt.json"
PHYS=V5/"V5_source_kelvin_physical_ECO_receipt.json"
ZIP=V5/"G0_V5_161_PART_KELVIN_SOURCE_AUTHORED_EDITABLE_KICAD_NOT_FOR_FAB.zip"

def data(p):return json.loads(p.read_text("utf-8"))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def test_v5_161_footprints_441_idependent_pin_erc_drc_zero():
    r=data(RECEIPT)
    assert r["PCB_footprints"]==161
    assert r["schematic_independent_ref_pin_net_parity"]==441
    assert r["native_pcb_DRC_violations"]==0
    assert r["native_pcb_unconnected"]==0
    assert r["native_schematic_ERC_violations"]==0
    assert r["primary_secondary_copper_returns_separate"] is True
    assert r["source_V4_PCB_SHA"]==sha(G2/"d1_g0_INDEPENDENT_SOURCE_V4_MAINBOARD_NOT_FOR_FAB/d1_g0_157_PART_INDEPENDENT_SOURCE_MAINBOARD_NOT_FOR_FAB.kicad_pcb")

def test_ucc24624_vss_5_not_joined_with_high_current_pgnd_pin2():
    phys=data(PHYS)
    assert phys["four_SR_VSS_Kelvin_nets_present"] is True
    assert phys["four_0R_kicad_resistor_footprints_present"] is True
    assert phys["KiCad_native_DRC_violations"]==0
    assert phys["KiCad_native_unconnected"]==0
    assert len(phys["physical_layout"])==4
    assert {x["VSS_sense_pin5"] for x in phys["physical_layout"]}=={
      "SR_KELVIN_1","SR_KELVIN_2","SR_KELVIN_3","SR_KELVIN_4"}
    assert all(x["gate_current_return_pin2"]=="SR_SOURCE_RETURN" for x in phys["physical_layout"])
    assert all(x["new_Kelvin_route_layer"]=="In9.Cu" for x in phys["physical_layout"])
    assert all(x["source_star_connection_physical_qualification"] is False for x in phys["physical_layout"])

def test_2u2_reg_caps_vendor_mpns_and_0r_are_real_bom_items():
    with BOM.open(newline="",encoding="utf-8") as f:
        r={x["Ref"]:x for x in csv.DictReader(f)}
    assert len(r)==161
    for i in range(1,5):
        cap=r[f"C{i+6}"]
        assert "GRM188C71E225KE11" in cap["Value"] and cap["Design_MPN_NOT_FOR_FAB"]=="GRM188C71E225KE11"
        assert cap["Pad_NetPassport"]==f"1=REG{i};2=SR_SOURCE_RETURN"
        sens=r[f"RK{i}"]
        assert sens["DNP"]=="no"
        assert sens["Design_MPN_NOT_FOR_FAB"]=="Yageo RC0603JR-070RL 0R"
        assert sens["Pad_NetPassport"]==f"1=SR_SOURCE_RETURN;2=SR_KELVIN_{i}"
        u=r[f"U{i+2}"]
        assert f"5=SR_KELVIN_{i}" in u["Pad_NetPassport"]
        assert "2=SR_SOURCE_RETURN" in u["Pad_NetPassport"]
    assert {x["Ref"] for x in r.values() if x["DNP"]=="yes"}=={"R8"}

def test_kicad_independent_schematic_receipt_is_not_an_actual_functional_signoff():
    r=data(SRC)
    assert r["independent_device_count"]==161
    assert r["independent_native_schematic_pin_parity"]==441
    assert r["native_KiCad_ERC_violations"]==0
    assert r["physical_native_board_ref_pin_net_equal_to_design"] is True
    assert r["UCC24624_pin5_VSS_separate_from_pin2_PGND"] is True
    assert r["REG_actual_effective_cap_at_11V_verified"] is False
    assert r["safety_protection_full_schematic_qualified"] is False

def test_kicad_native_packaged_sha_is_byte_exact():
    report=data(RECEIPT)
    assert len(report["sha256"])>=12
    assert all(sha(V5/k)==v for k,v in report["sha256"].items())
    with zipfile.ZipFile(ZIP) as z:
        assert z.testzip() is None
        assert len(z.namelist())>=13
        assert all(hashlib.sha256(z.read(k)).hexdigest()==v for k,v in report["sha256"].items())

@pytest.mark.parametrize("flag",[
   "REG_2u2_effective_at_11v_and_kelvin_switching_noise_verified",
   "input_48v_to_12v_isolated_modules_built_in",
   "physical_power_estop_and_high_side_monitor_present",
   "12_layer_stackup_and_via_DFM_qualified",
   "vendor_magnetics_pin_DOT_and_insulation_qualified",
   "60_actual_fault_waveforms_measured",
   "energization_allowed","G0_approved","fabrication_approved",
])
def test_native_kicad_drc_zero_does_not_bypass_physical_safety(flag):
    assert data(RECEIPT)[flag] is False

def test_all_five_ignored_kicad_drc_checks_stay_visible():
    d=data(RECEIPT)
    assert len(d["ignored_KiCad_DRC_categories"])==5
    assert "missing_courtyard" in d["ignored_KiCad_DRC_categories"]

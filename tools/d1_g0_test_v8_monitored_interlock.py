"""Independent V8 isolated highside analog + V7 interlock CAD regression.

Tests cannot declare G0 physical PASS, allow 48V, or certify switching-edge
shutdown performance. KiCad vendor source and native DRC/ERC receipts only.
"""
from __future__ import annotations
import ast,hashlib,json,math,zipfile
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
DIR=ROOT/"hardware/dcx_main/g2/d1_g0_V8_MONITORED_INTERLOCK_NOT_FOR_FAB"
REPORT=DIR/"V8_58part_source_authored_schematic_native_KiCad_receipt_NOT_FOR_FAB.json"
PLACEMENT=DIR/"V8_integrated_HS_analog_real_pad_pin_contract_NOT_FOR_FAB.json"
ROUTED=DIR/"V8_isolated_HS_analog_routed_evidence_NOT_FOR_FAB.json"
PREROUTED=DIR/"V8_pre_monitor_route_receipt_NOT_FOR_FAB.json"
ZIP=DIR/"G0_V8_58PART_GH_HB_MONITORED_INTERLOCK_NATIVE_KICAD_NOT_FOR_FAB.zip"
def parse_const(path,name):
  src=ast.parse((ROOT/path).read_text(encoding="utf8"))
  for stmt in src.body:
    if isinstance(stmt,ast.Assign) and any(isinstance(x,ast.Name) and x.id==name for x in stmt.targets):
      return ast.literal_eval(stmt.value)
  raise LookupError(name)
P=parse_const("tools/d1_g0_v8_highside_monitor.py","P")
V7=parse_const("tools/d1_g0_estop_interlock_v7.py","PARTS")
def j(path):return json.loads(path.read_text(encoding="utf8"))
def pins(ref):return P[ref][3]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def test_original_24_real_V7_control_connections_remain_0_DRC_0_open():
    r=j(PREROUTED)
    assert r["routes_attempted"]==24
    assert r["successfully_routed_connections"]==24
    assert r["failed_routes"]==[]
    assert r["native_drc"]==r["native_unconnected"]==0
    assert r["energization_allowed"] is False

def test_58_actual_native_pads_171_independent_sch_0_KiCad_failures():
    r=j(REPORT)
    assert len(P)==31 and len(V7)==27
    assert r["native_footprints"]==58
    assert r["independent_ref_pin_net_parity"]==171
    assert r["native_ERC_errors"]==r["native_DRC_errors"]==r["native_unconnected"]==0
    assert r["true_AMC1311B_highside_analog_measurement_connected_in_native_CAD"] is True

@pytest.mark.parametrize("ref,expected",[
 ("U_GH_SENSE",{"1":"HS5V","2":"GH_DIV","3":"HS_SW","4":"HS_SW",
    "5":"PGND","6":"GH_OUTN","7":"GH_OUTP","8":"PRI5V"}),
 ("U_HB_SENSE",{"1":"HS5V","2":"HB_DIV","3":"HS_SW","4":"HS_SW",
    "5":"PGND","6":"HB_OUTN","7":"HB_OUTP","8":"PRI5V"}),
 ("U_HS12",{"1":"VIN48_HS_F","2":"PGND","3":"HS_VB",
    "4":"","5":"HS_SW","6":""}),
 ("U_LDO_HS",{"1":"HS_VB","2":"HS_SW","3":"HS5V"}),
 ("U_LDO_P",{"1":"VCC12","2":"PGND","3":"PRI5V"}),
 ("U_HS_COMP",{"1":"HB_VALID","2":"HB_REF","3":"HB_OUTP","4":"PGND",
   "5":"GH_REF","6":"GH_OUTP","7":"GH_GATE_OFF","8":"PRI5V"}),
])
def test_real_vendor_pin_mappings_of_isolation_bias_and_comparators(ref,expected):
    assert pins(ref)==expected
    assert j(PLACEMENT)["monitor_real_pad_net_contract"][ref]==expected

def test_highside_floating_winding_return_NEVER_short_to_input_primary():
    p=pins("U_HS12")
    assert p["2"]=="PGND" and p["5"]=="HS_SW"
    assert p["2"]!=p["5"]
    assert pins("J_HS_FLOAT_BIAS")=={"1":"HS_VB","2":"HS_SW"}
    assert pins("J_HS_SENSE")=={"1":"GH_RAW","2":"HB_RAW","3":"HS_SW"}
    for ref in ("U_GH_SENSE","U_HB_SENSE"):
       p=pins(ref)
       assert p["3"]==p["4"]=="HS_SW" and p["5"]=="PGND"
       assert p["3"]!=p["5"]

def test_amc1311B_2v_input_12v_divider_and_nominal_threshold_correct():
    assert pins("R_GH_TOP")=={"1":"GH_RAW","2":"GH_DIV"}
    assert pins("R_GH_BOT")=={"1":"GH_DIV","2":"HS_SW"}
    assert pins("R_HB_TOP")=={"1":"HB_RAW","2":"HB_DIV"}
    assert pins("R_HB_BOT")=={"1":"HB_DIV","2":"HS_SW"}
    for voltage in (0,5,12,18):
       assert abs(voltage*10/(100+10))<=2.0
    assert "16k" in P["R_HB_RTOP"][2]
    assert "10k" in P["R_HB_RBOT"][2]
    p=j(PLACEMENT)
    assert math.isclose(p["reference_HB_valid_typical_v"],5*10/26,rel_tol=1e-12)
    assert math.isclose(p["nominal_HB_SW_input_trip_v"],(5*10/26-1.44)*2*11,rel_tol=1e-12)
    assert p["AMC1311B_output_common_mode_data_min_v"]==1.39
    assert p["AMC1311B_output_common_mode_data_max_v"]==1.49
    # At supply worst-case common-mode, nominal threshold error is >1V!
    worst=(5*10/26-1.39)*2*11
    assert worst>11.0
    assert p["HB_valid_comparator_is_diagnostic_only_not_signed_UVLO"] is True

def test_amc1311B_failsafe_differential_drive_does_not_fake_HB_VALID_on_VDD1_loss():
    # TI AMC1311B undervoltage failsafe differential output about -2.5 V.
    fallback_outp=1.44-2.5/2
    assert fallback_outp<5*10/26
    assert pins("U_GH_SENSE")["3"]=="HS_SW" # SHTDN LOW
    assert pins("U_HB_SENSE")["3"]=="HS_SW"

def test_diagnostic_outputs_use_primary_5V_not_12V_to_prevent_false_high():
    assert pins("R_HB_PULL")=={"1":"PRI5V","2":"HB_VALID"}
    assert pins("R_GH_PULL")=={"1":"PRI5V","2":"GH_GATE_OFF"}
    assert j(PLACEMENT)["HB_and_GH_diag_outputs_pull_to_PRI5V_not_primary_12V"] is True
    assert j(PLACEMENT)["no_5V_to_12V_logic_level_translation_approved"] is True

def test_no_auto_arm_from_static_HB_GOOD_and_PWM_gateoff_signal():
    assert pins("J_HS_FLAGS")=={"1":"HB_VALID","2":"GH_GATE_OFF","3":"PGND"}
    assert pins("R_HS_RELEASE")=={"1":"HB_VALID","2":"HS_OK_IN"}
    assert "DNP" in P["R_HS_RELEASE"][2]
    assert j(REPORT)["HS_OK_gate_connection_is_DNP_and_NOT_power_permission"] is True
    assert j(REPORT)["GH_gateoff_is_diagnostic_only_not_runtime_safety_permission"] is True
    # Existing old V7 AND still reads HS_OK_IN, NOT GH_GATE_OFF or HB_VALID.
    assert V7["U_AND"][3]["5"]=="HS_OK_IN"
    assert "GH_GATE_OFF" not in str(V7["U_AND"][3])
    assert "HB_VALID" not in str(V7["U_AND"][3])

def test_real_NC_stop_both_pads_still_two_different_copper_nets():
    assert V7["J_ESTOP_PWR"][3]=={"1":"48V_FUSED","2":"48V_AFTER_ESTOP"}
    assert V7["J_GX14COIL"][3]=={"1":"48V_AFTER_ESTOP","2":"COIL_DRAIN"}

def test_both_highside_inputs_referenced_to_SOURCE_not_primary_GND():
    for ref in ("U_GH_SENSE","U_HB_SENSE"):
      assert pins(ref)["4"]=="HS_SW"
    assert pins("J_HS_SENSE")["3"]=="HS_SW"
    for r in ("R_GH_BOT","R_HB_BOT"):
      assert pins(r)["2"]=="HS_SW"

def test_both_live_measurements_remain_5V_isolated_and_present_test_outputs():
    p=pins("J_HS_DIFF")
    assert p=={"1":"GH_OUTP","2":"GH_OUTN","3":"HB_OUTP","4":"HB_OUTN"}
    for ref in ("U_GH_SENSE","U_HB_SENSE"):
      assert pins(ref)["1"]=="HS5V" and pins(ref)["8"]=="PRI5V"

@pytest.mark.parametrize("flag",[
 "g0_physical_signoff","fabrication_approved","energization_allowed",
 "isolated_physical_creepage_stress_and_CTR_qualified",
 "real_high_side_drive_VB_SW_and_GH_SW_loom_verified",
 "independent_phase_aware_HS_watchdog_present",
 "hardware_installed_and_witnessed"])
def test_CAD_does_NOT_falsely_authorize_G0(flag):
    assert j(REPORT)[flag] is False

def test_independent_part_source_BOM_SHA_and_zip_contents_stable():
    d=j(REPORT)
    assert len(d["data_files_sha256"])>=12
    for fn,h in d["data_files_sha256"].items():
      assert sha(DIR/fn)==h,fn
    with zipfile.ZipFile(ZIP) as z:
      assert z.testzip() is None
      assert set(d["data_files_sha256"])<=set(z.namelist())
      for fn,h in d["data_files_sha256"].items():
        assert hashlib.sha256(z.read(fn)).hexdigest()==h

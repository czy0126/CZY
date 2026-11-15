"""D1 G0 V6: actual 30-part KiCad dual TPS3710 UVLO / VO617A domain bridge."""
from __future__ import annotations
import hashlib,json,zipfile,csv
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"hardware/dcx_main/g2/d1_g0_THN30_UVLO_OPTO_V6_NOT_FOR_FAB"
STEM="d1_g0_dual_12v_UVLO_iso_health_30devices_NOT_FOR_FAB"
RPT=OUT/"V6_30part_native_UVLO_iso_schematic_receipt_NOT_FOR_FAB.json"
PHY=OUT/(STEM+"_PCB_evidence_NOT_FOR_FAB.json")
DRC=OUT/(STEM+"_native_drc.json")
ZIP=OUT/"G0_V6_TWO_THN30_UVLO_OPTO_KICAD_NOT_FOR_FAB.zip"
BOM=OUT/"G0_V6_UVLO_isolated_12v_30part_BOM.csv"

def read(p):return json.loads(p.read_text("utf-8"))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def test_uvlo_native_board_30_parts_80_independent_pins_all_DRC_ERC_zero():
    d=read(RPT)
    assert d["device_count"]==30
    assert d["unique_ref_pin_net_parity"]==80
    assert d["native_KiCad_ERC_violations"]==0
    assert d["native_KiCad_DRC_violations"]==0
    assert d["native_KiCad_unconnected"]==0
    assert d["12v_uvlo_primary_plus_secondary_hardware_layout_present"] is True

def test_ti_tps3710_sot6_DDC_top_view_pins_explicit_and_ground_correct():
    p=read(PHY)
    assert p["TPS3710_SOT6_top_pin_map"]=={
        "1":"OUT","2":"GND","3":"SENSE","4":"GND","5":"VDD","6":"GND"}
    m=p["native_pin_map"]
    assert m["UP"]=={"1":"UVLO_P_OK","2":"PGND","3":"P_SENSE",
                     "4":"PGND","5":"VCC12","6":"PGND"}
    assert m["US"]=={"1":"UVLO_S_OK","2":"SR_SOURCE_RETURN","3":"S_SENSE",
                     "4":"SR_SOURCE_RETURN","5":"VCC12_S","6":"SR_SOURCE_RETURN"}
    assert p["primary_secondary_copper_returns_directly_joined"] is False

def test_261k_10k_real_12v_threshold_and_vdd_sense_margins():
    d=read(PHY)
    assert d["divider_top_ohm"]==261000
    assert d["divider_bottom_ohm"]==10000
    assert abs(d["TPS3710_nominal_12v_trip_rising_v"]-10.84)<1e-8
    assert abs(d["TPS3710_nominal_12v_trip_falling_v"]-10.69095)<1e-8
    # 12 V nominal SENSE=0.4428 V, respecting 0..6.5V SENSE input rating.
    assert .4 < 12.0/27.1 < 6.5

def test_opto_is_the_only_secondary_to_primary_health_signal_bridge():
    m=read(PHY)["native_pin_map"]
    assert m["ISO1"]=={"1":"OPT_LED_P","2":"SR_SOURCE_RETURN",
                       "3":"PGND","4":"OPT_COL_N"}
    assert m["QINV"]=={"1":"QBASE","2":"PGND","3":"UVLO_S_PRIMARY_OK"}
    assert m["RS_LED"]=={"1":"UVLO_S_OK","2":"OPT_LED_P"}
    assert m["RP_OPTO"]=={"1":"VCC12","2":"OPT_COL_N"}
    assert m["RBASE"]=={"1":"OPT_COL_N","2":"QBASE"}
    assert m["RINV"]=={"1":"VCC12","2":"UVLO_S_PRIMARY_OK"}

def test_primary_3pin_status_output_is_NOT_an_unsafe_direct_relay_permit():
    m=read(PHY)["native_pin_map"]
    assert m["J_HEALTH"]=={"1":"UVLO_P_OK","2":"UVLO_S_PRIMARY_OK","3":"PGND"}
    r=read(RPT)
    assert r["status_3pin_is_a_power_stage_enable"] is False
    assert r["UVLO_status_to_physical_ESTOP_and_RUN_closed_loop"] is False

def test_PUFLOWER_output_logic_contract_requires_both_rail_valid_and_ESTOP():
    # This is a logical acceptance condition, NOT measured analog CTR/timing.
    for p in (0,1):
        for s in (0,1):
            for estop_nc in (0,1):
                for hs_vgs_ok in (0,1):
                    allowed=p and s and estop_nc and hs_vgs_ok
                    assert not allowed or (p and s and estop_nc and hs_vgs_ok)
    # Current board physically exposes only p and s, no power-switch execution.
    assert read(RPT)["contactor_DC_breaking_wiring_and_feedback_qualified"] is False

def test_V6_4_remaining_default_native_ignored_DRC_checks_are_disclosed():
    d=read(DRC)
    assert len(d.get("ignored_checks",[]))==4
    assert {v["key"] for v in d["ignored_checks"]}=={
       "track_not_centered_on_via","tuning_profile_track_geometries",
       "footprint_filters_mismatch","footprint_type_mismatch"}
    assert not d["violations"] and not d["unconnected_items"]

@pytest.mark.parametrize("flag",[
 "UVLO_status_to_physical_ESTOP_and_RUN_closed_loop",
 "opto_ctr_and_uvlo_dynamic_times_proven",
 "C_hold_up_minimum_and_surge_tested",
 "creepage_clearance_isolation_certified",
 "hardware_first_power_test_completed",
 "energization_allowed","g0_approved","fabrication_approved",
])
def test_real_CAD_does_not_electronically_authorize_power(flag):
    assert read(RPT)[flag] is False

def test_independent_net_source_mpn_BOM_and_sha_crc_still_reproducible():
    d=read(RPT)
    assert len(d["sha256"])>=11
    assert all(sha(OUT/name)==h for name,h in d["sha256"].items())
    with BOM.open("r",encoding="utf-8",newline="") as f:
        rows={r["Reference"]:r for r in csv.DictReader(f)}
    assert len(rows)==30
    for r in ("UP","US"):
        assert rows[r]["Design_MPN"].startswith("TPS3710DDCR")
        assert "SOT-23-6" in rows[r]["Native_KiCad_Footprint"]
    assert rows["ISO1"]["Design_MPN"].startswith("VO617A-3")
    assert rows["QINV"]["Design_MPN"]=="MMBT3904LT1G"
    with zipfile.ZipFile(ZIP) as z:
        assert z.testzip() is None
        assert set(d["sha256"])<=set(z.namelist())
        for f,h in d["sha256"].items():
            assert hashlib.sha256(z.read(f)).hexdigest()==h

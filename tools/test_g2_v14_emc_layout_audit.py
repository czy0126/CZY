"""V14 current physical placement and EMC audit guard regression tests."""
import json
from pathlib import Path

import pytest

from g2_v14_emc_layout_audit import build,sha,NATIVE,READ,POUR,OUTPUT,REPORT,EXPECTED_SHA


def test_native_board_audit_and_emc_gate_not_qualified():
    d=build()
    assert d["source_sha256"]==EXPECTED_SHA
    assert d["PCB_count"]=={"components":149,"pads":423,"lines":484,"vias":104}
    assert d["native_DRC_Connection_Error_count"]==111
    assert d["native_DRC_Netlist_Error_count"]==0
    assert d["routing_complete"] is False
    assert d["EMC_measured_and_passed"] is False
    assert d["manufacturing_release"] is False


def test_true_native_input_hot_loop_has_long_separation_and_unrouted_vin():
    d=build()
    assert 41.5<d["input_Cin_VIN_to_QH_VIN_nearest_pads_mm"]<42.5
    assert 36.5<d["input_Cin_PGND_to_QL_PGND_nearest_pads_mm"]<37.0
    assert d["VIN_P_top_and_bottom_track_count"]==0
    assert d["VIN_P_via_count"]==0
    assert d["open_connections_per_net"]["VIN_P"]==3


def test_halfbridge_and_resonant_group_not_mistaken_for_small_loop():
    d=build()
    assert d["QH_QL_centers_mm"]==9.0
    assert 46.0<d["Lr_to_Cr_centers_mm"]<46.2
    assert 49.4<d["Lr_to_CT_LR_anonymous_pad_mm"]<49.7


def test_no_pours_or_inner_layers_even_though_12_layer_native_board():
    d=build()
    assert len(d["native_12_layer_enables"])==12
    assert d["trace_counts_by_active_layer"]=={"1":409,"2":75}
    assert len(d["active_inner_layers_without_winding_tracks"])==10
    assert set(d["native_copper_Pour_Poured_Region_Fill"].values())=={0}
    assert d["native_DRC_rule_name"]=="JLCPCB Capability(Two Layers Board)"


def test_magnetic_slots_to_SR_switching_are_not_physically_close():
    d=build()
    assert len(d["core_to_SR_spacing"])==4
    for x in d["core_to_SR_spacing"]:
        assert 48.0<x["min_vertical_core_slot_end_y31_to_SR_power_pad_mm"]<48.3
        assert 62.0<x["core_center_to_SR_center_mm"]<62.5
    assert d["native_T1_to_T4_and_CT_actual_device_count"]==0
    assert d["native_anonymous_CT_pads"]==4


def test_real_bottom_caps_are_correct_but_emc_not_auto_qualified():
    d=build()
    assert [p["cap"] for p in d["actual_four_bottom_REG_caps"]]==["C7","C8","C9","C10"]
    assert all(.35<p["REG_pin_projected_gap_mm"]<.45 for p in d["actual_four_bottom_REG_caps"])
    assert d["open_connections_per_net"]["PGND"]==42
    assert d["PGND_via_count"]==8
    assert d["VOUT_via_count"]==74


def test_envelope_density_and_72_real_chb_locations():
    d=build()
    assert d["PCB_XY_mm"]==[155,131]
    assert d["area_mm2"]==20305
    assert d["200W_envelope_volume_L"]==0.32488
    assert d["200W_envelope_density_kW_per_L"]==0.616
    assert d["CHB_output_cap_count"]==72
    assert d["CHB_cap_center_x_range_mm"]==[7.5,145.5]
    assert d["CHB_cap_center_y_range_mm"]==[99.0,124.6]


def test_source_lock_rejects_a_drifted_native_binary(tmp_path,monkeypatch):
    import g2_v14_emc_layout_audit as a
    bad=tmp_path/"wrong-native.eprj2"
    bad.write_bytes(b"bad data")
    monkeypatch.setattr(a,"NATIVE",bad)
    with pytest.raises(ValueError,match="source lock"):
        a.build()


def test_output_report_generated_and_not_fabrication_signoff():
    d=json.loads(OUTPUT.read_text("utf8"))
    assert d["source_sha256"]==sha(NATIVE)
    assert d["source_live_pour_sha256"]==sha(POUR)
    assert d["source_readback_sha256"]==sha(READ)
    text=REPORT.read_text("utf8")
    assert "48.18mm" in text
    assert "0.616" in text
    assert "VIN_P" in text
    assert "EMC" in text
    assert "NOT_FOR_FAB" in text

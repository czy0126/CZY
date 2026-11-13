"""D1 V17: synchronized placement, PGND and output-return regression gates."""
from __future__ import annotations
import json
import pytest

import g2_v16_floorplan_screen as source
import g2_v17_compact_emc_screen as layout
import g2_v17_pgnd_power_route_screen as power


def test_source_locked_native_board_and_real_149_device_placement():
    d=layout.generate()
    assert d["source_v15_native_sha256"]==source.EXPECTED_V15_SHA256
    assert d["real_native_components_placed"]==149
    assert d["real_native_associated_pads_checked"]==419
    assert d["chb_cap_count"]==72
    assert d["board_envelope_candidate_mm"]==[155.,113.,16.]
    assert d["relative_geometric_density_increase_pct"]>15
    assert d["candidate_nominal_envelope_density_kW_L"]==.714


def test_every_compact_layout_keepout_and_trial_courtyard_is_unviolated():
    d=layout.generate()
    assert d["cross_net_pad_clearance_fail_count"]==0
    assert not d["slot_to_pad_conflicts"]
    assert not d["core_body_to_component_pad_failures"]
    assert not d["cap_envelope_in_output_throat"]
    assert not d["cap_envelope_too_close_to_board_edge"]
    assert not d["trial_nonbank_courtyard_pad_envelope_conflicts"]
    assert len(d["new_true_npth_slot_list_with_keepouts_mm"])==12


def test_full_source_real_44_pgnd_errors_are_not_misreported_as_closed():
    d=power.generate()
    assert d["native_original_pgnd_DRC"]["native_pgnd_unconnected_count"]==44
    assert d["native_original_pgnd_DRC"]["distinct_named_pgnd_pads_in_v15_readback"]==146
    assert d["native_original_pgnd_DRC"]["PGND_is_currently_one_net_and_not_galvanically_isolated"]
    assert not d["native_DRC_pgnd_zero_verified"]
    assert not d["native_V17_PCB_saved"]


def test_pgnd_and_vout_via_in_pad_candidates_are_net_preserving():
    d=power.generate()
    assert d["planned_via_count_by_net"]=={"PGND":168,"VOUT":144}
    assert len(d["planned_via_in_pad_sites"])==312
    assert d["via_to_unlike_net_pad_conflict_count"]==0
    assert d["via_to_named_plane_fail_count"]==0
    assert all(p["radius_mm"]>p["drill_mm"]/2 for p in d["planned_via_in_pad_sites"])
    assert set(p["net"] for p in d["planned_via_in_pad_sites"])=={"PGND","VOUT"}
    assert len({p["ref"] for p in d["planned_via_in_pad_sites"] if p["ref"].startswith("SR")})==8
    assert len({p["ref"] for p in d["planned_via_in_pad_sites"] if p["ref"].startswith("CHB")})==72


def test_ground_and_output_copper_pours_are_both_contiguous_and_distinct():
    d=power.generate()
    g=d["inner_layer_pgnd_copper"]
    v=d["inner_layer_vout_copper"]
    assert g["still_one_connected_polygon"] and v["still_one_connected_polygon"]
    assert g["nominal_EasyEDA_layer_id"]!=v["nominal_EasyEDA_layer_id"]
    assert g["total_opposite_VOUT_antipads"]==145
    assert v["total_opposite_PGND_antipads"]==169
    assert not g["actual_native_polygon_created"]
    assert not v["actual_native_polygon_created"]
    assert d["require_vendor_multi_contact_busbar_terminals"] is True


def test_shorted_input_primary_return_is_explicitly_clearance_screened():
    d=power.generate()
    assert d["input_pgnd_to_QL_pad_target"]["from_ref"]=="Cin.2"
    assert d["input_pgnd_to_QL_pad_target"]["to_ref"].startswith("QL.")
    assert not d["input_pgnd_to_QL_pad_target"]["approx_net_conflict_list"]
    assert d["input_pgnd_to_QL_pad_target"]["width_mm"]==.9
    assert d["input_pgnd_to_QL_pad_target"]["actual_copper_created"] is False


def test_ideal_power_bus_screen_cannot_approve_real_100a_copper():
    d=power.generate()
    c=d["paired_100A_copper_insert_screen"]
    assert c["ideal_bipolar_R_mohm"]==.0684
    assert c["ideal_bipolar_losses_at_100A_W"]==pytest.approx(.684,abs=.001)
    assert not c["joint_via_contact_spreading_loss_included"]
    assert not c["16mm_coldplate_stack_mechanical_verified"]
    assert not d["via_in_pad_plating_capping_vendor_signed"]
    assert not d["fab_release"]


def test_native_source_hash_drift_is_fatal(monkeypatch):
    monkeypatch.setattr(source,"EXPECTED_V15_SHA256","0"*64)
    with pytest.raises(ValueError,match="Native V15 source changed"):
        power.generate()

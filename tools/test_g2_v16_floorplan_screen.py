"""Regression gates for the source-locked V16 conceptual placement."""
import importlib.util
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import g2_v16_floorplan_screen as v16


def test_native_source_and_entire_fleet_are_covered():
    data=v16.generate()
    assert data["source_V15_native_sha256"] == v16.EXPECTED_V15_SHA256
    assert data["source_native_components"] == len(data["placement_all_components_mm"]) == 149
    assert data["relocated_component_count"] == 148  # J_OUT remains at original 76,116
    assert data["capacitor_bank_preserved"] == 72
    assert data["unassociated_native_pads_excluded_from_copied_placement_screen"] == 4
    assert len(data["core_slot_keepouts_mm"]) == 12
    assert len(data["right_bank_180deg_rotated_components"]) == 36


def test_source_true_pad_copper_and_shifted_slot_footprint_gates():
    data=v16.generate()
    assert data["native_pad_only_unlike_net_clearance_fail_count"] == 0
    assert data["new_slot_pad_keepout_conflict_count"] == 0
    assert not data["output_capacitor_throat_conflict_refs"]
    assert data["reserved_output_throat_xyxy_mm"] == [66.,86.,96.,126.]


def test_symmetric_72_cap_repack_and_original_pad_numbers_preserved():
    data=v16.generate()
    xy=data["placement_all_components_mm"]
    for row in range(6):
        refs=[f"CHB{12*row+j+1:02d}" for j in range(12)]
        assert len({tuple(xy[r]) for r in refs}) == 12
        left=sorted(xy[r][0] for r in refs if xy[r][0] < 76)
        right=sorted(xy[r][0] for r in refs if xy[r][0] > 76)
        assert len(left) == len(right) == 6
        assert all(round(a+b,4)==152 for a,b in zip(left,reversed(right)))
        assert len({xy[r][1] for r in refs}) == 1
    assert set(data["right_bank_180deg_rotated_components"]) == {
        ref for ref in xy if ref.startswith("CHB") and xy[ref][0] > 86
    }


def test_improvement_is_explicitly_only_a_pad_center_proxy():
    data=v16.generate()
    assert data["input_loop_pad_centres_sum_candidate_mm"] < 12
    assert data["input_loop_pad_centres_sum_before_mm"] > 75
    assert data["Lr_Cr_center_candidate_mm"] == 15.
    assert data["Lr_Cr_center_before_mm"] > 45
    assert data["T1_T4_slot_to_SR_SEC_y_candidate_mm"] < 15


def test_no_manufacturing_promotion_from_geometrical_or_ideal_copper_math():
    data=v16.generate()
    ideal=data["copper_insert_distributed_loss_screen"]
    assert 0 < ideal["two_pole_ideal_total_W"] < 2
    assert not ideal["thermal_EMI_and_MFG_verified"]
    assert not ideal["has_3D_current_spreading_contacts_vias_inductance"]
    for gate in ["full_native_SCH_PCB_rebuilt",
                 "all_native_electrical_routes_connected",
                 "native_12layer_stack_vendor_approved","fab_release"]:
        assert data[gate] is False
    assert data["status"].endswith("NOT_FOR_FAB")


def test_fail_closed_on_native_sha_mismatch(monkeypatch):
    monkeypatch.setattr(v16, "EXPECTED_V15_SHA256", "0"*64)
    with pytest.raises(ValueError, match="Native V15 source changed"):
        v16.generate()

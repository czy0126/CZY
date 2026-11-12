"""Eight-real-via native KiCad candidate tests: no shorted winding turn.

DRC is real KiCad CLI output, but layer-independent NET1 DRC alone cannot
prove 3 electrical series turns. Separate geometry checks are mandatory.
"""
from __future__ import annotations
import hashlib
import json

import pytest

import pcb_embedded_lr as parent
import pcb_embedded_lr_4via_trial as parallel


def test_original_two_via_board_geometry_is_unchanged_across_crlf_or_lf():
    # Git Windows autocrlf changes the working copy, not the source geometry.
    p=parent.PCB.read_text(encoding="utf-8").encode("utf-8")
    assert hashlib.sha256(p).hexdigest()==json.loads(
        parallel.REPORT.read_text(encoding="utf-8")
    )["parent_two_via_board_sha256"]
    assert parent.PCB.read_text(encoding="utf-8")==parent.contents()[0]


def test_independent_four_via_each_transition_has_expected_native_geometry():
    b,r=parallel.contents()
    assert parallel.BOARD.read_text(encoding="utf-8")==b
    assert parallel.REPORT.read_text(encoding="utf-8")==r
    row=json.loads(r)
    assert row["vias_per_transition"]==4
    assert row["total_transition_PTH"]==8
    assert row["new_PTH"]==6
    assert row["new_tracks"]==4
    assert b.count("(via (at ")==8
    assert b.count("(segment (start ")==46
    assert len(row["bridge_groups"])==2
    assert all(len(x["new_vias_mm"])==3 for x in row["bridge_groups"])
    assert all(len(x["additional_preceding_turn_stubs_on_layers"])==2
               for x in row["bridge_groups"])
    assert row["self_short_and_non_adjacent_through_barrel_screen_passed"]
    assert row["fabrication_approved"] is False
    assert row["real_current_distribution_among_vias_verified"] is False
    assert row["nonlinear_N97_100C_and_200kHz_AC_loss_verified"] is False
    assert row["power_board_CAD_integrated"] is False


def test_actual_kicad10_native_DRC_has_zero_violations_and_open_connections():
    assert parallel.DRC.is_file()
    body=parallel.DRC.read_text(encoding="utf-8",errors="replace")
    assert "** Found 0 DRC violations **" in body
    assert "** Found 0 unconnected pads **" in body
    assert "lib_footprint_issues" not in body


def test_all_six_layers_are_preserved_and_new_vias_stay_outside_foreign_turns():
    trial,plans,b=parallel.route_sites()
    assert len(plans)==2
    assert all(a["clearance_checked"] for a in plans)
    original=parent.PCB.read_text(encoding="utf-8")
    assert all(f'\"{layer}\"' in b for layer in parent.LAYER_NUM)
    for plan in plans:
        via_start=plan["original_endpoint_mm"]
        for point in plan["new_vias_mm"]:
            assert point[1]==via_start[1]
            assert point[0]<via_start[0]
            assert abs(point[0]-via_start[0])<5
    assert not trial["qualification"]["fabrication_approved"]


def test_pth_worst_case_loss_is_ideal_equal_share_and_never_release_claim():
    r=json.loads(parallel.REPORT.read_text(encoding="utf-8"))
    assert r["ideal_equal_sharing_four_vias_pdc_series_pair_W_UNQUALIFIED"]<.06
    assert r["ideal_100c_single_via_rated_dc_loss_W_at_25um"]>.10
    assert r["real_current_distribution_among_vias_verified"] is False
    assert r["plated_barrel_min_thickness_and_reliability_verified"] is False
    assert r["new_stubs_and_turn_2_effective_path_inductance_verified"] is False


def test_short_pitch_cannot_duplicate_or_overlap_via_bores(monkeypatch):
    monkeypatch.setattr(parallel,"PITCH_MM",.3)
    with pytest.raises(ValueError,match="overlaps"):
        parallel.route_sites()


def test_excessive_via_count_cannot_intrude_on_existing_board_terminal(monkeypatch):
    monkeypatch.setattr(parallel,"ADDITIONAL",32)
    with pytest.raises((ValueError,AssertionError),match="overlap|terminal|unrelated|touch|site|transition"):
        parallel.route_sites()


def test_hacked_parent_is_rejected_before_native_copy(monkeypatch,tmp_path):
    replacement=tmp_path/"winding.kicad_pcb"
    replacement.write_bytes(parent.PCB.read_bytes()+b"\n; changed")
    monkeypatch.setattr(parent,"PCB",replacement)
    with pytest.raises(ValueError,match="stale"):
        parallel.contents()

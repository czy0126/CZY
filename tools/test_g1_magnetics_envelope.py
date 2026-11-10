"""Native G1 3D magnetic-envelope prelayout gate regression tests.

This is geometry only. 0 physical native DRC violations cannot be used to
override occupied magnetic body envelope or to approve a 100A PCB.
"""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT/"tools/g1_magnetics_envelope.py"
spec = importlib.util.spec_from_file_location("g1_magnetic_envelope", FILE)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def baseline():
    p = gate.load_current()
    g = json.loads(gate.MAG.read_text(encoding="utf-8"))
    return p, g


def test_recomputed_structural_gate_matches_committed_native_readback():
    report = gate.report()
    committed = json.loads(gate.OUT.read_text(encoding="utf-8"))
    assert report == committed
    assert report["status"] == "P0_G1_MAGNETIC_PLACEMENT_ECO_REQUIRED"
    assert report["board_mm"] == [155.0,131.0]
    assert report["decisions"]["freeze_existing_lr_placement"] is False
    assert report["decisions"]["approve_g1_magnetic_assembly"] is False
    assert report["decisions"]["approve_g2_fab"] is False


def test_latest_reopened_98_line_board_has_22_pad_intersections():
    assert gate.load_current()["source_status"] == "ACTUAL_NATIVE_G1_KELVIN_REOPEN_READBACK"
    a = gate.report()
    lr = a["lr_elp38_candidate"]
    assert lr["physical_core_envelope_mm"] == [38.0,25.4]
    assert lr["current_body_xy_mm"] == {
        "left":1.0, "right":39.0, "top":39.3, "bottom":64.7
    }
    assert lr["native_footprint_pad_count"] == 2
    assert lr["native_footprint_pad_pitch_mm"] == pytest.approx(9.002, abs=.001)
    assert lr["minimum_board_edge_margin_mm"] == 1.0
    assert lr["board_edge_reserve_passed"] is False
    assert lr["other_pad_envelope_intersections"] == 22
    assert lr["other_ref_count"] == 11
    refs = {r["ref"] for r in lr["by_ref"]}
    assert refs == {"C10","C101","C102","C105","C106","C107",
                    "Cout","R1","R10","R2","R7"}
    assert "Lr" not in refs


def test_old_initial_placement_overstates_active_collisions():
    original = json.loads(gate.PADS.read_text(encoding="utf-8"))
    cfg = json.loads(gate.MAG.read_text(encoding="utf-8"))
    old = gate.report(original, cfg)
    live = gate.report()
    assert old["lr_elp38_candidate"]["other_pad_envelope_intersections"] == 30
    assert old["lr_elp38_candidate"]["other_ref_count"] == 15
    assert live["lr_elp38_candidate"]["other_pad_envelope_intersections"] == 22
    assert live["evidence"]["native_board_pad_readback"].endswith("kelvin_readback.json")
    assert live["evidence"]["active_copper_lines"] == 98
    assert live["evidence"]["active_vias"] == 18
    assert live["evidence"]["native_readback_git_blob_sha"] == gate.git_blob_sha(
        gate.ACTIVE_READBACK)


def test_current_native_source_rejects_a_stale_or_failed_cad_reopen(monkeypatch, tmp_path):
    raw = json.loads(gate.ACTIVE_READBACK.read_text(encoding="utf-8"))
    raw["ok"] = False
    path = tmp_path / "damaged_reopen.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(gate, "ACTIVE_READBACK", path)
    with pytest.raises(ValueError, match="reopen readback failed"):
        gate.load_current()


def test_native_polygons_are_real_world_xy_not_fake_millimeter_dimensions():
    pads, _ = baseline()
    polygon = next(p for p in pads["pads"] if p["Pad"][0] == "POLYGON")
    assert (polygon["ref"],polygon["PadNumber"]) == ("U2","11")
    poly_rect = gate.pad_rect(polygon)
    assert poly_rect["left"] > 130 and poly_rect["right"] < 135
    lr = gate.report()["lr_elp38_candidate"]["current_body_xy_mm"]
    dx, dy = gate.intersection(lr,poly_rect)
    assert dx == 0.0  # Y intervals may overlap; no 2D area without both axes
    assert dy >= 0.0


def test_current_elp32_transforms_have_six_mm_gap_but_elp38_does_not():
    p = gate.report()["transformer_envelopes"]
    assert p["present_design"] == "ELP32_32x20_3_1_1_GEOMETRY_PROXY"
    assert p["change_to_elp38_is_not_an_existing_design"] is True
    assert p["elp38_stretch_requires_placement_change"] is True
    assert len(p["adjacent_pairs"]) == 3
    assert p["elp38_if_all_four_single_row_required_board_width_mm"] == 164.0
    assert p["elp38_if_all_four_single_row_shortfall_mm"] == 9.0
    for x in p["adjacent_pairs"]:
        assert x["current_elp32_gap_mm"] == 6.0
        assert x["if_changed_to_elp38_gap_mm"] == 0.0


def test_moving_a_real_pad_out_of_the_body_changes_gate():
    pad_dump, m = baseline()
    moved = copy.deepcopy(pad_dump)
    a = next(p for p in moved["pads"]
             if p["ref"] == "C10" and p["PadNumber"] == "1")
    a["Y"] -= 2500
    got = gate.report(moved,m)
    assert got["lr_elp38_candidate"]["other_pad_envelope_intersections"] == 21
    assert got["decisions"]["freeze_existing_lr_placement"] is False


def test_fail_closed_on_unknown_pad_or_claimed_maxwell_signoff():
    pad_dump, m = baseline()
    damaged = copy.deepcopy(pad_dump)
    q = next(p for p in damaged["pads"] if p["ref"] == "C10")
    q["Pad"] = ["UNKNOWN", 20, 40]
    with pytest.raises(ValueError, match="Unsupported"):
        gate.report(damaged,m)
    fake = copy.deepcopy(m)
    fake["maxwell_solved"] = True
    with pytest.raises(ValueError, match="approval"):
        gate.report(pad_dump,fake)


def test_no_physical_3d_or_fab_approval_is_assumed():
    r = gate.report()
    assert r["evidence"]["actual_maxwell_3d_solve"] is False
    assert r["evidence"]["real_assembly_Z_cleared"] is False
    assert r["evidence"]["native_gui_3d_collision_test"] is False
    assert r["evidence"]["fab_approved"] is False
    assert r["clearance_planning_assumptions_mm"]["status"].startswith(
        "ENGINEERING_PLANNING")
    assert "XY" in r["limitations"][0]

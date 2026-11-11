"""72 x 6.3V T530 is a real OEM-sourced alternative, not a release."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
import cout_t530_72 as C


def test_verified_vendor_and_p0_nominal_vs_real_operating_point():
    d=C.report()
    p=d["part"];a=d["arithmetic_100khz_25c_only"]
    assert d["schema"]=="g2_t530_72_cost_unrestricted/1"
    assert p["mpn"]=="T530X477M006ATE004"
    assert p["exact_order_oem_url"].startswith("https://")
    assert p["rated_v_at_or_below_105c"]==6.3
    assert p["rated_v_at_125c"]==4.22
    assert p["esr_mohm_at_100khz_25c"]==4
    assert p["ripple_a_at_100khz_125c"]==pytest.approx(2.05)
    assert a["minimum_count_for_ideal_esr"]==58
    assert a["chosen_count"]==72
    assert a["nominal_capacity_mF"]==pytest.approx(33.84)
    assert a["initial_tolerance_min_mF"]==pytest.approx(27.072)
    assert a["bank_esr_mohm_25c"]==pytest.approx(4/72,rel=1e-7)
    assert a["maximum_allowed_esr_per_part_mohm_at_hot_frequency"]==pytest.approx(5.04)
    assert a["allowed_esr_increase_over_25c_before_limit_pct"]==pytest.approx(26)
    assert a["bank_125c_ripple_nameplate_sum_a_at_100khz"]==pytest.approx(147.6)
    assert a["125c_ripple_arithmetic_only_pass"] is True
    assert a["voltage_nominal_and_125c_at_least_4v"] is True
    assert a["hot_200khz_esr_qualified"] is False
    assert a["hot_200khz_ripple_qualified"] is False
    assert a["startup_dynamics_qualified"] is False
    assert a["ac_current_sharing_qualified"] is False
    assert d["hardware_gates"]["fab_approved"] is False


def test_actual_132_line_board_72_body_grid_gross_fit_but_copper_requires_eco():
    d=C.report()
    p=d["placement"]
    assert p["board_source_sha256"]=="59ec7ab3f8dd17ba76b465e9686bce58647db66b76770a4762c0b7e33e33afb0"
    assert p["board_readback_lines"]==132
    assert p["board_readback_pads"]==299
    assert p["board_readback_vias"]==18
    assert p["grid_columns"]==18 and p["grid_rows"]==4
    assert len(p["units"])==72
    assert len(set(u["ref"] for u in p["units"]))==72
    assert p["units"][0]["candidate_position_mm"]==[8.0,92.0]
    assert p["units"][-1]["candidate_position_mm"]==pytest.approx([149.1,111.2])
    assert p["body_gap_x_mm"]==pytest.approx(.7)
    assert p["body_gap_y_mm"]==pytest.approx(1.8)
    assert p["manufacturer_courtyard_verified"] is False
    assert p["existing_pad_body_conflicts"]==[]
    # Existing output copper is still only 1-2mm traces, crosses the body
    # field and must be redesigned BEFORE placing 72 finished components.
    assert p["existing_copper_traversals_count"]>0
    assert p["board_source"].endswith("dcx_main_board_g1_open_batch.eprj2")
    assert p["source_native_connection_errors"]==183
    assert set(p["existing_copper_traversals_by_net"])=={"PGND","VOUT"}
    assert p["existing_copper_traversals_count"]==sum(p["existing_copper_traversals_by_net"].values())
    assert p["current_native_component_count_added"]==0
    assert all(not u["actual_native_pcb_component"] for u in p["units"])
    assert not d["hardware_gates"]["actual_72_components_in_schematic_and_pcb"]
    assert not d["hardware_gates"]["corrected_100a_high_current_copper_in_native_board"]


def test_official_part_identity_cannot_be_substituted_without_requalifying(tmp_path,monkeypatch):
    d=json.loads(C.SOURCING.read_text(encoding="utf-8"))
    part=next(x for x in d["capacitor_candidates"] if x["mpn"]=="T530X477M006ATE004")
    part["esr_mohm_at_100khz"]=6
    wrong=tmp_path/"sourcing.json"
    wrong.write_text(json.dumps(d),encoding="utf-8")
    monkeypatch.setattr(C,"SOURCING",wrong)
    with pytest.raises(ValueError,match="original part sourcing changed"):
        C.get_part()


def test_wrong_native_g1_board_cannot_be_silent_source(tmp_path,monkeypatch):
    fake=tmp_path/"new_easyeda.eprj2"
    fake.write_bytes(b"new wrong board")
    monkeypatch.setattr(C,"BASE",fake)
    with pytest.raises(ValueError,match="Wrong native G1 source"):
        C.report()


def test_segment_box_intersection_checks_not_just_endpoints():
    box=(0,0,10,10)
    assert C.segment_hits_rectangle((-2,5),(12,5),box)
    assert C.segment_hits_rectangle((5,5),(6,6),box)
    assert not C.segment_hits_rectangle((-2,15),(12,15),box)
    assert not C.segment_hits_rectangle((20,20),(30,30),box)
    assert C.touches((0,0,7.6,4.6),(8.3,0,15.9,4.6)) is False


def test_pr95_132_line_drc_evidence_is_required(tmp_path,monkeypatch):
    d=json.loads(C.DRC_DELTA.read_text(encoding="utf-8"))
    d["native_reopen_drc"]["Connection Error"]=199
    forged=tmp_path/"bad_drc_delta.json"
    forged.write_text(json.dumps(d),encoding="utf-8")
    monkeypatch.setattr(C,"DRC_DELTA",forged)
    with pytest.raises(ValueError,match="actually checked native 132-line"):
        C.active_native_g1()


def test_pr95_saved_reopen_has_to_contain_actual_132_tracks(tmp_path,monkeypatch):
    d=json.loads(C.READBACK.read_text(encoding="utf-8"))
    d["value"]["lines"]=d["value"]["lines"][:107]
    fake=tmp_path/"old_board_readback.json"
    fake.write_text(json.dumps(d),encoding="utf-8")
    monkeypatch.setattr(C,"READBACK",fake)
    with pytest.raises(ValueError,match="native geometry/counts changed"):
        C.active_native_g1()

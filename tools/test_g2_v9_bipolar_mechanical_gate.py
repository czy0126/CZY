"""D1 V9 physical copper-bar and actual native readback fail-closed tests.

Pass means the *screen* reproduced and remaining problems are exposed.
It does not qualify a 100A board or manufacture.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
G2=ROOT/"hardware/dcx_main/g2"
sys.path.insert(0,str(ROOT/"tools"))
import g2_v9_bipolar_mechanical_gate as G


def test_actual_native_board_source_and_generated_geometry_screen_are_locked():
    read=json.loads(G.READBACK.read_text("utf8"))
    report=json.loads(G.REPORT.read_text("utf8"))
    native=G.V9.sha(G.V9.V9)
    assert read["native_counts"]=={"components":149,"pads":443,"lines":407,"vias":93,"nets":65}
    assert read["source_sha256"]==native==report["source_native_sha256"]
    assert report==json.loads(json.dumps(G.report()))
    assert G.SVG.read_text("utf8")==G.svg_body(report)
    assert report["fabrication_approved"] is False
    assert report["actual_dual_busbar_contact_created_on_v9"] is False


def test_real_original_72_caps_and_both_pole_continuity_are_not_100a_qualification():
    r=G.report()
    assert r["native_islands"]=={"VOUT":1,"PGND":39}
    assert r["feeder_via_count"]==3
    assert len(r["contact_anchors"]["CTAP"])==4
    assert len(r["contact_anchors"]["SR_SOURCE"])==16
    assert all(x["inside_legacy_bar"] for x in r["contact_anchors"]["CTAP"])
    assert all(x["inside_legacy_bar"] for x in r["contact_anchors"]["SR_SOURCE"])
    assert r["native_drc_open_connections"]==168
    assert r["native_drc_netlist_errors"]==1


def test_legacy_bar_overlay_really_finds_unlike_net_vias():
    report=G.report()
    pairs=report["opposite_net_native_vias_needing_bottom_bar_insulation"]
    assert len(pairs["VOUT"])==1
    assert len(pairs["PGND"])==25
    # These are different-net vias, not manufactured busbar contacts.
    assert all(v["other_net"]!="VOUT" for v in pairs["VOUT"])
    assert all(v["other_net"]!="PGND" for v in pairs["PGND"])


def test_existing_narrow_feeder_and_barrel_resistance_use_real_units():
    d=G.report()["cross_section_scenarios"]
    assert d["20"]["three_via_total_resistance_uohm"]==pytest.approx(292.675,abs=.001)
    assert d["100"]["three_via_total_resistance_uohm"]>d["20"]["three_via_total_resistance_uohm"]
    assert d["20"]["three_feeder_only_if_100a_loss_w"]>2
    assert d["20"]["three_via_only_if_100a_loss_w"]==pytest.approx(2.927,abs=.002)
    assert G.via_ohm(6)==pytest.approx(G.via_ohm(3)/2)
    assert G.feeder_ohm(6)==pytest.approx(G.feeder_ohm(3)/2)
    with pytest.raises(ValueError):
        G.via_ohm(0)
    with pytest.raises(ValueError):
        G.feeder_ohm(0)


def test_assembly_stack_and_contact_quality_fail_closed():
    r=G.report()
    base=r["test_assembly_height_scenarios"]["none"]["cases"]
    full=r["test_assembly_height_scenarios"]["trial_TIM_clamp_tolerance"]["cases"]
    assert all(x["remaining_16mm_allowance_mm"]==pytest.approx(.55) for x in base)
    assert all(x["remaining_16mm_allowance_mm"]==pytest.approx(-.45) for x in full)
    assert all(not x["screen_full_height"] for x in full)
    assert full[0]["screen_both_pole_150uohm"] is True
    assert full[1]["screen_both_pole_150uohm"] is False
    assert r["test_assembly_height_scenarios"]["none"]["maximum_contact_uohm_each_if_other_assumptions_hold"]<50
    with pytest.raises(ValueError):
        G.bar_screen(-.01)


def test_mutated_native_board_or_evidence_refused(monkeypatch,tmp_path):
    fake=tmp_path/"fake.eprj2"
    fake.write_bytes(b"synthetic CAD is not saved native evidence")
    monkeypatch.setattr(G.V9,"V9",fake)
    with pytest.raises(ValueError,match="native source changed"):
        G.source()


def test_independent_reopen_receipt_reports_partial_failure_not_success():
    attempted=json.loads((G2/"g2_v9_independent_gui_reopen_attempt_NOT_FOR_FAB.json").read_text("utf8"))
    result=json.loads((G2/"g2_v9_independent_gui_reopen_verified_NOT_FOR_FAB.json").read_text("utf8"))
    assert attempted["do_not_replay_on_error"] is True
    assert result["source_sha256"]==G.V9.sha(G.V9.V9)
    assert result["native_saved_source_unchanged"] is True
    assert result["copy_unchanged"] is True
    assert result["other_gui_preserved"] is True
    assert result["new_verification_gui_closed"] is True
    assert result["status"]=="INDEPENDENT_REOPEN_NOT_VERIFIED_NOT_FOR_FAB"
    assert result["error"]=="Native DRC response failed or missing"
    assert result["fabrication_approved"] is False

def test_original_visible_v9_native_drc_readonly_returns_168_and_netlist_one():
    import route_open_connections as ROUTE
    r=json.loads((G2/"g2_v9_live_drc_readonly_followup_NOT_FOR_FAB.json").read_text("utf8"))
    assert r["source_sha256"]==r["source_after_sha256"]==G.V9.sha(G.V9.V9)
    assert r["response"]["ok"] is True
    assert ROUTE.categories(r["response"])=={"Connection Error":168,"Netlist Error":1}
    assert r["fab_approved"] is False


def test_new_independent_reopen_v2_really_reads_native_drc_and_schematic():
    r=json.loads((G2/"g2_v9_independent_gui_reopen_v2_verified_NOT_FOR_FAB.json")
                 .read_text("utf8"))
    attempt=json.loads((G2/"g2_v9_independent_gui_reopen_v2_attempt_NOT_FOR_FAB.json")
                       .read_text("utf8"))
    assert r["status"]=="INDEPENDENT_NATIVE_GUI_REOPEN_VERIFIED_NOT_FOR_FAB"
    assert r["source_sha256"]==r["source_sha256_after"]==G.V9.sha(G.V9.V9)
    assert r["native_saved_source_unchanged"] is True
    assert r["copy_unchanged"] is True
    assert r["other_gui_preserved"] is True
    assert r["new_verification_gui_closed"] is True
    assert r["native_counts"]=={"components":149,"pads":443,"lines":407,"vias":93,"nets":65}
    assert r["native_capacitor_instances_and_144_pins_verified"] is True
    assert r["native_schematic_72_symbols_144_wires_verified"] is True
    assert r["native_pcb_schematic_cout72_pin_parity"] is True
    assert r["vout_ctap_and_cout_saved_copper_joined"] is True
    assert r["native_drc_invocation"]["ok"] is True
    assert r["native_drc"]=={"Connection Error":168,"Netlist Error":1}
    assert r["fabrication_approved"] is False and r["100A_qualified"] is False
    assert attempt["preexisting_visible_sessions"]>=3

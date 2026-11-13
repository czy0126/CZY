"""Verify source-locked actual EasyEDA V18 Cin+T1+Lr power-cell CAD evidence.

This intentionally DOES NOT assert EMC qualification, full 12L fabrication
or the 106 remaining net connections. Only actual GUI native readbacks.
"""
from __future__ import annotations
import hashlib
import json
import sqlite3
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
G=ROOT/"hardware/dcx_main/g2"
PRE_CIN_SHA="7c9fe44004b3490ddf7c599385d57a8471803a146cdf8c16cc36d544d33cb95a"
CIN_SHA="2a3aa08510cd1b6b354b6b70ae7deb5217dfcdda5eee1c9b0defb996b6b62466"
FINAL_SHA="b291faea3b46c1d7ec4e7b54d57dd78a20e70523a2a629760f49d5141f7c7739"

def load(name):
    return json.loads((G/name).read_text("utf8"))

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def test_two_true_native_saved_project_binary_snapshots():
    for name,h in [
      ("dcx_main_board_g2_V18_CIN_TRUE_POWER_LOOP_NATIVE_SAVED_NOT_FOR_FAB.eprj2",CIN_SHA),
      ("dcx_main_board_g2_V18_CIN_T1_LR_RELAYOUT_NATIVE_SAVED_NOT_FOR_FAB.eprj2",FINAL_SHA)
    ]:
        file=G/name
        assert file.stat().st_size>3_000_000
        assert sha(file)==h
        with sqlite3.connect("file:"+file.resolve().as_posix()+"?mode=ro",uri=True) as db:
            row=db.execute("select id,structure from project_structures order by id desc limit 1").fetchone()
            assert row is not None
            boards=json.loads(row[1])["pcbs"]
            assert set(boards)=={"9b212da9a255a2af","8c496410b2877d3c","2f6fa2d508d3f9a8"}
    assert sha(G/"dcx_main_board_g2_V18_CIN_TRUE_POWER_LOOP_NATIVE_SAVED_NOT_FOR_FAB.eprj2")!=FINAL_SHA

def test_genuine_Cin_move_and_wired_both_terminals_with_correct_metal_count():
    r=load("g2_v18_true_native_Cin_relocated_both_loop_3VIN_3GND_tracks_2via_DRC_ONCE_NOT_FOR_FAB.json")
    assert r["native"]["ok"] is True
    v=r["native"]["value"]
    assert v["status"]=="TRUE_V18_CIN_CLOSED_VIN_AND_PGND_ROUTED"
    assert v["before"]=={"Connection Error":103}
    assert v["after"]=={"Connection Error":102}
    assert v["saved"] is True
    assert len(v["newNativeTrackIDs"])==6
    assert len(set(v["newNativeTrackIDs"]))==6
    assert len(v["newNativeViaIDs"])==2
    assert v["counts"]=={"parts":149,"pads":423,"lines":508,"vias":106}
    assert abs(v["newCin"]["x"]*.0254-43)<.02
    assert abs(v["newCin"]["y"]*.0254+44)<.02
    assert v["VIN_pin"]["x"]<v["QH_pin"]["x"]
    assert r["fabrication_approved"] is False

def test_first_Cin_short_circuit_layout_was_rejected_and_rolled_back():
    d=load("g2_v18_Cin_power_loop_one_clearance_error_NATIVE_DIAGNOSTIC_NOT_FOR_FAB.json")
    assert d["native"]["ok"] is True
    v=d["native"]["value"]
    assert v["status"]=="TEMP_DIAGNOSTIC_FULLY_REVERTED"
    assert v["cats"]=={"Clearance Error":1,"Connection Error":102}
    assert len(v["collision"])==1
    assert "Cin_2" in v["collision"][0]["obj2"]["suffix"]
    assert v["undoLines"] is True and v["undoVias"] is True

def test_native_T1_and_Lr_10_actual_components_20_tracks_two_vias():
    plan=load("g2_v18_T1_Lr_swap_30mm_native_source_plan_NOT_FOR_FAB.json")
    assert plan["source_after_Cin_SHA256"]==CIN_SHA
    assert len(plan["components"])==10
    assert len(plan["lines"])==20
    assert len(plan["vias"])==2
    assert len({x["id"] for x in plan["lines"]})==20
    assert {x["net"] for x in plan["vias"]}=={"PGND","REG1"}
    assert plan["static_native_pad_mechanical_body_collisions"]==0
    assert plan["planned_copper_moving_to_different_net_collisions"]==0
    a=load("g2_v18_T1_Lr_10native_components_RELOCATED_ONCE_NOT_FOR_FAB.json")
    b=load("g2_v18_T1_Lr_20tracks_2vias_NATIVE_MOVE_ONCE_NOT_FOR_FAB.json")
    assert a["status"]=="T1_LR_NATIVE_10_PARTS_MOVED_REQUIRES_COPPER"
    assert b["status"]=="T1_LR_NATIVE_LOCAL_COPPER_RELOCATED_PENDING_DRC"
    assert a["native"]["ok"] is True and b["native"]["ok"] is True
    assert len(a["native"]["value"]["done"])==10
    assert len(b["native"]["value"]["done"]["lines"])==20
    assert len(b["native"]["value"]["done"]["vias"])==2

def test_independent_real_DRC_and_positions_not_fake_compactness():
    d=load("g2_v18_independent_post_T1_Lr_relayout_real_native_DRC_AND_30primitive_readback_NOT_FOR_FAB.json")
    assert d["status"]=="V18_SECOND_REAL_NATIVE_DRC_AND_COMPONENT_POSITION_RECHECK"
    assert d["native"]["ok"] is True
    v=d["native"]["value"]
    assert v["errors"]=={"Connection Error":106}
    assert v["count"]=={"parts":149,"pads":423,"lines":508,"vias":106}
    assert v["rule"]=="JLCPCB Capability(Two Layers Board)"
    positions={x["ref"]:(x["x"]*.0254,-x["y"]*.0254) for x in v["moved"]}
    targets={"Cin":(43,44),"Lr":(26,79),"SR1A":(14,52),
        "SR1B":(24,52),"U3":(19,42),"C7":(18.933,45),
        "C105":(18,37),"SR2A":(52,82),"SR3A":(90,82),"SR4A":(128,52)}
    for ref,point in targets.items():
        assert ref in positions
        assert all(abs(a-b)<.06 for a,b in zip(positions[ref],point)),(ref,positions[ref],point)
    assert next(x for x in v["topNets"] if x["net"]=="PGND")["n"]==38
    assert d["fabrication_approved"] is False

def test_real_native_final_sha_receipt_and_not_for_fab():
    d=load("g2_v18_Cin_T1_Lr_real_native_saved_project_provenance_NOT_FOR_FAB.json")
    assert d["sha256"]==FINAL_SHA
    assert d["initial_V17_sha256"]==PRE_CIN_SHA
    assert d["initial_Cin_native_sha256"]==CIN_SHA
    assert d["real_native_DRC"]=={"Connection Error":106}
    assert d["native_sqlite_revision"]>=90
    assert d["emc_approved"] is False and d["fabrication_approved"] is False
    md=(ROOT/"hardware/dcx_main/manufacturing/V18_TRUE_POWER_UNIT_RELAYOUT_CIN_T1_LR_NOT_FOR_FAB.md").read_text("utf8")
    for phrase in ("SR1A","Lr","PGND","106","NOT_FOR_FAB","b291faea3b46"):
        assert phrase in md

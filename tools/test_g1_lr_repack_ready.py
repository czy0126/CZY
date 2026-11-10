"""Offline evidence tests: G1 Lr ELP38 physical repack, not a PCB release."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("g1_lr_repack_ready",ROOT/"tools/g1_lr_repack_ready.py")
r=importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


def test_frozen_source_parent_is_locked_to_plan():
    report=r.check()
    assert not report["preflight_errors"], report["preflight_errors"]
    assert report["move_count"]==12
    assert report["actual_cross_ref_overlap"]==11
    assert report["Lr_center_mm"]==[26.0,49.0]
    assert report["Lr_core_xy_mm"]=={
        "left":7,"right":45,"top":36.3,"bottom":61.7}
    # The plan is locked to the frozen pre-ECO parent, NOT to the active board:
    # once the repack is applied the active readback no longer has these moves
    # to make, so reading it here would double-apply or fail the source guard.
    assert r.geom.SOURCE_READBACK.name=="kelvin_readback.json"
    assert r.geom.ACTIVE_READBACK.name=="lr_repack_readback.json"
    assert report["source_readback_git_blob_sha"]==r.geom.git_blob_sha(
        r.geom.SOURCE_READBACK)
    assert report["source_readback_git_blob_sha"]!=r.geom.git_blob_sha(
        r.geom.ACTIVE_READBACK)
    assert report["native_eda_modified"] is False
    assert report["native_drc_passed"] is False
    assert report["maxwell_solved"] is False
    assert report["fab_approved"] is False


def test_not_auto_choose_far_empty_board_placement():
    d=r.check()["resonant_endpoint_proxy_mm"]
    assert d["original"]>d["near_loop_candidate"]
    assert d["near_loop_candidate"]<90
    assert d["rejected_remote"]>180
    assert d["rejected_remote"]>2*d["near_loop_candidate"]


def test_11_moving_parts_mapped_to_real_logical_anchors():
    p=json.loads(r.PLAN.read_text(encoding="utf-8"))
    x=p["moves"]
    assert set(x)==r.EXPECTED_MOVER_REFS
    assert x["Lr"]["rotation_deg"]==180
    assert x["C105"]["anchor_ref"]=="U3"
    assert x["C106"]["anchor_ref"]=="U4"
    assert x["C107"]["anchor_ref"]=="U5"
    assert x["C108"]["anchor_ref"]=="U6"
    assert x["R9"]["anchor_net"]=="GD1"
    assert x["R10"]["anchor_net"]=="GD2"
    assert x["R1"]["anchor_net"]=="DT"
    assert x["R2"]["anchor_net"]=="RT"
    assert x["C101"]["anchor_net"]=="VCC12"
    assert x["C102"]["anchor_net"]=="VCC12"


def test_emitted_js_is_a_guarded_native_cad_copy_only_action():
    value=r.emit_js(r.check())
    assert "Expected exactly Lr plus 11 passives" in value
    assert "if (lines.length!==98 || vias.length!==18)" in value
    assert "Ref moved since readback; refuse to apply" in value
    assert "eda.pcb_PrimitiveComponent.modify" in value
    assert "eda.pcb_Document.save()" in value
    assert "hardware_approved:false" in value
    assert "rotation" in value
    assert "DCX_MAIN_G1_LR" not in value  # no misleading claim of new CAD artifact


def test_source_hash_mismatch_fails_closed(tmp_path,monkeypatch):
    d=json.loads(r.PLAN.read_text(encoding="utf-8"))
    d["source_reopen_git_blob_sha"]="f"*40
    new=tmp_path/"plan.json"
    new.write_text(json.dumps(d),encoding="utf-8")
    monkeypatch.setattr(r,"PLAN",new)
    with pytest.raises(ValueError,match="source changed"):
        r.check()


def test_bad_native_count_or_changing_mover_set_fails_closed(tmp_path,monkeypatch):
    d=json.loads(r.PLAN.read_text(encoding="utf-8"))
    d["source_count_guard"]["lines"]=75
    new=tmp_path/"plan.json"
    new.write_text(json.dumps(d),encoding="utf-8")
    monkeypatch.setattr(r,"PLAN",new)
    with pytest.raises(ValueError,match="source counts"):
        r.check()
    d["source_count_guard"]["lines"]=98
    del d["moves"]["R9"]
    new.write_text(json.dumps(d),encoding="utf-8")
    with pytest.raises(ValueError,match="scope"):
        r.check()


def test_moving_magnet_is_not_a_maxwell_solve_or_real_terminal_approval():
    p=json.loads(r.PLAN.read_text(encoding="utf-8"))
    assert p["status"]=="CANDIDATE_ECO_NOT_APPLIED"
    assert p["guards"]["never_modify_input_project"] is True
    assert p["guards"]["require_lrs_real_physical_winding_and_terminal_design"] is True
    assert p["options"]["remote_no_existing_pad_or_route_overlap"]["status"].startswith("REJECT")
    assert p["output_cad_new_file"].endswith("_lr_repack.eprj2")
    assert "kelvin" in p["source_cad"]


def test_box_corner_and_pad_rotation_math():
    from math import isclose
    a=r.geom.rectangle(26,49,38,25.4)
    assert a=={"left":7.0,"right":45.0,"top":36.3,"bottom":61.7}
    assert r.touches(a,r.geom.rectangle(46,49,1,1),0) is False
    assert r.touches(a,r.geom.rectangle(44.9,49,1,1),0) is True
    assert isclose(r.electrical_proxy_length((26,49),True),77.5,abs_tol=1.0)

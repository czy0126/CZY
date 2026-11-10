"""Evidence-only regression tests for nine real-G1 low-current route proposals.

These tests never use the native EasyEDA editor and must not assert a
fabrication or successful *applied* PCB.
"""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
G1=ROOT/"hardware/dcx_main/g1"
import sys
sys.path.insert(0,str(G1))
import route_lr_signal_stubs as S
import apply_lr_signal_stubs as A


def test_nine_real_after_lr_repack_segments_are_clear():
    audit=S.report()
    assert audit["preflight_problems"]==[]
    assert audit["source_counts"]=={
        "components":77,"pads":299,"nets":65,"lines":98,"vias":18,"polylines":38}
    assert audit["new_trace_count"]==9
    assert audit["new_via_count"]==0
    assert audit["candidate"]=="dcx_main_board_g1_signal_stubs.eprj2"
    assert audit["native_eda_run"] is False
    assert audit["fab_approved"] is False
    assert {r["net"] for r in audit["routes"]}=={"VCC12","VCC12_S","RUN","OC1","OC"}
    assert all(r["length_mm"]<4.0 and r["layer"]==1 for r in audit["routes"])
    assert [r["from"] for r in audit["routes"]]==[
        "C101.1","C102.1","C103.1","C105.1","C107.1","C108.1",
        "R7.1","R15.2","R16.2"]
    # Actual protection net pairs come from the real saved native pads.
    assert {(r["from"], r["to"], r["net"]) for r in audit["routes"]} >= {
        ("R15.2", "R16.1", "OC1"),
        ("R16.2", "R17.1", "OC"),
        ("C103.1", "C104.1", "VCC12"),
    }


def test_source_geometry_stays_locked_to_actual_native_binary():
    p=S.parent()
    assert S.SOURCE.is_file()
    assert len(p["lines"])==98
    assert len(p["vias"])==18
    assert S.report()["source_readback_git_blob_sha"]==S.geom.git_blob_sha(S.READBACK)
    assert S.report()["source_sha256"]==json.loads(
        S.PARENT_REPORT.read_text(encoding="utf-8"))["candidate_sha256"]


def test_fourth_sr_decoupler_excluded_due_to_real_obstacle():
    assert not any(pair[0]=="C106" for pair in S.PAIRS)
    doc=S.report()["forbidden_not_routed"]
    assert doc[0].startswith("C106.1→U4.7")
    pads=S.R.load_pads(S.READBACK)
    a=S.reference_pad(S.parent()["pads"],"C106","1","VCC12_S")
    b=S.reference_pad(S.parent()["pads"],"U4","7","VCC12_S")
    segment={"net":"VCC12_S","layer":1,"width":.2,"a":a,"b":b}
    obstacles=S.R.find_conflicts(pads,[segment])
    assert any(o["kind"]=="pad" and o["other"]=="U4.8" for o in obstacles)
    assert all(o["other"]!="C106.2" for o in obstacles)  # near but not below 0.152mm floor


def test_js_is_nine_real_native_line_creations_without_vias():
    js=S.R.emit_js(S.copper(),S.vias())
    assert "pcb_PrimitiveLine.create" in js
    assert "pcb_PrimitiveVia.create" in js  # generic emitter, but via array empty
    assert "const vias = []" in js
    assert '"RUN"' in js and '"VCC12_S"' in js
    assert "await eda.pcb_Document.save()" in js
    assert "pcb_Drc.check" not in js  # real DRC is a distinct read-only host step


def test_mock_reopen_verifies_all_original_98_tracks_and_nine_new_segments(tmp_path):
    original=json.loads(S.READBACK.read_text(encoding="utf-8"))
    fake=copy.deepcopy(original)
    baseline=len(fake["value"]["lines"])
    for i,s in enumerate(S.R.segments(S.copper())):
        fake["value"]["lines"].append({
            "id":f"mock_new_{i}","net":s["net"],"layer":s["layer"],
            "x1":s["a"][0]*S.R.MIL,"y1":-s["a"][1]*S.R.MIL,
            "x2":s["b"][0]*S.R.MIL,"y2":-s["b"][1]*S.R.MIL,
            "width":s["width"]*S.R.MIL,
        })
    assert len(fake["value"]["lines"])==baseline+9
    file=tmp_path/"mock_reopen.json"
    file.write_text(json.dumps(fake),encoding="utf-8")
    results=S.verify(file)
    assert results["status"]=="REOPENED_NATIVE_SIGNAL_STUBS_PENDING_ACTUAL_DRC"
    assert results["new_seg_count"]==9
    assert results["layout_counts"]["unchanged"] is True
    assert results["lines"]["coverage_problems"]==[]
    assert results["native_drc_passed"] is False
    assert results["fab_release"] is False


def test_reopen_fails_if_a_preexisting_copper_segment_disappears(tmp_path):
    resp=json.loads(S.READBACK.read_text(encoding="utf-8"))
    resp["value"]["lines"]=resp["value"]["lines"][1:]
    p=tmp_path/"bad_reopen.json"
    p.write_text(json.dumps(resp),encoding="utf-8")
    results=S.verify(p)
    assert results["status"]=="NATIVE_ROUTING_REOPEN_VERIFICATION_FAILED"
    assert results["layout_counts"]["unchanged"] is False


def test_native_drc_categories_honest_when_still_206_errors():
    values=A.categories(A.BEFORE_DRC)
    assert values["Connection Error"]==206
    assert values["Netlist Error"]==1
    assert values.get("Physical Error",0)==0


def test_native_drc_must_improve_and_not_add_new_physical_errors(tmp_path,monkeypatch):
    def write(name,opens,physical=0,netlist=1):
        v={"ok":True,"value":{"raw":[
            {"name":"Connection Error","list":[{"name":"any",
                   "list":[{"errorType":"Connection Error"}]*opens}]},
            {"name":"Netlist Error","list":[{"name":"any",
                   "list":[{"errorType":"Netlist Error"}]*netlist}]},
            {"name":"Physical Error","list":[{"name":"any",
                   "list":[{"errorType":"Physical Error"}]*physical}]}]}}
        p=tmp_path/name
        p.write_text(json.dumps(v),encoding="utf-8")
        return p
    src=write("a.json",206,0)
    monkeypatch.setattr(A,"BEFORE_DRC",src)
    dest=write("b.json",200,0)
    monkeypatch.setattr(A,"AFTER_DRC",dest)
    ok=A.compare_drc()
    assert ok["connection_errors_reduced"]==6
    assert ok["fabrication_approved"] is False
    monkeypatch.setattr(A,"AFTER_DRC",write("unchanged.json",206,0))
    with pytest.raises(ValueError,match="must reduce"):
        A.compare_drc()
    monkeypatch.setattr(A,"AFTER_DRC",write("physical.json",200,1))
    with pytest.raises(ValueError,match="category|collision"):
        A.compare_drc()

"""V14 REAL native EasyEDA PCB: 12 Board Outline cutouts and 12 copper layers.
NOT a complete primary/secondary winding or manufacturing release.
"""
from __future__ import annotations
import json, sqlite3
from pathlib import Path
import pytest
import sys

ROOT=Path(__file__).resolve().parents[1]
G2=ROOT/"hardware/dcx_main/g2"
sys.path[:0]=[str(G2),str(ROOT/"tools")]
import g2_v14_native_pcb_12slots_apply as N
import g2_v14_through_board_magnetics as G

REPORT=G2/"g2_v14_real_native_12NPTH_saved_binary_snapshot_NOT_FOR_FAB.json"
BINARY=G2/"dcx_main_board_g2_V14_EILP32_TWELVE_NPTH_12L_STACK_WIP_NOT_FOR_FAB.eprj2"
LAYER_RECEIPT=G2/"g2_v14_native_PCB_12copperlayers_12cutouts_saved_NOT_FOR_FAB.json"
STACK=G2/"g2_v14_native_trial_12layer_stack_change_once_NOT_FOR_FAB.json"
DRC=G2/"g2_v14_native_PCB_after_12slots_real_DRC_raw_NOT_FOR_FAB.json"


def test_saved_real_native_project_snapshot_and_copy_board_are_sha_bound():
    r=json.loads(REPORT.read_text("utf8"))
    assert r["status"]=="SAVED_V14_NATIVE_EPRJ2_WITH_ORIGINAL_PCB1_AND_NEW_V14_COPY_PCB_NOT_FOR_FAB"
    assert r["original_verified_V11_sha256"]==G.SOURCE_SHA
    assert G.sha(BINARY)==r["saved_candidate_SHA256"]
    assert r["saved_candidate_SHA256"]=="1e76e6865a746a49bea8a9fb87037b0301213faa386f5fdd2d6bdf5550ffbac6"
    assert BINARY.stat().st_size>=2_000_000
    assert r["original_PCB1_uuid"]==N.ORIGINAL_BOARD
    assert r["new_V14_actual_PCB_uuid"]==N.BOARD_UUID
    assert r["manufacturer_DFM_approved"] is False
    assert r["fabrication_approved"] is False


def test_native_project_snapshot_sqlite_contains_two_pcb_entities():
    with sqlite3.connect(f"file:{BINARY.resolve().as_posix()}?mode=ro",uri=True) as db:
        tables={t[0] for t in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "project_structures" in tables
        all_docs=db.execute("SELECT structure FROM project_structures ORDER BY id DESC LIMIT 1").fetchone()
        assert all_docs
        project=json.loads(all_docs[0])
        assert set(project["pcbs"])=={N.ORIGINAL_BOARD,N.BOARD_UUID}
        assert project["pcbs"][N.ORIGINAL_BOARD]["title"]=="PCB1"
        assert project["pcbs"][N.BOARD_UUID]["title"]=="PCB1_1"
        assert len(project["schematics"])==1
        assert len(project["sheets"])==2


def test_20_obsolete_native_pads_7_vout_lines_3_vout_vias_actually_deleted():
    plan=json.loads(N.PREP.read_text("utf8"))
    removed=json.loads(N.REMOVED.read_text("utf8"))
    assert plan==N.plan()
    assert {k:len(v) for k,v in plan["old_copper_replacements"].items()}=={
        "pads":20,"lines":7,"vias":3}
    assert removed["status"]=="NATIVE_V14_20_PAD_7_VOUT_TRACK_3_VIA_REMOVED_NOT_FOR_FAB"
    reply=removed["native"]["value"]
    assert reply["padDeleted"] is True
    assert reply["lineDeleted"] is True
    assert reply["viaDeleted"] is True
    assert reply["counts"]=={"pads":423,"lines":458,"vias":90}
    assert reply["obsolete_pad_ids_remaining"]==0
    assert reply["obsolete_track_ids_remaining"]==0
    assert reply["obsolete_via_ids_remaining"]==0
    assert len(set(reply["removed_native_pad_ids"]))==20
    assert removed["fabrication_approved"] is False


def test_twelve_true_native_internal_board_contours_written_and_saved():
    slots=json.loads(N.SLOTS.read_text("utf8"))
    saved=json.loads(N.SAVED.read_text("utf8"))
    plan=N.plan()
    assert slots["status"]=="REAL_NATIVE_V14_BOARD_12_NPTH_CONTOURS_CREATED_NOT_FOR_FAB"
    native=slots["native"]["value"]
    assert native["requested"]==12
    assert native["original_outline_present"] is True
    assert native["board_layer_contour_count"]==13
    assert len(native["created"])==12
    assert [x["slot"] for x in native["created"]]==[s["id"] for s in G.slot_geometry()]
    assert len({x["id"] for x in native["created"]})==12
    assert all(x["layer"]==11 and x["source_length"]==75 for x in native["created"])
    assert len(plan["native_EI_PCB_slot_contours"])==12
    assert saved["status"]=="V14_NEW_PCB_WITH_12_REAL_NPTH_CONTOURS_SAVED_NOT_FOR_FAB"
    v=saved["native"]["value"]
    assert v["saved"] is True
    assert v["board_outlines"]==13
    assert (v["pads"],v["tracks"],v["vias"],v["components"])==(423,458,90,149)


def test_true_12layer_physical_EasyEDA_stack_active_on_new_pcb_only():
    a=json.loads(STACK.read_text("utf8"))
    b=json.loads(LAYER_RECEIPT.read_text("utf8"))
    assert a["status"]=="V14_NATIVE_PCB_12_COPPER_LAYERS_ACTIVE_TRIAL_NOT_FOR_FAB"
    got=a["native"]["value"]
    assert got["updated"] is True
    assert got["before"]==[1,2]
    assert [x["id"] for x in got["after"]]==[1,2,*range(15,25)]
    assert all(x["layerStatus"]==1 for x in got["after"])
    assert got["source_board_untouched"] is True
    assert b["status"]=="NATIVE_V14_REAL_CAD_12_COPPERLAYERS_12_NPTH_PERSISTED_NOT_FOR_FAB"
    assert b["source_readback"]["saved"] is True
    assert b["source_readback"]["board_source_original_still_present"] is True
    assert b["source_readback"]["outline_count"]==13
    assert b["supplier_12L_3OZ_physical_stack_approved"] is False


def test_native_DRC_did_not_claim_electrical_or_netlist_release():
    drc=json.loads(DRC.read_text("utf8"))
    assert drc["status"]=="V14_NATIVE_DRC_RAN_NOT_FOR_FAB"
    assert drc["categories"]=={"Connection Error":149,"Netlist Error":1}
    assert drc["raw_native"]["ok"] is True
    assert drc["fabrication_approved"] is False


def test_magnetics_footprint_as_native_part_is_not_same_as_3turn_copper_winding():
    report=G.build()
    assert report["native_winding_tracks_already_applied"] is False
    assert report["fabrication_approved"] is False
    assert report["released_copper_stackup"] is False
    assert N.plan()["supplier_3_1_1_PCB_windings_already_created"] is False
    assert N.plan()["fabrication_approved"] is False
    assert G.sha(N.PARENT)==G.SOURCE_SHA


def test_wrong_saved_V11_source_is_safety_stop(monkeypatch,tmp_path):
    bogus=tmp_path/"bad-native.eprj2"
    bogus.write_bytes(b"wrong")
    monkeypatch.setattr(N,"PARENT",bogus)
    with pytest.raises(ValueError,match="source drift"):
        N.plan()

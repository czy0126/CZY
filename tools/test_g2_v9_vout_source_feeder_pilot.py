"""Fail-closed G2 V9 source-to-Cout native copper-feeder evidence tests."""
import json
import sys
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
G2=ROOT/"hardware/dcx_main/g2"
sys.path.insert(0,str(G2))
import g2_v9_vout_source_feeder_pilot as F


def load(path):
    return json.loads(path.read_text(encoding="utf8"))


def test_real_native_3_feeder_3_via_save_and_true_drc_improvement():
    saved=load(F.SAVE_RECEIPT)
    assert saved["ok"] and saved["value"] is True
    seen=load(F.VERIFY_RECEIPT)
    assert seen["source_sha256"]==F.V9.sha(F.V9.V9)
    assert seen["native_counts"]=={
        "components":149,"pads":443,"lines":407,"vias":93,"nets":65}
    assert seen["native_drc"]=={"Connection Error":168,"Netlist Error":1}
    assert seen["vout_island_count_geometry_screen"]==1
    assert seen["vout_source_ctap_and_cout_same_physical_island"] is True
    assert seen["new_vias"]==3
    assert seen["new_bottom_tracks_requested"]==3
    assert seen["actual_tracks_increased_by"]==4
    assert seen["ampacity_100A_verified"] is False
    assert seen["fabrication_approved"] is False


def test_route_preflight_locked_to_actual_frozen_native_V9_historical_source():
    data=load(F.PLAN)
    # Full pre-feeder readback was an untracked local capture; the committed
    # source-bound native route plan is the surviving historical evidence.
    # Final-board parity must be checked independently after native reopen.
    assert data["source_sha256"]==F.CANDIDATE_SHA
    assert F.V9.sha(F.V9.V8)==F.V9.EXPECTED_V8_SHA
    assert data["source_sha256"]==F.CANDIDATE_SHA
    assert data["physical_preflight_problems"]==[]
    assert data["source_connected_vout_island_count"]==2
    assert len(data["tracks"])==len(data["vias"])==3
    assert all(t["net"]=="VOUT" and t["layer"]==2 for t in data["tracks"])
    assert all(t["net"]=="VOUT" for t in data["vias"])
    assert all(t["width_mm"]==1.6 for t in data["tracks"])
    assert data["full_100a_copper_ampacity_qualified"] is False


def test_a_second_apply_is_not_allowed_to_modify_live_gui(monkeypatch):
    called=[]
    monkeypatch.setattr(F.V9,"active_v9",lambda:called.append("gui"))
    with pytest.raises(FileExistsError,match="already happened"):
        F.apply()
    assert not called


def test_native_mutation_receipts_match_exact_one_shot_submission():
    start=load(F.ATTEMPT)
    assert start["status"]=="SUBMISSION_INITIATED_DO_NOT_RETRY"
    assert start["source_sha256"]==F.CANDIDATE_SHA
    assert start["do_not_replay_if_timeout"] is True
    assert start["vias_requested"]==start["lines_requested"]==3
    for file in (F.VIAS_RECEIPT,F.LINES_RECEIPT):
        answer=load(file)
        assert answer["ok"] and answer["value"]["all_created"]
        assert answer["value"]["requested"]==3


def test_no_GUI_session_close_reset_or_reopen_in_native_source_feeder():
    body=Path(F.__file__).read_text(encoding="utf8")
    assert "build_open_args" not in body
    assert "build_close_args" not in body
    assert "session close" not in body
    assert "lceda-pro stop" not in body

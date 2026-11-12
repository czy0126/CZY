"""Regression guards for saved native V8 GUI ECO and one-shot write path."""
import json
import sys
from pathlib import Path
import pytest

G2=Path(__file__).resolve().parents[1]/"hardware/dcx_main/g2"
sys.path.insert(0,str(G2))
import route_t530_oem_v8_gui_real_ocm as V8


def test_v8_real_gui_board_and_drc_receipt_bound_to_source():
    result=json.loads(V8.VERIFIED.read_text(encoding="utf8"))
    assert result["status"]=="V8_REAL_GUI_NATIVE_OCM_ISLAND_JOIN_NOT_FOR_FAB"
    assert V8.sha(V8.TARGET)==result["candidate_sha256"]
    assert V8.sha(V8.V6.SOURCE)==result["v5_sha256"]
    assert result["candidate_sha256"]!=result["v5_sha256"]
    assert result["native_counts"]=={
        "components":77,"pads":443,"lines":403,"vias":90,"nets":65}
    assert result["native_drc"]=={"Connection Error":170,"Netlist Error":1}
    assert result["route"]["ocm_target_island_joined"] is True
    assert result["route"]["new_ocm_tracks_physically_covered"]==3
    assert result["route"]["old_native_copper_preserved"] is True
    assert result["gui_kept_open"] is True
    assert result["fabrication_approved"] is False
    assert result["100A_approved"] is False
    assert result["72_caps_real_instances_verified"] is False


def test_v8_single_mutation_attempt_and_native_save_evidence():
    attempt=json.loads(V8.ATTEMPT.read_text(encoding="utf8"))
    write=json.loads(V8.APPLIED.read_text(encoding="utf8"))
    save=json.loads((G2/(V8.PREFIX+"_save.json")).read_text(encoding="utf8"))
    assert attempt["do_not_retry_even_on_timeout"]
    assert attempt["source_sha256"]==V8.sha(V8.V6.SOURCE)
    assert attempt["candidate_before_sha256"]==attempt["source_sha256"]
    assert (attempt["net"],attempt["segments"])==("OCM",3)
    assert write["ok"] and write["value"]["all_created"]
    assert write["value"]["requested"]==3
    assert write["source_unchanged"]
    assert save["ok"] and save["value"] is True


def test_existing_attempt_blocks_every_later_write(monkeypatch):
    monkeypatch.setattr(V8,"session",lambda:pytest.fail("Unexpected EDA call"))
    with pytest.raises(FileExistsError,match="Never replay"):
        V8.apply()


def test_matching_visible_gui_required_and_not_closed(monkeypatch):
    d=V8.V6.V.A.D
    calls=[]
    def fake(args,timeout_s=None):
        calls.append(args)
        if args[1]=="session":
            return {"ok":True,"value":[
                {"status":"alive","headless":False,"sessionId":"v5"},
                {"status":"alive","headless":False,"sessionId":"v8"},
                {"status":"alive","headless":True,"sessionId":"hidden"}]}
        return {"ok":True,"value":{"name":V8.TARGET.stem if args[2]=="v8" else "v5",
                                    "pcb":"2f6fa2d508d3f9a8"}}
    monkeypatch.setattr(d,"call",fake)
    monkeypatch.setattr(d,"build_invoke_args",
                        lambda sid,js,timeout_ms: ["CLI","invoke",sid,js])
    assert V8.session()=="v8"
    assert [x[1] for x in calls]==["session","invoke","invoke"]
    assert all(x[1] not in ("close","stop") for x in calls)


def test_ambiguous_visible_gui_identity_fails_closed(monkeypatch):
    d=V8.V6.V.A.D
    def fake(args,timeout_s=None):
        if args[1]=="session":
            return {"ok":True,"value":[
                {"status":"alive","headless":False,"sessionId":"a"},
                {"status":"alive","headless":False,"sessionId":"b"}]}
        return {"ok":True,"value":{"name":V8.TARGET.stem,"pcb":"pcb"}}
    monkeypatch.setattr(d,"call",fake)
    monkeypatch.setattr(d,"build_invoke_args",
                        lambda sid,js,timeout_ms: ["CLI","invoke",sid,js])
    with pytest.raises(RuntimeError,match="No unique"):
        V8.session()

"""V12 must fail closed while its native board rule reports 3mm track >100mil."""
from __future__ import annotations
import json,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
import g2_v12_native_physical_stopline as G


def test_exact_saved_native_source_and_real_physical_drc_fails_closed():
    r=G.build()
    assert r==json.loads(G.OUT.read_text("utf8"))
    assert G.sha(G.BOARD)==r["saved_native_V12_sha256"]
    assert G.sha(G.PARENT)==r["last_physically_clean_independently_reopened_native_V11_sha256"]
    assert r["status"]=="NATIVE_V12_HAS_PHYSICAL_ERROR_1_MUST_NOT_RELEASE"
    assert r["native_DRC"]=={"Physical Error":1,"Connection Error":145,"Netlist Error":1}
    assert r["fab_release"]=="NOT_FOR_FAB"
    assert r["fabrication_approved"] is False


def test_native_error_UUID_and_rule_max_100mil_actual_readback():
    r=G.build()
    assert r["offending_native_trace_id"]=="25fcbfaa23a768e3"
    assert r["offending_net"]=="PRI_T1"
    assert r["width_current_mm"]==3.
    assert r["width_rule_max_mil"]==100
    assert r["width_rule_max_mm"]==2.54
    assert r["width_proposed_mm"]==2.5
    assert r["unperformed_native_modify_attempt_proven"] is False


def test_native_board_sha_mutation_cannot_clear_fail_gate(tmp_path,monkeypatch):
    fake=tmp_path/"tampered.eprj2"
    fake.write_bytes(b"no native model")
    monkeypatch.setattr(G,"BOARD",fake)
    with pytest.raises(ValueError,match="native V12"):
        G.build()


def test_drc_phys_error_tampering_is_rejected(tmp_path,monkeypatch):
    raw=json.loads(G.NATIVE_DRC.read_text("utf8"))
    raw["native_categories"]["Physical Error"]=0
    f=tmp_path/"pretend_clean.json"
    f.write_text(json.dumps(raw),encoding="utf8")
    monkeypatch.setattr(G,"NATIVE_DRC",f)
    with pytest.raises(ValueError,match="evidence incomplete or changed"):
        G.build()

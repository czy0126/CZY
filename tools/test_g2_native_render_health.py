"""Fail-closed unit tests for one-process native EasyEDA health checks."""
from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import g2_native_render_health as H


def test_reset_refuses_active_gui_or_headless_sessions(monkeypatch):
    events = []
    def fake(args, timeout_s=None):
        events.append(args[1:3])
        return {"ok": True, "value": [{"status":"open","sessionId":"current-user"}]}
    monkeypatch.setattr(H.D, "call", fake)
    with pytest.raises(RuntimeError, match="Active EasyEDA sessions"):
        H.reset_if_no_active_sessions()
    assert events == [["session","list"]]


def test_reset_only_after_all_sessions_closed(monkeypatch):
    events = []
    def fake(args, timeout_s=None):
        events.append(args[1])
        if args[1] == "session":
            return {"ok": True,"value":[{"status":"closed"}]}
        assert args[1] == "stop"
        return {"ok": True,"value":"stopping"}
    monkeypatch.setattr(H.D, "call", fake)
    monkeypatch.setattr(H.time, "sleep", lambda *_: None)
    r=H.reset_if_no_active_sessions()
    assert events==["session", "stop"]
    assert r["active_sessions_touched"] == 0
    assert r["closed_session_count"] == 1


def test_no_current_project_aborts_before_expensive_native_read(tmp_path, monkeypatch):
    board=tmp_path/"test.eprj2"
    board.write_bytes(b"read-only-native-copy")
    scratch=tmp_path/"new"
    scratch.mkdir()
    monkeypatch.setattr(H.tempfile, "mkdtemp", lambda prefix: str(scratch))
    monkeypatch.setattr(H.time, "sleep", lambda *_: None)
    actions=[]
    def fake(args, timeout_s=None):
        actions.append(args)
        if args[1]=="open":
            return {"ok":True,"value":{"sessionId":"safe","headless":True}}
        if args[1]=="invoke" and "return 1;" in args:
            return {"ok":True,"value":1}
        if args[1]=="invoke":
            assert H.INFO_JS in args
            return {"ok":True,"value":{"project_present":False,"board_uuids":[]}}
        if args[1]=="session":
            return {"ok":True,"value":{"status":"closed"}}
        raise AssertionError("Unexpected native write")
    monkeypatch.setattr(H.D, "call", fake)
    result=H.run(board,settle_s=20,out=tmp_path/"receipt.json")
    assert result["status"]=="NATIVE_READBACK_NOT_VERIFIED_NOT_FOR_FAB"
    assert result["original_source_unchanged"] is True
    assert result["temporary_copy_unchanged"] is True
    assert result["write_attempted"] is False
    assert "components" not in result["steps"]
    assert "full_readback" not in result["steps"]


def test_visible_gui_is_never_closed_even_after_failed_ping(tmp_path, monkeypatch):
    board=tmp_path/"keep-visible.eprj2"
    board.write_bytes(b"native-eprj2")
    scratch=tmp_path/"scratch"
    scratch.mkdir()
    monkeypatch.setattr(H.tempfile,"mkdtemp",lambda prefix:str(scratch))
    monkeypatch.setattr(H.time,"sleep",lambda *_:None)
    actions=[]
    def fake(args,timeout_s=None):
        actions.append(args)
        if args[1]=="open":
            assert args[-2:]==["--headless","false"]
            return {"ok":True,"value":{"sessionId":"visible","headless":False}}
        assert args[1]=="invoke"
        return {"ok":False,"error":{"code":"REQUEST_TIMEOUT"}}
    monkeypatch.setattr(H.D,"call",fake)
    report=H.run(board,settle_s=20,out=tmp_path/"out.json",visible_editor=True)
    assert report["steps"]["visible_gui_retained"]["ok"] is True
    assert not any("close" in x for args in actions for x in args)
    assert report["original_source_unchanged"] is True


def test_malformed_missing_source_and_existing_receipt_refused(tmp_path):
    with pytest.raises(ValueError,match="Only existing native"):
        H.run(tmp_path/"missing.eprj2",out=tmp_path/"result.json")
    board=tmp_path/"source.eprj2"
    board.write_bytes(b"cad")
    out=tmp_path/"result.json"
    out.write_text("preserve")
    with pytest.raises(FileExistsError,match="Do not overwrite"):
        H.run(board,out=out)
    assert out.read_text()=="preserve"

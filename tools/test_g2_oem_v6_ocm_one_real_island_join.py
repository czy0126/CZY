"""Native V6 OCM route preflight, source fence and actual-island gate.

These tests alone NEVER prove saved native EDA or make the board fabricable.
"""
import copy
import json
import sys
from pathlib import Path
import pytest

G2 = Path(__file__).resolve().parents[1] / "hardware/dcx_main/g2"
sys.path.insert(0, str(G2))
import route_t530_oem_v6_ocm_one_real_island_join as V6


def test_v6_genuine_172_error_parent_and_three_collision_free_control_stubs():
    plan = V6.geometry_plan()
    assert plan["source_eprj2_sha256"] == V6.sha(V6.SOURCE)
    assert plan["native_drc_before"] == {"Connection Error": 172, "Netlist Error": 1}
    assert plan["path"]["source_copper_islands_distinct"]
    assert (plan["path"]["net"], plan["path"]["start"], plan["path"]["end"]) == (
        "OCM", "R17.2", "C11.2")
    assert not plan["preflight_problems"]
    assert len(plan["tracks"]) == 3
    assert {q["net"] for q in plan["tracks"]} == {"OCM"}
    assert plan["high_current_and_sense_nets_untouched"]
    assert plan["manufacturing_approved"] is False


def test_v6_requires_original_v5_native_bytes(monkeypatch):
    monkeypatch.setattr(V6, "sha", lambda *_: "0" * 64)
    with pytest.raises(ValueError, match="source differs"):
        V6.geometry_plan()


def test_v6_cannot_claim_link_exists_before_eda_writes():
    native, _ = V6.frozen_source()
    with pytest.raises(ValueError, match="requested copper"):
        V6.verify_target(native, V6.geometry_plan())


def test_v6_disallows_write_after_false_ping_with_actual_render_blocked(monkeypatch):
    """A no-op ping alone cannot demonstrate native EDA API readiness."""
    native, _ = V6.frozen_source()
    calls = []
    def fake_call(args, timeout_s=None):
        calls.append(args)
        if len(calls) == 1:
            return {"ok": True, "value": {"sessionId": "dummy"}}
        return {"ok": True, "value": 1}
    monkeypatch.setattr(V6.V.A.D, "call", fake_call)
    monkeypatch.setattr(V6.V.A, "invoke", lambda *_: {"ok": False, "error": {"code": "REQUEST_TIMEOUT"}})
    monkeypatch.setattr(V6.time, "sleep", lambda *_: None)
    monkeypatch.setattr(V6, "dump", lambda *_: None)
    assert V6.open_board("apply") is None
    assert len(calls) == 3  # open, ping, close; no write request


def test_v6_ready_probe_requires_exact_frozen_native_object_counts(monkeypatch):
    native, _ = V6.frozen_source()
    calls = []
    def fake_call(args, timeout_s=None):
        calls.append(args)
        if len(calls) == 1:
            return {"ok": True, "value": {"sessionId": "dummy"}}
        return {"ok": True, "value": 1}
    monkeypatch.setattr(V6.V.A.D, "call", fake_call)
    invoked = []
    def invoke(session, code):
        invoked.append(code)
        if len(invoked) == 1:
            assert code == V6.HEALTH.INFO_JS
            return {"ok": True, "value": {"project_present": True,
                                              "board_uuids": ["pcb-real"]}}
        return {"ok": True, "value": native}
    monkeypatch.setattr(V6.V.A, "invoke", invoke)
    monkeypatch.setattr(V6.time, "sleep", lambda *_: None)
    monkeypatch.setattr(V6, "dump", lambda *_: None)
    assert V6.open_board("apply") == "dummy"
    assert len(calls) == 2  # successful open and ping only
    assert len(invoked) == 2  # lightweight project check, then full PCB read


def test_v6_missing_native_document_blocks_full_read_and_writes(monkeypatch):
    calls, invoked = [], []
    def fake_call(args, timeout_s=None):
        calls.append(args)
        if len(calls) == 1:
            return {"ok": True, "value": {"sessionId": "dummy"}}
        return {"ok": True, "value": 1}
    def fake_invoke(session, code):
        invoked.append(code)
        assert code == V6.HEALTH.INFO_JS  # never progress to 443-pad read
        return {"ok": True, "value": {"project_present": False,
                                         "board_uuids": []}}
    monkeypatch.setattr(V6.V.A.D, "call", fake_call)
    monkeypatch.setattr(V6.V.A, "invoke", fake_invoke)
    monkeypatch.setattr(V6.time, "sleep", lambda *_: None)
    monkeypatch.setattr(V6, "dump", lambda *_: None)
    assert V6.open_board("apply") is None
    assert len(invoked) == 1
    assert len(calls) == 3  # open, ping, close


def test_v6_wrong_source_netlist_fails_no_shortcut_to_drc_approval(monkeypatch):
    native, _ = V6.frozen_source()
    altered = copy.deepcopy(native)
    altered["nets"].pop()
    with pytest.raises(ValueError, match="component/pad/via/net"):
        V6.verify_target(altered, V6.geometry_plan())

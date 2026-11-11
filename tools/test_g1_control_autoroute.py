"""Use only the real EasyEDA selected-net API; never route 100A/SR/Kelvin."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
G1DIR=ROOT/"hardware/dcx_main/g1"
sys.path.insert(0,str(G1DIR))
import apply_g1_control_autoroute as M
import route_open_connections as P


def test_native_autoroute_source_and_two_independent_scope_guards():
    p=M.plan()
    assert p["source_sha256"]=="59ec7ab3f8dd17ba76b465e9686bce58647db66b76770a4762c0b7e33e33afb0"
    assert p["first_stage_parent_sha256"]=="17fbae57bebdab6e0e18b6e4ddd177da98e25ca646bcb71d5e482a3b8db7b37e"
    assert p["active_native_connection_errors"]==183
    assert p["net_count"]==65
    assert p["routing_nets"]==["RUN","SS","OC","OCD","OCM"]
    assert p["routing_drc_subcategories"]=={"RUN":2,"SS":2,"OC":4,"OCD":4,"OCM":6}
    assert len(p["ignoring_nets"])==60
    assert {"DT","RT","OC1"}.issubset(p["ignoring_nets"])
    assert set(p["routing_nets"]).isdisjoint(p["ignoring_nets"])
    assert {"PGND","VOUT","SW","VIN_P","CT_LR","SEC1_A","GA1",
            "VG1_A","REG1","VCC12","VCC12_S"}.issubset(set(p["ignoring_nets"]))
    assert p["native_eda_applied"] is False
    assert p["fabrication_approved"] is False
    s=M.js_body(p)
    assert "autoRouting({" in s
    assert "RoutingNets: allow" in s  # EasyEDA interface exact property name
    assert "ignoreNets: excluded" in s  # second independent safety fence
    assert "layers: [1]" in s
    assert "await eda.pcb_Document.save()" in s
    assert "autoRouting();" not in s  # all-nets is physically unsafe
    assert '"PGND"' in s and '"VOUT"' in s


def test_mutant_whitelist_source_is_rejected(monkeypatch):
    monkeypatch.setattr(M,"ROUTE_NETS",M.ROUTE_NETS+("PGND",))
    with pytest.raises(ValueError,match="whitelist changed"):
        M.plan()


def test_routed_readback_must_preserve_every_old_trace_pad_and_via():
    original=P.source()
    after=json.loads(json.dumps(original))
    extra={**original["lines"][0],
           "id":"G1_AUTOROUTED_NEW_SIGNAL_ONLY",
           "net":"SS","layer":1}
    after["lines"].append(extra)
    x=M.compare_readback(original,after)
    assert x["added_line_count"]==1
    assert x["added_nets"]==["SS"]
    assert x["unexpected_nets"]==[]
    assert x["problems"]==[]
    assert x["readback_accepted_for_native_drc"] is True


def test_power_net_and_kelvin_autoroute_cannot_pass_with_drc_reduced():
    original=P.source()
    for net in ("PGND","VOUT","SW","GA1","VG1_A","VD1_B","VCC12_S"):
        after=json.loads(json.dumps(original))
        after["lines"].append({**original["lines"][0],
                               "id":"RISKY_NEW_ROUTE","net":net,"layer":1})
        d=M.compare_readback(original,after)
        assert not d["readback_accepted_for_native_drc"]
        assert net in d["unexpected_nets"]
        assert any("Unauthorized" in p for p in d["problems"])


def test_missing_and_mutated_original_native_copper_are_rejected():
    original=P.source()
    after=json.loads(json.dumps(original))
    assert not M.compare_readback(original,after)["readback_accepted_for_native_drc"]
    after["lines"].pop(0)
    assert "Original copper line missing" in str(M.compare_readback(original,after)["problems"])
    after=json.loads(json.dumps(original))
    after["lines"][0]["width"]+=10
    assert "Original copper line geometry changed" in str(M.compare_readback(original,after)["problems"])
    after=json.loads(json.dumps(original))
    after["vias"].append({**original["vias"][0],"id":"UNSAFE_NEW_VIA"})
    assert "vias" in str(M.compare_readback(original,after)["problems"])


def test_native_drc_must_be_real_decline_without_new_error(tmp_path,monkeypatch):
    def fake(n,netlist=1,physical=0):
        group=lambda name,m:{"name":name,"list":[{"name":name,"list":[{"errorType":"test"} for _ in range(m)]}]}
        return {"ok":True,"value":{"count":3,"raw":[group("Connection Error",n),
                      group("Netlist Error",netlist),group("Physical Error",physical)]}}
    a=tmp_path/"first.json";b=tmp_path/"second.json"
    board1=tmp_path/"first.eprj2";board2=tmp_path/"second.eprj2"
    board1.write_bytes(b"verified-12");board2.write_bytes(b"one-more-g1-control-route")
    monkeypatch.setattr(M.STAGE1,"AFTER_DRC",a)
    monkeypatch.setattr(M,"STAGE2_DRC",b)
    monkeypatch.setattr(M,"STAGE1_BOARD",board1)
    monkeypatch.setattr(M,"STAGE2_BOARD",board2)
    a.write_text(json.dumps(fake(198)),encoding="utf-8")
    b.write_text(json.dumps(fake(197)),encoding="utf-8")
    d=M.compare_native_drc({}, {})
    assert d["extra_real_connection_errors_removed"]==1
    assert d["actual_origin_199_to_new_count"]==197
    assert d["fab_approved"] is False
    b.write_text(json.dumps(fake(198)),encoding="utf-8")
    with pytest.raises(ValueError,match="did not decrease"):
        M.compare_native_drc({}, {})
    b.write_text(json.dumps(fake(197,netlist=2)),encoding="utf-8")
    with pytest.raises(ValueError,match="netlist"):
        M.compare_native_drc({}, {})
    b.write_text(json.dumps(fake(197,physical=1)),encoding="utf-8")
    with pytest.raises(ValueError,match="physical"):
        M.compare_native_drc({}, {})


def test_native_save_reopen_array_reordering_is_not_a_false_layout_failure():
    original=P.source()
    after=json.loads(json.dumps(original))
    for key in ("components","pads","vias","nets"):
        after[key].reverse()
    after["lines"].append({**original["lines"][0],
                           "id":"NEW_NATIVE_CONTROL_ONLY",
                           "net":"OC","layer":1})
    result=M.compare_readback(original,after)
    assert result["problems"] == [], result["problems"]
    assert result["added_nets"] == ["OC"]
    assert result["readback_accepted_for_native_drc"] is True


def test_latest_checked_in_first_stage_is_a_real_native_132_line_183_open_board():
    actual=M.stage1_verified()
    assert len(actual["lines"]) == 132
    assert len(actual["pads"]) == 299
    assert len(actual["vias"]) == 18
    assert len(actual["nets"]) == 65
    assert M.sha(M.STAGE1_BOARD) == (
        "59ec7ab3f8dd17ba76b465e9686bce58647db66b76770a4762c0b7e33e33afb0"
    )
    import json
    d=json.loads(M.STAGE1.DELTA.read_text(encoding="utf-8"))
    assert d["native_reopen_drc"]["Connection Error"]==183
    assert d["native_reopen_drc"]["Netlist Error"]==1
    assert d["native_connection_errors_reduced"]==16
    assert d["full_board_fabrication_approved"] is False


def test_beta_native_pcb_document_must_be_opened_and_cli_budget_exceed_60s():
    js=M.js_body(M.plan())
    assert "eda.dmt_Project.getCurrentProjectInfo()" in js
    assert "eda.dmt_EditorControl.openDocument(pcbUuid)" in js
    assert js.index("openDocument(pcbUuid)") < js.index("pcb_Document.autoRouting")
    assert "RoutingNets: allow" in js
    assert "ignoreNets: excluded" in js
    import inspect
    body=inspect.getsource(M.apply)
    assert "timeout_ms=930000" in body
    assert "timeout_s=960" in body


def test_known_60s_timeout_is_safe_to_retry_only_on_identical_unsaved_copy(tmp_path,monkeypatch):
    parent=tmp_path/"real_first_stage_132.eprj2"
    target=tmp_path/"previous_failed_copy.eprj2"
    receipt=tmp_path/"previous_failed_apply.json"
    approval=tmp_path/"approved_native_drc.json"
    parent.write_bytes(b"actual validated board")
    target.write_bytes(parent.read_bytes())
    receipt.write_text('{"ok":false,"error":{"code":"REQUEST_TIMEOUT"}}',encoding="utf-8")
    monkeypatch.setattr(M,"STAGE1_BOARD",parent)
    monkeypatch.setattr(M,"STAGE2_BOARD",target)
    monkeypatch.setattr(M,"STAGE2_APPLY",receipt)
    monkeypatch.setattr(M,"STAGE2_REPORT",approval)
    before=target.read_bytes()
    assert "byte-identical" in M.prepare_stage2_copy()
    assert target.read_bytes()==before
    target.write_bytes(before+b"unverified copper")
    with pytest.raises(FileExistsError,match="differs"):
        M.prepare_stage2_copy()
    target.write_bytes(before)
    approval.write_text('{"status":"approved"}',encoding="utf-8")
    with pytest.raises(FileExistsError,match="already exists"):
        M.prepare_stage2_copy()
    approval.unlink()
    receipt.write_text('{"ok":true,"value":{"saved":true}}',encoding="utf-8")
    with pytest.raises(FileExistsError,match="known timeout failure"):
        M.prepare_stage2_copy()
    receipt.unlink()
    with pytest.raises(FileExistsError,match="no recorded timeout"):
        M.prepare_stage2_copy()


def test_missing_stage2_copy_is_created_without_overwriting_132_line_parent(tmp_path,monkeypatch):
    source=tmp_path/"valid.eprj2"
    candidate=tmp_path/"candidate.eprj2"
    source.write_bytes(b"the accepted G1 first stage")
    monkeypatch.setattr(M,"STAGE1_BOARD",source)
    monkeypatch.setattr(M,"STAGE2_BOARD",candidate)
    assert M.prepare_stage2_copy()=="created fresh copy"
    assert candidate.read_bytes()==source.read_bytes()
    assert source.read_bytes()==b"the accepted G1 first stage"


def test_drc_sha_rejects_any_content_change_but_allows_only_documented_lf_crlf(tmp_path):
    import hashlib
    raw=b'{"ok":true,\n"native":183}\n'
    f=tmp_path/"raw_drc.json"
    f.write_bytes(raw)
    win_hash=hashlib.sha256(raw.replace(b"\n",b"\r\n")).hexdigest()
    assert M.original_drc_hash_verified(f,win_hash)
    assert M.original_drc_hash_verified(f,hashlib.sha256(raw).hexdigest())
    f.write_bytes(raw.replace(b"183",b"182"))
    assert not M.original_drc_hash_verified(f,win_hash)
    f.write_bytes(raw.replace(b"\n",b"\n\n"))
    assert not M.original_drc_hash_verified(f,win_hash)
    f.write_bytes(b"{}")
    assert not M.original_drc_hash_verified(f,"bad")


def test_native_beta_router_result_must_report_real_success_and_only_allowed_nets():
    js=M.js_body(M.plan())
    assert "result.success !== true" in js
    assert "result.totalNetsCount > allow.length" in js
    assert "result.failedNets.some(net => !allow.includes(net))" in js
    assert "result.successNetsCount > result.totalNetsCount" in js
    assert "if (allow.length !== 5 || excluded.length !== 60)" in js
    assert "await eda.pcb_Document.save()" in js
    assert js.index("result.success !== true") < js.index("pcb_Document.save()")
    assert '"DT"' in js and '"RT"' in js and '"OC1"' in js

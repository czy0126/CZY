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
    assert p["source_sha256"]=="17fbae57bebdab6e0e18b6e4ddd177da98e25ca646bcb71d5e482a3b8db7b37e"
    assert p["net_count"]==65
    assert p["routing_nets"]==["RUN","SS","DT","RT","OC1","OC","OCM","OCD"]
    assert len(p["ignoring_nets"])==57
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

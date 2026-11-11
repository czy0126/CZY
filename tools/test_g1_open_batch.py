"""Native 199-open board: route actual signal pins, never short a power/Kelvin net."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
G1=ROOT/"hardware/dcx_main/g1"
sys.path.insert(0,str(G1))
import route_open_connections as P
import apply_g1_open_batch as A


def test_parent_is_real_current_107_line_saved_native_board():
    board=P.source()
    assert P.SOURCE.name=="dcx_main_board_g1_signal_stubs.eprj2"
    assert hashlib.sha256(P.SOURCE.read_bytes()).hexdigest()=="17fbae57bebdab6e0e18b6e4ddd177da98e25ca646bcb71d5e482a3b8db7b37e"
    assert len(board["lines"])==107
    assert len(board["pads"])==299
    assert len(board["vias"])==18
    assert P.categories(json.loads(P.DRC.read_text(encoding="utf-8")))["Connection Error"]==199
    assert P.categories(json.loads(P.DRC.read_text(encoding="utf-8")))["Netlist Error"]==1


def test_batch_only_safe_reviewed_low_current_nets_and_no_conflicts():
    report=P.report()
    assert report["preflight_problems"]==[],report["preflight_problems"][:15]
    assert report["routes"]==12
    assert report["segments"]==26
    assert report["new_vias"]==0
    assert report["native_before_drc"]["Connection Error"]==199
    assert not report["actual_easyeda_applied"]
    assert not report["native_drc_improved"]
    assert not report["fabrication_approved"]
    x=P.copper()
    assert set(x)=={"VCC12_S","DT","RT","VD1_A","VD2_A","VD3_A",
                    "VD4_A","OC1","OCD","OCM"}
    assert all(v["layer"]==1 and v["width"]==pytest.approx(.20) for v in x.values())
    assert all(not (k.startswith(("SEC","PRI","GA","GB","VG","REG"))
                    or k in P.BANNED) for k in x)


def test_can_fix_previous_directly_blocked_u4_supply_without_shorting_u4_8():
    plan=P.copper()
    p=plan["VCC12_S"]["paths"][0]
    assert len(p)==4
    assert p[0][1]==pytest.approx(67,abs=.02)
    assert p[1][1]==pytest.approx(68,abs=.02)
    assert p[2][1]==pytest.approx(68,abs=.02)
    assert p[-1][1]==pytest.approx(69.4,abs=.02)


def test_first_and_last_endpoint_are_actual_same_net_component_pads():
    readback=P.source()
    for net,from_ref,from_pin,to_ref,to_pin,shape in P.PAIRS:
        plan=P.copper()[net]["paths"]
        a=P.nativepad(readback,from_ref,from_pin,net)
        b=P.nativepad(readback,to_ref,to_pin,net)
        assert any(abs(points[0][0]-a[0])<.01 and abs(points[0][1]-a[1])<.01 and
                   abs(points[-1][0]-b[0])<.01 and abs(points[-1][1]-b[1])<.01
                   for points in plan)


def test_wrong_net_pad_rejected_before_eda():
    p=P.source()
    with pytest.raises(ValueError,match="Native pad identity changed"):
        P.nativepad(p,"QL","1","VCC12_S")


def test_unqualified_power_net_batch_refused(monkeypatch):
    old=P.PAIRS
    monkeypatch.setattr(P,"PAIRS",old+(("VOUT","Cout","1","J_OUT","1","direct"),))
    with pytest.raises(ValueError,match="Unsafe current"):
        P.copper()


def test_unchanged_native_drc_does_not_count_as_routing_improvement(tmp_path,monkeypatch):
    baseline=P.categories(json.loads(P.DRC.read_text(encoding="utf-8")))
    assert baseline["Connection Error"]==199
    fake=tmp_path/"native_drc.json"
    def make(n,netlist=1,physical=0):
        def group(k,count):
            return {"name":k,"list":[{"list":[{"errorType":"test"} for _ in range(count)]}]}
        fake.write_text(json.dumps({"ok":True,"value":{"raw":[group("Connection Error",n),
                            group("Netlist Error",netlist),group("Physical Error",physical)]}}))
    monkeypatch.setattr(A,"AFTER_DRC",fake)
    make(199)
    with pytest.raises(ValueError,match="did NOT reduce"):
        A.compare_actual_drc()
    make(198,2,0)
    with pytest.raises(ValueError,match="netlist or physical"):
        A.compare_actual_drc()

    make(198,1,1)
    with pytest.raises(ValueError,match="netlist or physical"):
        A.compare_actual_drc()


@pytest.mark.parametrize("payload",[
    {"ok":False,"value":{"raw":[]}},
    {"ok":True,"value":{"raw":[]}},
    {"ok":True,"value":{"raw":[{"name":"Connection Error","list":None}]}},
    {"ok":True,"value":{"raw":[{"name":"Connection Error","list":[{}]}]}},
])
def test_invalid_native_drc_cannot_be_zero_errors(payload):
    with pytest.raises(ValueError):
        P.categories(payload)


def test_new_error_category_is_not_ignored(tmp_path,monkeypatch):
    data=json.loads(P.DRC.read_text(encoding="utf-8"))
    data["value"]["raw"]=[
        {"name":"Connection Error","list":[{"list":[{}]*183}]},
        {"name":"Netlist Error","list":[{"list":[{}]}]},
        {"name":"Unexpected Rule Error","list":[{"list":[{}]}]},
    ]
    data["value"]["count"]=3
    path=tmp_path/"new_category.json"
    path.write_text(json.dumps(data),encoding="utf-8")
    monkeypatch.setattr(A,"AFTER_DRC",path)
    with pytest.raises(ValueError,match="new native DRC"):
        A.compare_actual_drc()


def test_a_nonzero_baseline_category_cannot_disappear(tmp_path,monkeypatch):
    """An absent category is not zero errors: it is a truncated payload.

    The 199 baseline is the denominator of the whole comparison, so an ``after``
    report that simply omits "Connection Error" must be refused rather than read
    as 0 < 199.  Categories that are zero in the baseline may be omitted by the
    native reporter; only a category that carried errors is mandatory.
    """
    def group(name,count):
        return {"name":name,"list":[{"list":[{"errorType":"test"} for _ in range(count)]}]}
    after=tmp_path/"dropped_category.json"
    after.write_text(json.dumps({"ok":True,"value":{"raw":[
        group("Netlist Error",1),group("Physical Error",0)]}}),encoding="utf-8")
    monkeypatch.setattr(A,"AFTER_DRC",after)
    with pytest.raises(ValueError,match="disappeared"):
        A.compare_actual_drc()

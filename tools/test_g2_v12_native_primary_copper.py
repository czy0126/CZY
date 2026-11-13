"""Real D1 native V12 primary resonant copper and manufacturing safety gates."""
from __future__ import annotations
from pathlib import Path
import sys,json,pytest

G2=Path(__file__).resolve().parents[1]/"hardware/dcx_main/g2"
sys.path.insert(0,str(G2))
import g2_v12_native_primary_copper as V


def test_source_V11_exact_independently_reopened_and_DRC_not_green():
    n=V.source()
    assert V.sha(V.SOURCE)==V.SOURCE_SHA
    assert {k:len(n[k]) for k in V.EXPECT}==V.EXPECT
    r=json.loads(V.SOURCE_REOPEN.read_text("utf8"))
    assert r["status"]=="V11_INDEPENDENT_NATIVE_GUI_REOPEN_AND_DRC_PASSED_NOT_FOR_FAB"
    assert r["real_native_DRC"]=={"Connection Error":149,"Netlist Error":1}
    assert r["fabrication_approved"] is False


def test_two_actual_source_locked_native_power_pad_routes_clear_all_other_nets():
    p=V.plan()
    assert p==json.loads(V.PLAN.read_text("utf8"))
    assert p["source_native_islands"]=={"CR_CT":2,"PRI_T1":2}
    assert p["proposed_native_islands"]=={"CR_CT":1,"PRI_T1":1}
    assert p["physical_preflight_issues"]==[]
    assert len(p["new_top_primary_net_tracks"])==2
    assert {x["net"] for x in p["new_top_primary_net_tracks"]}=={"CR_CT","PRI_T1"}
    assert all(x["layer"]==1 for x in p["new_top_primary_net_tracks"])
    assert p["not_an_output_100A_bus"] is True
    assert p["fabrication_approved"] is False
    assert p["source_magnetics_bare_pads_instead_of_approved_devices"] is True


def test_original_schematic_primary_net_correspondence_for_real_existing_pads():
    d=V.source()
    expected=[("CR_CT","Cr","2",None,"PRI_A"),
              ("PRI_T1","Lr","2",None,"PRI_A")]
    for net,start,pin,end,terminal in expected:
        a=V.pin(d,net,start,pin)
        b=V.pin(d,net,end,terminal)
        assert a["Net"]==b["Net"]==net
        assert a["Layer"]==b["Layer"]==1
    p=V.plan()
    route={q["net"]:q for q in p["new_top_primary_net_tracks"]}
    assert route["CR_CT"]["width_mm"]==1.2
    assert route["PRI_T1"]["width_mm"]==3.0
    assert 8.<route["CR_CT"]["length_mm"]<9.
    assert 27.<route["PRI_T1"]["length_mm"]<29.


def test_do_not_claim_hot_copper_loss_or_100A_from_uniform_70um_model():
    p=V.plan()
    for a in p["new_top_primary_net_tracks"]:
        assert a["unverified_copper_thickness_um"]==70
        assert a["upper_uniform_copper_R_100C_mOhm"]>0
        assert a["9p45A_RMS_100C_straight_trace_model_W"]>0
    assert p["manufacturer_DFM_approved"] is False
    assert p["N97_100C_LI_current_safety_qualified"] is False
    assert p["not_an_output_100A_bus"] is True


def test_wrong_actual_v11_saved_binary_must_fail_closed(monkeypatch,tmp_path):
    fake=tmp_path/"not_native.eprj2";fake.write_bytes(b"invalid")
    monkeypatch.setattr(V,"SOURCE",fake)
    with pytest.raises(ValueError,match="hash drift"):
        V.source()


def test_mutated_Cr_CT_original_native_connection_rejected(monkeypatch,tmp_path):
    native=json.loads(V.SOURCE_READBACK.read_text("utf8"))
    assert native["real_native_data"]["pads"]
    p=next(x for x in native["real_native_data"]["pads"] if x.get("ref")=="Cr" and x["PadNumber"]=="2")
    p["Net"]="PGND"
    fake=tmp_path/"phony_readback.json";fake.write_text(json.dumps(native),encoding="utf8")
    monkeypatch.setattr(V,"SOURCE_READBACK",fake)
    with pytest.raises(ValueError,match="G2 P1 raw magnetic pad/part lost"):
        V.plan()

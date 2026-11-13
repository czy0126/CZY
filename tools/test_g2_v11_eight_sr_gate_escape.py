"""D1 V11 real-GUI gate escape must match immutable V10 source and copper geometry."""
from __future__ import annotations
from pathlib import Path
import sys
import json
import copy
import pytest

G2=Path(__file__).resolve().parents[1]/"hardware/dcx_main/g2"
sys.path.insert(0,str(G2))
import g2_v11_eight_sr_gate_escape as V


def test_parent_is_exact_saved_and_independently_reopened_native_V10():
    native=V.frozen()
    assert V.sha(V.SOURCE)==V.SOURCE_SHA
    assert {k:len(native[k]) for k in V.EXPECTED}==V.EXPECTED
    r=json.loads(V.REOPEN.read_text("utf8"))
    assert r["native_drc"]=={"Connection Error":165,"Netlist Error":1}
    assert r["status"]=="INDEPENDENT_V10_NATIVE_REOPEN_WITH_DRC_PASSED_NOT_FOR_FAB"


def test_real_native_pad_route_proposal_source_bound_and_not_fab():
    p=V.plan()
    assert p==json.loads(V.PLAN.read_text("utf8"))
    assert p["source_V10_native_sha256"]==V.SOURCE_SHA
    assert p["geometric_issues"]==[]
    assert p["fabrication_approved"] is False
    assert len(p["real_old_ground_spine_to_delete_ids"])==8
    assert len(p["relocated_ground_spines"])==8
    assert len(p["gate_escape_traces"])==24
    assert len(p["native_new_lines"])==32


def test_all_8_SR_gates_are_connected_in_geometry_and_ground_not_worse():
    p=V.plan()
    for i in range(1,5):
        for s in "AB":
            name=f"G{s}{i}"
            assert p["before_real_native_islands"][name]==2
            assert p["after_simulated_islands"][name]==1
    assert p["before_real_native_islands"]["PGND"]==37
    assert p["after_simulated_islands"]["PGND"]==37


def test_nothing_uses_a_fake_pad_or_replaced_ground_stripe_after_layout():
    p=V.plan()
    native=V.frozen()
    old={x["id"]:x for x in native["lines"]}
    ids=p["real_old_ground_spine_to_delete_ids"]
    assert len(set(ids))==8
    assert all(old[i]["net"]=="PGND" for i in ids)
    for x in p["relocated_ground_spines"]:
        assert x["old_id"] in ids
        assert x["width_mm"]==1
        assert x["new_end_xy_mm"][1]==94
        matching=[y for y in native["pads"] if y.get("ref")==x["ref"] and
               y["Net"]=="PGND" and str(y["PadNumber"])=="2"]
        assert len(matching)==1
        assert V.K.distance_to_box(x["new_start_xy_mm"],V.K.pad_bbox(matching[0]))<.30
    # This is signal routing, never a 100A bus or vendor signed 3D model.
    assert all(x["layer"]==1 and x["width_mm"]==.15 for x in p["gate_escape_traces"])


def test_changed_real_source_hash_fails_closed(tmp_path,monkeypatch):
    bad=tmp_path/"fake.eprj2"
    bad.write_bytes(b"not native EDA")
    monkeypatch.setattr(V,"SOURCE",bad)
    with pytest.raises(ValueError,match="SHA drift"):
        V.frozen()


def test_tampered_V10_independent_DRC_receipt_fails_closed(tmp_path,monkeypatch):
    a=json.loads(V.REOPEN.read_text("utf8"))
    a["native_drc"]["Netlist Error"]=0
    bad=tmp_path/"pretendDRC.json"
    bad.write_text(json.dumps(a),encoding="utf8")
    monkeypatch.setattr(V,"REOPEN",bad)
    with pytest.raises(ValueError,match="independent GUI reopen not proven"):
        V.frozen()

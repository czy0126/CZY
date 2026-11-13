"""Source-locked regression for V15 T4 native EasyEDA power-cell relocation."""
import hashlib,json,sqlite3
from pathlib import Path
import pytest
import g2_v15_T4_rigid_power_cell_native as L

G=Path(__file__).resolve().parents[1]/"hardware/dcx_main/g2"
SHA="02d59c63c747678849466cc62565c1522bc50586a7dadc06b0829016ab601e75"
BINARY=G/"dcx_main_board_g2_V15_T4_POWER_CELL_UP30MM_WIP_NOT_FOR_FAB.eprj2"
FULL=G/"g2_v15_after_T4_move_native_readback_NOT_FOR_FAB.json"
REC=G/"g2_v15_T4_9part_18line_2via_native_split_edit_once_NOT_FOR_FAB.json"
DRC=G/"g2_v15_T4_real_post_layout_independent_native_DRC_NOT_FOR_FAB.json"
META=G/"g2_v15_T4_saved_native_snapshot_NOT_FOR_FAB.json"

def test_V15_native_binary_real_three_PCBs_and_original_untouched():
    assert BINARY.stat().st_size>3_000_000
    assert hashlib.sha256(BINARY.read_bytes()).hexdigest()==SHA
    assert L.sha(L.V14)==L.V14_SHA
    m=json.loads(META.read_text("utf8"))
    assert m["sha256"]==SHA
    with sqlite3.connect("file:"+BINARY.resolve().as_posix()+"?mode=ro",uri=True) as db:
        d=json.loads(db.execute("select structure from project_structures order by id desc limit 1").fetchone()[0])
    assert set(d["pcbs"])=={"2f6fa2d508d3f9a8","8c496410b2877d3c",L.V15_UUID}
    assert d["pcbs"]["2f6fa2d508d3f9a8"]["title"]=="PCB1"
    assert "V15" in d["pcbs"][L.V15_UUID]["title"]

def test_exact_source_locked_preflight_9parts_18lines_2vias():
    a=L.build()
    original=json.loads(L.PLAN.read_text("utf8"))
    assert json.loads(json.dumps(a))==original
    assert len(a["rigid_cell_9_refdes"])==9
    assert len(a["move_18_real_native_line_IDs"])==18
    assert len(a["move_2_real_native_via_IDs"])==2
    assert a["unlike_net_static_copper_comparisons"]>45000
    assert a["slot_lower_edge_to_SR4A_SEC_pad_after_mm"]==18.179
    assert a["T4_to_SR4A_centre_before_mm"]==62.29
    assert a["T4_to_SR4A_centre_after_mm"]==32.558
    assert a["T4_to_SR4A_centre_reduction_pct"]==47.7
    assert a["fabrication_approved"] is False

def test_true_EasyEDA_native_modifications_all_returned_before_save():
    r=json.loads(REC.read_text("utf8"))
    assert r["status"]=="V15_T4_NATIVE_REAL_LAYOUT_SAVED_DRC_STILL_PENDING"
    v=r["native_api"]["value"]
    assert v["saved"] is True
    assert v["status"]=="V15_T4_NATIVE_9COMP_18LINES_2VIAS_REAL_MOVED_AND_SAVED_WIP"
    assert len(v["changes"]["components"])==9
    assert len(v["changes"]["lines"])==18
    assert len(v["changes"]["vias"])==2
    assert v["counts"]=={"components":149,"pads":423,"lines":484,"vias":104}

def test_native_full_readback_positions_and_signal_islands_followed_cell():
    plan=L.build()
    v=json.loads(FULL.read_text("utf8"))["native"]
    assert [len(v[k]) for k in ("components","pads","lines","vias")]==[149,423,484,104]
    comps={x["ref"]:x for x in v["components"]}
    for ref in plan["rigid_cell_9_refdes"]:
        old=plan["original_component_positions_mil"][ref]
        now=comps[ref]
        assert abs(now["X"]-old["X"])<.08
        assert abs(now["Y"]-old["Y"]-30/.0254)<.08
        assert now["Rotation"]==old["Rotation"]
    l={x["id"]:x for x in v["lines"]}
    for raw in plan["move_18_real_native_line_IDs"]:
        now=l[raw["id"]]
        assert now["net"]==raw["net"]
        assert abs(now["y1"]-raw["startY"]-30/.0254)<.08
        assert abs(now["y2"]-raw["endY"]-30/.0254)<.08
    through={x["id"]:x for x in v["vias"]}
    for raw in plan["move_2_real_native_via_IDs"]:
        now=through[raw["id"]]
        assert now["net"]==raw["net"]
        assert abs(now["y"]-raw["y"]-30/.0254)<.08

def test_native_DRC_111_to_112_is_not_electrical_completion():
    d=json.loads(DRC.read_text("utf8"))
    assert d["status"]=="V15_T4_NATIVE_DRC_REAL_VERIFIED_WIP"
    assert d["native"]["value"]["categories"]=={"Connection Error":112}
    assert d["native"]["value"]["outlines"]==13
    assert d["native"]["value"]["rule"]=="JLCPCB Capability(Two Layers Board)"
    assert d["fabrication_approved"] is False

def test_no_claim_of_vendor_DOT_100A_or_EMC_release():
    p=L.build()
    assert p["all_electrical_connections_closed"] is False
    assert p["original_100A_PGND_and_VOUT_straps_must_be_rerouted"] is True
    assert p["true_vendor_CORE_DOT_PINOUT_validated"] is False
    assert p["fabrication_approved"] is False

def test_fail_closed_if_original_baseline_drifted(tmp_path,monkeypatch):
    f=tmp_path/"wrong"
    f.write_bytes(b"bad")
    monkeypatch.setattr(L,"V14",f)
    with pytest.raises(ValueError,match="V14 verified original"):
        L.build()

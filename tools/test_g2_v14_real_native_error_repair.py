"""Source-bound proof of REAL G2 V14 native EasyEDA signal repairs and backside caps.

Read through each native saved binary/source readback; reject synthetic
DRC zero, missing source, altered pin-net, reversed backside capacitor,
and missing actual Native PTH/trace primitive IDs. NOT FOR FAB.
"""
from __future__ import annotations
import hashlib
import json
import math
import sqlite3
from pathlib import Path
import pytest

G=Path(__file__).resolve().parents[1]/"hardware/dcx_main/g2"
SHA=[
 ("dcx_main_board_g2_V14_EILP32_TWELVE_NPTH_12L_STACK_WIP_NOT_FOR_FAB.eprj2","1e76e6865a746a49bea8a9fb87037b0301213faa386f5fdd2d6bdf5550ffbac6"),
 ("dcx_main_board_g2_V14_EILP32_TWELVE_NPTH_OC_FIX_WIP_NOT_FOR_FAB.eprj2","706808f923f60da263ea77ed30236762bc7cf0b3cd58a0db029676e71247c0b8"),
 ("dcx_main_board_g2_V14_EILP32_12NPTH_OC_OCM_WIP_NOT_FOR_FAB.eprj2","80381f0bb00b781dfc635298020638e3757e9ddc99e2987cd8838c10ee4b0260"),
 ("dcx_main_board_g2_V14_EILP32_12NPTH_OC_OCM_OCD_WIP_NOT_FOR_FAB.eprj2","3e279574988af011883dd36ef5565cb50e7f72966020c1fa606a54542e1a62de"),
 ("dcx_main_board_g2_V14_EILP32_12NPTH_OC_OCM_OCD_REG4_BOTTOM_WIP_NOT_FOR_FAB.eprj2","7dd77910bcf7ff3fd0e2be1e4194439a22189aaf353f105bbe1280c104e4f6fc")
]
DRC=[
 ("g2_v14_native_PCB_after_12slots_real_DRC_raw_NOT_FOR_FAB.json",149),
 ("g2_v14_after_OC_independent_same_session_second_DRC_NOT_FOR_FAB.json",124),
 ("g2_v14_OCM_native_2via_save_after_DRC_NOT_FOR_FAB.json",122),
 ("g2_v14_OCD_real_native_signal_fix_DRC_NOT_FOR_FAB.json",120),
 ("g2_v14_after_REG4_independent_second_native_DRC_bottom_four_NOT_FOR_FAB.json",111)
]
API_RECEIPTS=[
 ("g2_v14_OC_native_real_DRC_fix_attempt_NOT_FOR_FAB.json","api",3,2),
 ("g2_v14_OCM_native_2via_save_after_DRC_NOT_FOR_FAB.json","native_result",3,2),
 ("g2_v14_OCD_real_native_signal_fix_DRC_NOT_FOR_FAB.json","native_response",4,2),
 ("g2_v14_four_bottom_REG_capacitors_native_DRC_applied_NOT_FOR_FAB.json","native_result",16,8)
]

def load(name):return json.loads((G/name).read_text("utf8"))
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def counted(data):
    if "categories" in data:return data["categories"]
    if "native" in data and "cat" in data["native"]["value"]:return data["native"]["value"]["cat"]
    if "native_result" in data:return data["native_result"]["value"]["categories"]
    raise AssertionError("Unrecognized real DRC evidence")

@pytest.mark.parametrize("filename,sha",SHA)
def test_intermediate_real_native_eprj2_exists_and_sha_matches(filename,sha):
    p=G/filename
    assert p.stat().st_size>2_000_000
    assert digest(p)==sha
    with sqlite3.connect(f"file:{p.resolve().as_posix()}?mode=ro",uri=True) as db:
        struct=db.execute("select structure from project_structures order by id desc limit 1").fetchone()
        assert struct is not None
        docs=json.loads(struct[0])
        assert "2f6fa2d508d3f9a8" in docs["pcbs"]
        assert "8c496410b2877d3c" in docs["pcbs"]
        assert docs["pcbs"]["2f6fa2d508d3f9a8"]["title"]=="PCB1"

def test_four_nets_repaired_sequentially_with_native_DRC_and_no_physical_errors():
    summaries=[]
    for name, expected in DRC:
        source=load(name)
        if "raw_native" in source and source.get("categories"):drc=source["categories"]
        elif "native_result" in source:drc=source["native_result"]["value"]["categories"]
        elif "native_response" in source:drc=source["native_response"]["value"]["categories"]
        elif "native" in source:drc=source["native"]["value"]["cat"]
        else:raise AssertionError("unrecognized real DRC")
        assert drc.get("Connection Error")==expected
        assert drc.get("Netlist Error",0)==0 or expected==149
        assert drc.get("Physical Error",0)==0
        summaries.append(expected)
    assert summaries==[149,124,122,120,111]
    # 149 -> 124 included recalculation of deleted transformer raw pads,
    # not 25 actual routed opens from the single OC fix!
    assert summaries[-4:]==[124,122,120,111]

@pytest.mark.parametrize("fname,api_field,tracks,vias",API_RECEIPTS)
def test_each_native_EasyEDA_apply_called_save_and_new_real_primitives(fname,api_field,tracks,vias):
    r=load(fname)
    assert r["fabrication_approved"] is False
    data=r[api_field]["value"]
    assert data["saved"] is True
    assert len(data.get("newLines",data.get("lineIds",[])))==tracks
    assert len(data.get("newVia",data.get("viaIds",[])))==vias
    assert len(set(data.get("newLines",data.get("lineIds",[]))))==tracks
    assert len(set(data.get("newVia",data.get("viaIds",[]))))==vias

def test_current_board_is_real_149parts_423pads_484lines_104vias_and_bottom_four():
    data=load("g2_v14_after_REG4_native_full_copper_readback_NOT_FOR_FAB.json")
    assert data["board_uuid"]=="8c496410b2877d3c"
    b=data["native"]
    assert (len(b["components"]),len(b["pads"]),len(b["lines"]),len(b["vias"]))==(149,423,484,104)
    cap={c["ref"]:c for c in b["components"] if c["ref"] in ("C7","C8","C9","C10")}
    assert len(cap)==4
    assert all(c["Rotation"]==180 for c in cap.values())
    for i in range(1,5):
        ref=f"C{i+6}"
        c=cap[ref]
        pins=[p for p in b["pads"] if p.get("ref")==ref]
        assert len(pins)==2
        assert {p["PadNumber"]:p["Net"] for p in pins}=={"1":f"REG{i}","2":"PGND"}
        assert {p["Layer"] for p in pins}=={2}
        assert 74.95< -pins[0]["Y"]*.0254 <75.05

def test_actual_native_created_pth_and_tracks_preserved_by_final_readback():
    b=load("g2_v14_after_REG4_native_full_copper_readback_NOT_FOR_FAB.json")["native"]
    t={x["id"] for x in b["lines"]}
    v={x["id"] for x in b["vias"]}
    assert len(t)==484 and len(v)==104
    for fname,field,nt,nv in API_RECEIPTS:
        result=load(fname)[field]["value"]
        assert set(result.get("newLines",result.get("lineIds",[]))).issubset(t)
        assert set(result.get("newVia",result.get("viaIds",[]))).issubset(v)

def test_real_final_EasyEDA_independent_DRC_and_project_snapshot():
    c=load("g2_v14_after_REG4_independent_second_native_DRC_bottom_four_NOT_FOR_FAB.json")
    assert c["status"]=="REG4_BOTTOM_FOUR_SEPARATE_NATIVE_DRC_RECHECK_NOT_FOR_FAB"
    v=c["native"]["value"]
    assert v["cat"]=={"Connection Error":111}
    assert v["counts"]=={"components":149,"pads":423,"lines":484,"vias":104}
    assert {x["ref"] for x in v["caps"]}=={"C7","C8","C9","C10"}
    assert all(x["layer"]==2 and x["rotation"]==180 for x in v["caps"])
    assert v["rule"]=="JLCPCB Capability(Two Layers Board)"
    # Explicitly reject "12-layer DFM already verified" claim.
    assert c["fabrication_approved"] is False
    r=load("g2_v14_REG4_real_saved_snapshot_NOT_FOR_FAB.json")
    assert r["status"]=="FOUR_TRUE_BOTTOM_REG_CAPS_NATIVE_BINARY_SAVED_NOT_FOR_FAB"
    assert r["sha256"]==SHA[-1][1]
    assert r["manufacturer_stackup_signed"] is False

def test_gate_original_v11_unchanged_and_do_not_release_real_hardware():
    v11=G/"dcx_main_board_g2_V11_NATIVE_SR_GATE_ESCAPE_NOT_FOR_FAB.eprj2"
    assert digest(v11)=="d90ca22079ad7245e8c3904eb8369da58c705ae39b56574bf7843dad34cad89b"
    d=load("g2_v14_real_native_12NPTH_saved_binary_snapshot_NOT_FOR_FAB.json")
    assert d["original_PCB1_uuid"]=="2f6fa2d508d3f9a8"
    assert d["new_V14_actual_PCB_uuid"]=="8c496410b2877d3c"
    assert d["fabrication_approved"] is False

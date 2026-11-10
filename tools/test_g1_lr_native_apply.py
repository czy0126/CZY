"""Native ECO runner verification from synthetic readback, no EDA mutation in CI.

A generated mock candidate is not evidence that an actual .eprj2 was changed.
It tests only fail-closed readback comparisons and the exact intended moves.
"""
from __future__ import annotations
import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
G1=ROOT/"hardware/dcx_main/g1"
sys.path.insert(0,str(G1))
spec=importlib.util.spec_from_file_location("g1_lr_native_apply",G1/"apply_lr_repack.py")
n=importlib.util.module_from_spec(spec)
spec.loader.exec_module(n)


@pytest.fixture
def source_and_mock():
    original=json.loads(n.G.ACTIVE_READBACK.read_text(encoding="utf-8"))["value"]
    plan=json.loads(n.R.PLAN.read_text(encoding="utf-8"))
    v=copy.deepcopy(original)
    old={c["ref"]:(c["X"],c["Y"]) for c in original["components"]}
    for c in v["components"]:
        if c["ref"] not in plan["moves"]:continue
        entry=plan["moves"][c["ref"]]
        c["X"]=entry["new_xy_mm"][0]*n.G.MIL_PER_MM
        c["Y"]=-entry["new_xy_mm"][1]*n.G.MIL_PER_MM
        c["Rotation"]=entry.get("rotation_deg",0)
    new={c["ref"]:(c["X"],c["Y"]) for c in v["components"]}
    for p in v["pads"]:
        ref=p.get("ref")
        if ref not in plan["moves"]:continue
        dx=p["X"]-old[ref][0]
        dy=p["Y"]-old[ref][1]
        rot=ref=="Lr"
        p["X"]=new[ref][0]+(-dx if rot else dx)
        p["Y"]=new[ref][1]+(-dy if rot else dy)
        if rot:
            p["Rotation"]=(float(p.get("Rotation") or 0)+180)%360
    return original,{"ok":True,"value":v},plan


def test_synthetic_native_reopen_proof_method_without_claiming_actual_eda(source_and_mock):
    original, mock, plan=source_and_mock
    result=n.native_verify(original,mock,plan)
    assert result["status"]=="REOPENED_NATIVE_CAD_CANDIDATE_REQUIRES_GUI_DRC_AND_3D_REVIEW"
    assert result["moved_refs"]==sorted(plan["moves"])
    assert result["lr_other_pad_intersections"]==0
    assert result["core_board_edge_margin_mm"]==7.0
    assert result["real_assembly_3d_verified"] is False
    assert result["fab_release"] is False


def test_missing_or_unapproved_source_file_is_protected():
    assert n.SOURCE.name=="dcx_main_board_g1_kelvin.eprj2"
    assert n.TARGET.name=="dcx_main_board_g1_lr_repack.eprj2"
    assert n.SOURCE!=n.TARGET
    assert n.READBACK.name=="lr_repack_readback.json"
    assert n.REPORT.name=="lr_repack_native_report.json"


def test_native_reopen_catches_moved_nonparticipant(source_and_mock):
    old, resp, plan=source_and_mock
    altered=copy.deepcopy(resp)
    c=next(c for c in altered["value"]["components"] if c["ref"]=="U3")
    c["X"]+=100
    with pytest.raises(ValueError,match="did not preserve"):
        n.native_verify(old,altered,plan)


def test_native_reopen_catches_a_stale_or_missing_track(source_and_mock):
    old, resp, plan=source_and_mock
    altered=copy.deepcopy(resp)
    altered["value"]["lines"][0]["x1"]+=10
    with pytest.raises(ValueError,match="moved or resized"):
        n.native_verify(old,altered,plan)
    missing=copy.deepcopy(resp)
    missing["value"]["lines"].pop()
    with pytest.raises(ValueError,match="counts"):
        n.native_verify(old,missing,plan)


def test_native_reopen_catches_turned_back_lr_pin(source_and_mock):
    old, resp, plan=source_and_mock
    altered=copy.deepcopy(resp)
    c=next(p for p in altered["value"]["pads"]
           if p.get("ref")=="Lr" and str(p["PadNumber"])=="1")
    c["X"]+=100
    with pytest.raises(ValueError,match="Lr rotation"):
        n.native_verify(old,altered,plan)


def test_native_reopen_catches_changed_pad_net_or_wrong_footprint(source_and_mock):
    old, resp, plan=source_and_mock
    altered=copy.deepcopy(resp)
    p=next(p for p in altered["value"]["pads"]
           if p.get("ref")=="C105" and str(p["PadNumber"])=="1")
    p["Net"]="WRONG"
    with pytest.raises(ValueError,match="pad/net"):
        n.native_verify(old,altered,plan)
    altered=copy.deepcopy(resp)
    p=next(p for p in altered["value"]["pads"]
           if p.get("ref")=="C105" and str(p["PadNumber"])=="1")
    p["Pad"][1]+=10
    with pytest.raises(ValueError,match="footprint"):
        n.native_verify(old,altered,plan)

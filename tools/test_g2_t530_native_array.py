"""G2 72-cap provisional native-EasyEDA land geometry safety guards."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"hardware/dcx_main/g2"))
import plan_t530_72_native as P
import apply_t530_72_native as A
ROUTE=A.R

def test_source_bound_plan_has_72_devices_and_144_distinct_polarized_lands():
    d=P.make()
    assert d["source_board_sha256"]=="9cbeb298287d2f0c4e5cad84ecfa151e44a211a65fd47ced1334daada3c4e1c1"
    assert d["source_board_sha256"]==P.sha(P.C.BASE)
    assert d["original_149_line_connection_errors"]==173
    assert d["part_count"]==72 and d["pad_count"]==144
    assert not d["problems"]
    assert len(d["placements"])==72
    assert sum(len(q["provisional_pads"]) for q in d["placements"])==144
    assert len({pad["number"] for pad in A.pad_rows(d)})==144
    assert {pad["net"] for pad in A.pad_rows(d)}=={"VOUT","PGND"}
    assert all(pad["oem_footprint_approved"] is False for pad in A.pad_rows(d))
    assert not d["hardware_manufacturing_approved"]
    assert not d["schematic_parity_verified"]
    assert d["actual_oem_land_pattern_verified"] is False

def test_relocates_two_lands_away_from_jout_without_resizing_board():
    d=P.make()
    placements={p["ref"]:p for p in d["placements"]}
    assert placements["CHV01"]["centre_mm"]==[7.0,99.0]
    assert placements["CHV63"]["centre_mm"]==[7.0,125.0]
    assert placements["CHV64"]["centre_mm"]==[15.3,125.0]
    assert placements["CHV72"]["centre_mm"]==[148.1,118.2]
    assert len(set(tuple(p["centre_mm"]) for p in placements.values()))==72
    for p in placements.values():
        x,y=p["centre_mm"]
        assert 2<=x-3.8 and x+3.8<=153
        assert 2<=y-2.3 and y+2.3<=129

def test_written_trial_is_exactly_reproducible_and_current():
    d=P.make()
    assert json.loads(P.OUT.read_text(encoding="utf-8"))==d
    assert A.verified_plan()==d

def test_proposed_native_editor_js_is_24_at_a_time_and_no_overwrite():
    j=A.chunk_js(A.pad_rows(P.make())[:24])
    assert "getState_PadNumber" in j
    assert "already on board, refuse double-apply" in j
    assert "pcb_PrimitivePad.create" in j
    assert "return await" in j
    assert j.count('"num":"CHV')==24
    assert "pcb_Document.save" not in j
    assert "pcb_PrimitiveLine" not in j
    assert "pcb_PrimitiveVia" not in j
    assert "pcb_PrimitiveComponent" not in j

def test_real_readback_must_preserve_all_original_pads_tracks_vias_and_nets():
    d=P.make()
    base=P.C.active_native_g1()
    added=[]
    for pad in A.pad_rows(d):
        added.append({"ref":None,
                      "X":pad["centre_mm"][0]/.0254,
                      "Y":-pad["centre_mm"][1]/.0254,
                      "Rotation":0,"Net":pad["net"],
                      "PadNumber":pad["number"],
                      "Layer":1,
                      "Pad":["RECT",pad["size_mm"][0]/.0254,
                             pad["size_mm"][1]/.0254,0]})
    native={**base,"pads":base["pads"]+added}
    assert A.compare_readback(native,d)["native_pad_xy_net_size_verified"]
    wrong={**native,"pads":[*native["pads"][:-1],
           {**native["pads"][-1],"Net":"OC"}]}
    with pytest.raises(ValueError,match="Wrong native land"):
        A.compare_readback(wrong,d)
    wrong_trace={**native,"lines":[*native["lines"][:-1],{**native["lines"][-1],"net":"OC"}]}
    with pytest.raises(ValueError,match="previously accepted 149 native copper"):
        A.compare_readback(wrong_trace,d)


def test_actual_saved_reopened_443_pad_native_candidate_has_hash_bound_drc():
    receipt=json.loads(A.DELTA.read_text(encoding="utf-8"))
    raw=json.loads((A.HERE/(A.PREFIX+"_reopen_readback.json")).read_text(encoding="utf-8"))
    drc=json.loads((A.HERE/(A.PREFIX+"_drc_raw.json")).read_text(encoding="utf-8"))
    assert receipt["status"]=="ACTUAL_144_PROVISIONAL_PAD_NATIVE_SAVE_REOPEN_NOT_FOR_FAB"
    assert receipt["candidate_sha256"]==A.sha(A.TARGET)
    assert receipt["parent_sha256"]==A.sha(P.C.BASE)
    assert receipt["provisional_land_plan_sha256"]==A.sha(P.OUT)
    assert raw["ok"] and drc["ok"]
    assert receipt["readback"]==A.compare_readback(raw["value"],P.make())
    assert ROUTE.categories(drc)==receipt["native_reopen_drc"]
    assert receipt["native_reopen_drc"]["Connection Error"]==324
    assert receipt["native_reopen_drc"]["Netlist Error"]==1
    assert receipt["native_reopen_drc"].get("Physical Error",0)==0
    assert receipt["readback"]["new_trial_lands"]==144
    assert receipt["added_actual_component_instances"]==0
    assert receipt["native_drc_zero"] is False
    assert receipt["fabrication_approved"] is False

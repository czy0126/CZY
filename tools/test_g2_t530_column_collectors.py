"""Actual G2 144-cap-pad native column collector copper acceptance."""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"hardware/dcx_main/g2"))
import route_t530_bank_columns as R

def test_g2_source_identity_and_real_native_108_segment_plan():
    p=R.generate()
    assert p["source_board_sha256"]==R.sha(R.SOURCE)
    assert p["count"]==108 and p["groups"]==36
    assert p["problems"]==[]
    assert set(q["net"] for q in p["segments"])=={"VOUT","PGND"}
    assert len(set((x["start_pad"],x["end_pad"]) for x in p["segments"]))==108
    assert all(q["layer"]==1 and q["width_mm"]==1.6 for q in p["segments"])
    assert not p["real_high_current_pole_bars_done"]
    assert not p["oem_footprint_approved"]
    assert not p["fabrication_approved"]

def test_g2_js_real_net_and_primitive_not_dummy():
    p=R.generate()
    j=R.draw_js(p["segments"][:18])
    assert "pcb_PrimitiveLine.create" in j
    assert "return await" in j
    assert j.count('"net":"PGND"')+j.count('"net":"VOUT"')==18
    assert "pcb_PrimitivePad.create" not in j
    assert "pcb_Document.save" not in j

def test_native_saved_reopened_bank_reduces_drc_with_original_copper_preserved():
    if not R.DELTA.is_file():
        pytest.skip("No accepted native G2 collector yet")
    r=json.loads(R.DELTA.read_text(encoding="utf-8"))
    assert r["status"]=="REAL_G2_CAPACITOR_COLUMN_COPPER_NATIVE_REOPEN_DRC_NOT_FOR_FAB"
    assert r["candidate_sha256"]==R.sha(R.TARGET)
    assert r["parent_sha256"]==R.sha(R.SOURCE)
    assert r["plan_sha256"]==R.sha(R.PLAN)
    assert r["actual_native_drc"]["Connection Error"]<324
    assert r["actual_native_drc"].get("Physical Error",0)==0
    assert r["actual_native_drc"]["Netlist Error"]<=1
    d=json.loads((R.HERE/(R.PREFIX+"_reopen_readback.json")).read_text(encoding="utf-8"))
    assert d["ok"]
    assert r["readback"]==R.review_readback(d["value"],R.generate())
    assert not r["both_pole_bar_connected"]
    assert not r["true_oem_cout_footprint"]
    assert not r["manufacturing_approved"]

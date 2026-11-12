"""Actual G2 two-polarity capacitor-array native routing proof.

This checks connectivity geometry, NOT its 100-A ability.  Native verified
over 257 accepted parent copper lines and all 443 existing pads.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"hardware/dcx_main/g2"))
import connect_t530_both_poles as C
import route_t530_bank_columns as B

def test_source_is_actually_saved_257_line_board():
    d=C.parent()
    assert len(d["lines"])==257
    assert len(d["pads"])==443
    assert C.sha(C.SOURCE)==json.loads(B.DELTA.read_text(encoding="utf-8"))["candidate_sha256"]

def test_52_tracks_18_vias_are_plan_derived_and_other_net_clear():
    d=C.route_rows()
    assert len(d["tracks"])==52
    assert len(d["vias"])==18
    assert d["problems"]==[]
    assert sum(t["net"]=="PGND" for t in d["tracks"])==35
    assert sum(t["net"]=="VOUT" for t in d["tracks"])==17
    assert set(t["layer"] for t in d["tracks"])=={1,2}
    assert all(v["net"]=="VOUT" and v["hole_mm"]==.4 for v in d["vias"])
    assert not d["line_width_100a_qualified"]
    assert not d["via_thermal_100a_qualified"]
    assert not d["two_pole_100a_busbar_qualified"]
    assert not d["manufacturing_approved"]

def test_native_js_is_real_copper_and_vias_not_fake_pads():
    d=C.route_rows()
    j=C.js_tracks(d["tracks"][:13])
    v=C.js_vias(d["vias"][:9])
    assert "pcb_PrimitiveLine.create" in j
    assert "pcb_PrimitiveVia.create" in v
    assert "getTheNumberOfCopperLayers" in j
    assert "pcb_Document.save" not in j+v
    assert "pcb_PrimitivePad.create" not in j+v

def test_reopened_70_new_real_primitives_and_true_native_drc():
    receipt=json.loads(C.DELTA.read_text(encoding="utf-8"))
    plan=json.loads(C.PLAN.read_text(encoding="utf-8"))
    rb=json.loads((C.HERE/(C.PREFIX+"_reopen_readback.json")).read_text(encoding="utf-8"))
    drc=json.loads((C.HERE/(C.PREFIX+"_drc_raw.json")).read_text(encoding="utf-8"))
    assert receipt["status"]=="REAL_G2_BIPOLAR_ARRAY_NETS_SAVED_REOPENED_DRC_NOT_100A_QUALIFIED"
    assert receipt["parent_sha256"]==C.sha(C.SOURCE)
    assert receipt["candidate_sha256"]==C.sha(C.TARGET)
    assert receipt["plan_sha256"]==C.sha(C.PLAN)
    assert plan==C.route_rows()
    assert rb["ok"] and drc["ok"]
    assert C.verify_readback(rb["value"],plan)==receipt["native_readback"]
    assert C.A.R.categories(drc)==receipt["actual_drc"]
    assert receipt["previous_drc"]["Connection Error"]==227
    assert receipt["actual_drc"]["Connection Error"]==175
    assert receipt["actual_drc"]["Netlist Error"]==1
    assert receipt["actual_drc"].get("Physical Error",0)==0
    assert receipt["both_polarity_cap_array_electrically_joined"]
    assert not receipt["100a_current_carrying_and_contacts_qualified"]
    assert not receipt["fabrication_approved"]

def test_reject_any_wrong_net_in_native_source():
    plan=C.route_rows()
    rb=json.loads((C.HERE/(C.PREFIX+"_reopen_readback.json")).read_text(encoding="utf-8"))
    actual=rb["value"]
    # Any change to an existing component must be caught, not treated as an ECO.
    corrupt={**actual,"pads":[{**actual["pads"][0],"Net":"WRONG"}]+actual["pads"][1:]}
    with pytest.raises(ValueError,match="changed old"):
        C.verify_readback(corrupt,plan)

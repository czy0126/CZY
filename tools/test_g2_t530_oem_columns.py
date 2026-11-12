"""Real native G2 16x5 Density-B 112 local top-layer capacitor connections."""
from __future__ import annotations
import json,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"hardware/dcx_main/g2"))
import plan_t530_72_oem_density_b as P
import apply_t530_density_b_native as A
import route_t530_oem_16x5_columns as C

def test_provenance_112_segments_safe_new_oem_geometry_only():
    plan=C.generate()
    assert plan["count"]==112 and plan["groups"]==32
    assert plan["problems"]==[]
    assert plan["source_board_sha256"]==C.sha(A.TARGET)
    assert plan["source_pad_plan_sha256"]==C.sha(P.OUT)
    assert plan["source_readback_sha256"]==C.sha(A.PADS)
    assert len({(p["start_pad"],p["end_pad"]) for p in plan["segments"]})==112
    assert set(x["net"] for x in plan["segments"])=={"PGND","VOUT"}
    assert all(x["layer"]==1 and x["width_mm"]==1.6 for x in plan["segments"])
    assert plan["real_high_current_pole_bars_done"] is False
    assert plan["fabrication_approved"] is False

def test_real_copper_js_targets_source_native_board():
    p=C.generate()
    code=C.draw_js(p["segments"][:17])
    assert "pcb_PrimitiveLine.create" in code
    assert "expected 443 saved OEM/native pads" in code
    assert "return await" in code
    assert "pcb_Document.save" not in code
    assert "pcb_PrimitivePad.create" not in code

def test_saved_reopened_16x5_native_112_lines_reduce_connection_issues():
    evidence=json.loads(C.DELTA.read_text(encoding="utf-8"))
    rb=json.loads((C.HERE/(C.PREFIX+"_reopen_readback.json")).read_text(encoding="utf-8"))
    drc=json.loads((C.HERE/(C.PREFIX+"_drc_raw.json")).read_text(encoding="utf-8"))
    plan=json.loads(C.PLAN.read_text(encoding="utf-8"))
    assert plan==C.generate()
    assert evidence["status"]=="REAL_G2_OEM_DENSITY_B_LOCAL_COLUMN_NATIVE_REOPEN_DRC_NOT_FOR_FAB"
    assert evidence["candidate_sha256"]==C.sha(C.TARGET)
    assert evidence["parent_sha256"]==C.sha(C.SOURCE)
    assert evidence["plan_sha256"]==C.sha(C.PLAN)
    assert rb["ok"] and drc["ok"]
    assert C.review_readback(rb["value"],plan)==evidence["readback"]
    assert C.A.R.categories(drc)==evidence["actual_native_drc"]
    assert evidence["previous_native_drc"]["Connection Error"]==321
    assert evidence["actual_native_drc"]["Connection Error"]==223
    assert evidence["actual_native_drc"]["Netlist Error"]==1
    assert evidence["actual_native_drc"].get("Physical Error",0)==0
    assert evidence["readback"]["new_actual_top_copper_segments"]==112
    assert evidence["readback"]["all_112_real_pad_pairs_covered"] is True
    assert evidence["both_pole_bar_connected"] is False
    assert evidence["true_oem_cout_component_instances"] is False
    assert evidence["manufacturing_approved"] is False

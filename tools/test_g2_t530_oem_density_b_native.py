"""KEMET official 2026 T530 X case Density-B 16x5 CAD landing tests.

Source: official KEMET T52x/T530 Table2 p37; footprint is manufacturer-
dimensioned nominal pads ONLY, not instantiated OEM components or schematic.
"""
from __future__ import annotations
import json,sys
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"hardware/dcx_main/g2"))
import plan_t530_72_oem_density_b as P
import apply_t530_density_b_native as A

def test_18x4_is_rejected_by_manufacturer_density_b_courtyard():
    r=P.make()
    assert r["manufacturer_datasheet"].endswith("KEM_T2076_T52X-530.pdf")
    assert r["density"]=="B" and r["land_case"]=="X1/7343-43"
    assert r["prior_18_column_overlaps_density_b_courtyard_by_mm"]==.82
    assert r["courtyard_x_mm"]==9.12 and r["courtyard_y_mm"]==5.10
    assert r["grid_pitch_x_mm"]>=r["courtyard_x_mm"]
    assert r["grid_pitch_y_mm"]>=r["courtyard_y_mm"]
    assert r["new_cols"]==16 and r["new_rows"]==5
    assert r["total_slots"]==80 and r["collision_free_slots"]==78
    assert r["placement_count"]==72 and r["trial_pad_count"]==144
    assert r["preflight_problems"]==[]
    assert r["nominal_land_geometry_derived_from_manufacturer"] is True
    assert r["actual_72_components_and_schematic_symbols"] is False
    assert r["fabrication_approved"] is False

def test_all_72_have_valid_OEM_dimensions_and_144_polarized_nets():
    report=P.make()
    pad=[p for q in report["placement"] for p in q["pads"]]
    assert len(pad)==144 and len({q["number"] for q in pad})==144
    assert set(x["net"] for x in pad)=={"VOUT","PGND"}
    assert all(x["size_mm"]==[2.37,2.43] for x in pad)
    for comp in report["placement"]:
        x,y=comp["centre_mm"]
        neg,pos=comp["pads"]
        assert neg["net"]=="PGND" and pos["net"]=="VOUT"
        assert pos["centre_mm"][0]-neg["centre_mm"][0]==pytest.approx(6.24)
        assert 2<=x-9.12/2 and x+9.12/2<=153
        assert 2<=y-5.10/2 and y+5.10/2<=129
        assert comp["actual_schematic_component"] is False
        assert comp["manufacturer_library_footprint_instantiated"] is False

def test_manufacturer_plan_is_source_bound_exact_and_js_real_netted_pads():
    plan=P.make()
    assert json.loads(P.OUT.read_text(encoding="utf-8"))==plan
    assert A.checkplan()==plan
    assert len(A.pad_rows(plan))==144
    j=A.js(A.pad_rows(plan)[:24])
    assert "pcb_PrimitivePad.create" in j
    assert 'refus' in j.lower()
    assert 'rect' in j.lower()
    assert "pcb_Document.save" not in j

def test_real_native_saved_144_manufacturer_dimensioned_pads_are_read_back_and_fail_closed():
    if not A.DELTA.exists():
        pytest.skip("actual new OEM-dimensioned native pad candidate has not passed native reopen")
    receipt=json.loads(A.DELTA.read_text(encoding="utf-8"))
    read=json.loads(A.PADS.read_text(encoding="utf-8"))
    drc=json.loads((A.HERE/(A.PREFIX+"_drc_raw.json")).read_text(encoding="utf-8"))
    assert receipt["candidate_sha256"]==A.sha(A.TARGET)
    assert receipt["source_sha256"]==A.sha(P.SOURCE)
    assert receipt["plan_sha256"]==A.sha(P.OUT)
    assert read["ok"] and drc["ok"]
    assert A.review(read["value"],P.make())==receipt["readback"]
    assert A.R.categories(drc)==receipt["native_drc"]
    assert receipt["readback"]["new_144_netted_manufacturer_nominal_lands"]==144
    assert receipt["readback"]["true_72_component_instances_added"]==0
    assert receipt["real_100A_both_pole_copper_qualified"] is False
    assert receipt["fabrication_approved"] is False

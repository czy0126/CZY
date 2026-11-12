"""Manufacturer X1/7343-43 Density-B 16x5 nominal landing, real native ECO.

This preserves the limitation: all 144 pads are native pads, NOT 72 actual
components. It requires OEM schematic parity, solder paste verification,
mechanical height and 100A bus/thermal design before a fabrication release.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"hardware/dcx_main/g2"))
import plan_t530_72_oem_density_b as P
import apply_t530_density_b_native as A

def test_18_column_nominal_density_B_standoff_fails_and_16x5_passes():
    r=P.make()
    assert r["manufacturer_datasheet"].endswith("/KEM_T2076_T52X-530.pdf")
    assert r["density"]=="B" and r["land_case"]=="X1/7343-43"
    assert r["prior_18_column_overlaps_density_b_courtyard_by_mm"]==.82
    assert r["courtyard_x_mm"]==9.12 and r["courtyard_y_mm"]==5.1
    assert r["grid_pitch_x_mm"]>=r["courtyard_x_mm"]
    assert r["grid_pitch_y_mm"]>=r["courtyard_y_mm"]
    assert r["new_cols"]==16 and r["new_rows"]==5
    assert r["total_slots"]==80 and r["collision_free_slots"]==78
    assert r["placement_count"]==72 and r["trial_pad_count"]==144
    assert r["preflight_problems"]==[]
    assert r["actual_72_components_and_schematic_symbols"] is False
    assert r["fabrication_approved"] is False

def test_real_72_geometry_and_independently_polarized_144_nets():
    r=P.make()
    p=[z for c in r["placement"] for z in c["pads"]]
    assert len(p)==144 and len({x["number"] for x in p})==144
    assert set(x["net"] for x in p)=={"PGND","VOUT"}
    assert all(x["size_mm"]==[2.37,2.43] and x["layer"]==1 for x in p)
    for c in r["placement"]:
        neg,pos=c["pads"]
        assert neg["net"]=="PGND" and pos["net"]=="VOUT"
        assert pos["centre_mm"][0]-neg["centre_mm"][0]==pytest.approx(6.24)
        assert c["actual_schematic_component"] is False
        assert c["manufacturer_library_footprint_instantiated"] is False

def test_native_batch_script_enforces_monotone_pad_count_and_no_duplicate_apply():
    r=P.make()
    assert json.loads(P.OUT.read_text(encoding="utf-8"))==r
    assert A.checkplan()==r
    assert len(A.pad_rows(r))==144
    js=A.js(A.pad_rows(r)[:24],299)
    js2=A.js(A.pad_rows(r)[24:48],323)
    assert "pcb_PrimitivePad.create" in js
    assert "incorrect before-batch native pad count" in js
    assert "expected=299" in js
    assert "expected=323" in js2
    assert "pcb_Document.save" not in js
    assert A.TARGET.name.endswith("V2_144_LANDS_NOT_FOR_FAB.eprj2")

def test_actual_native_reopen_all_144_nominal_pads_drc_and_provenance():
    assert A.DELTA.is_file(), "native 144-pad candidate absent"
    d=json.loads(A.DELTA.read_text(encoding="utf-8"))
    rb=json.loads(A.PADS.read_text(encoding="utf-8"))
    drc=json.loads((A.HERE/(A.PREFIX+"_drc_raw.json")).read_text(encoding="utf-8"))
    assert d["source_sha256"]==A.sha(P.SOURCE)
    assert d["candidate_sha256"]==A.sha(A.TARGET)
    assert d["plan_sha256"]==A.sha(P.OUT)
    assert d["status"]=="REAL_144_OEM_DIMENSIONED_PROVISIONAL_NATIVE_PAD_CAD_NOT_FOR_FAB"
    assert rb["ok"] and drc["ok"]
    assert A.review(rb["value"],P.make())==d["readback"]
    assert A.R.categories(drc)==d["native_drc"]
    assert d["native_drc"]["Connection Error"]==321
    assert d["native_drc"]["Netlist Error"]==1
    assert d["native_drc"].get("Physical Error",0)==0
    assert d["readback"]["new_144_netted_manufacturer_nominal_lands"]==144
    assert d["real_72_schematic_component_instances"] is False
    assert d["real_100A_both_pole_copper_qualified"] is False
    assert d["fabrication_approved"] is False

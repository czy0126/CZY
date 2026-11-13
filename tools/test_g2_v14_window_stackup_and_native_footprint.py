"""V14 ELP32 real native footprint persistence and ferrite window fail-closed."""
from __future__ import annotations

import json
from pathlib import Path
import pytest

import g2_v14_window_stackup_gate as W
import g2_v14_through_board_magnetics as V

G2=V.G2

def test_cold_elp32_window_minimum_with_assembly_clearances():
    x=W.build()
    assert x==json.loads(W.OUT.read_text("utf8"))
    assert x["status"]=="12L_4OZ_DOES_NOT_FIT_3P05MM_MIN_WINDOW_CONSERVATIVE_ASSEMBLY"
    assert x["core_E_window_guaranteed_min_mm"]==pytest.approx(3.05)
    assert x["estimated_board_worst_allowed_mm"]==pytest.approx(2.45)
    assert x["manufacturer_full_DFM_approved"] is False
    assert x["native_winding_applied_to_PCB"] is False


def test_12layer_4oz_stackup_fails_even_if_DC_loss_lower():
    x=W.build()
    c={d["case"]:d for d in x["cases"]}
    assert not c["12L_4OZ_0P10MM_DIELECTRIC"]["fits_provisional_ferrite_window"]
    assert c["12L_4OZ_0P10MM_DIELECTRIC"]["estimated_board_worst_stack_mm"]==pytest.approx(2.97)
    assert c["12L_2OZ_0P10MM_DIELECTRIC"]["fits_provisional_ferrite_window"]
    assert c["12L_3OZ_0P10MM_DIELECTRIC"]["estimated_board_worst_stack_mm"]==pytest.approx(2.55)
    assert not c["12L_3OZ_0P10MM_DIELECTRIC"]["fits_provisional_ferrite_window"]
    assert c["12L_3OZ_0P09MM_DIELECTRIC_CUSTOM"]["estimated_board_worst_stack_mm"]==pytest.approx(2.44)
    assert c["12L_3OZ_0P09MM_DIELECTRIC_CUSTOM"]["fits_provisional_ferrite_window"] is True
    assert all(not item["manufacturer_approved"] for item in c.values())


def test_3oz_custom_stack_hot_DC_loss_parametric_not_factory_verification():
    q=W.build()["custom_12L_3OZ_copper_hot_DC_screen"]
    assert q["estimated_100C_4core_copper_DC_loss_W"]>4
    assert q["part_primary_4core_W"]>0
    assert q["part_secondary_4core_W"]>0
    assert q["actual_200kHz_copper_AC_loss_and_blind_vias_NOT_included"] is True
    assert q["factory_12L_3OZ_inner_Cu_and_90um_P_to_S_dielectric_signed"] is False


def test_own_native_footprint_planned_3_real_board_outline_contours():
    a=json.loads((G2/"g2_v14_native_three_slot_library_plan_NOT_FOR_FAB.json").read_text("utf8"))
    assert a["source_V11_native_sha256"]==V.SOURCE_SHA
    assert a["source_V14_geometry_sha256"]==V.sha(V.OUT)
    assert a["reuse_existing_V13_GUI_only"] is True
    assert a["project_PCB_geometry_will_remain_untouched"] is True
    assert len(a["slot_polygons"])==3
    assert [item["name"] for item in a["slot_polygons"]]==["LEFT","CENTRE","RIGHT"]
    assert all(item["PCB_layer_id_board_outline"]==11 for item in a["slot_polygons"])
    assert all(item["native_line_width_mil"]==1 for item in a["slot_polygons"])


def test_actual_native_footprint_created_saved_and_reopened_without_new_GUI():
    created=json.loads((G2/"g2_v14_native_three_slot_library_created_once_NOT_FOR_FAB.json").read_text("utf8"))
    applied=json.loads((G2/"g2_v14_native_three_slot_contours_created_once_NOT_FOR_FAB.json").read_text("utf8"))
    verified=json.loads((G2/"g2_v14_native_three_slot_saved_reopened_NOT_FOR_FAB.json").read_text("utf8"))
    plan=json.loads((G2/"g2_v14_native_three_slot_library_plan_NOT_FOR_FAB.json").read_text("utf8"))
    assert created["status"]=="NATIVE_LIBRARY_CREATE_CONFIRMED_NOT_FOR_FAB"
    assert applied["status"]=="THREE_NATIVE_BOARDOUTLINE_CUTOUT_CONTOURS_CREATED_NOT_FOR_FAB"
    assert verified["status"]=="THREE_NATIVE_BOARDOUTLINE_CONTOURS_SAVED_AND_REOPENED_IN_SAME_GUI_NOT_FOR_FAB"
    assert created["native_reply"]["value"]["project"]==plan["existing_GUI_project_name"]
    assert created["session_id"]==applied["session_id"]
    assert verified["original_V13_board_unchanged"] is True
    assert verified["native_PCB_cutout_not_placed"] is True
    assert verified["native_response"]["value"]["saved"] is True
    assert verified["native_response"]["value"]["pad_count"]==0
    assert verified["native_response"]["value"]["count"]==3
    old=applied["native_response"]["value"]["created"]
    new=verified["native_response"]["value"]["rows"]
    assert {x["id"] for x in old}=={x["id"] for x in new}
    assert len(old)==3
    for chosen,actual in zip(plan["slot_polygons"],new):
        assert actual["layer"]==11
        x=chosen["native_polygon_source_mil"]
        y=actual["polygon_source"]
        assert len(x)==len(y)
        for a,b in zip(x,y):
            if isinstance(a,str): assert a==b
            else: assert abs(a-b)<.0001  # native 0.0001mil quantization
    assert V.sha(G2/"dcx_main_board_g2_V13_FIVE_MAGNETICS_LOGICAL_LANDING_TRIAL_NOT_FOR_FAB.eprj2")==V.SOURCE_SHA


def test_tampered_12slot_source_blocks_window_model(monkeypatch,tmp_path):
    content=json.loads(W.IN.read_text("utf8"))
    content["slot_count"]=10
    fake=tmp_path/"bad.json";fake.write_text(json.dumps(content),encoding="utf8")
    monkeypatch.setattr(W,"IN",fake)
    with pytest.raises(ValueError,match="baseline"):
        W.build()


def test_thickness_failure_is_not_overridden_by_economic_preference():
    z=W.one_case("whatif",12,140,.1)
    assert z["fits_provisional_ferrite_window"] is False
    z=W.one_case("whatif",12,70,.1)
    assert z["fits_provisional_ferrite_window"] is True
    assert z["manufacturer_approved"] is False

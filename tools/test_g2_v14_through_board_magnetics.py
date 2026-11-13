"""Physical regression for 12 ELP32 NPTH slots against actual V11 native CAD."""
from __future__ import annotations
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import pytest

import g2_v14_through_board_magnetics as V


def test_live_native_baseline_source_and_one_sided_are_not_guessed():
    pcb,pins=V.data()
    assert V.sha(V.V11)==V.SOURCE_SHA
    assert len(pcb["components"])==149
    assert len(pcb["pads"])==443
    assert len(pcb["lines"])==465
    assert len(pcb["vias"])==93
    assert len(pins["pin_rows"])==24
    side=json.loads(V.COMPONENT_SIDES.read_text("utf8"))["source_V13_native"]
    assert side["layers"]=={"1":149}


def test_exact_four_triple_elp32_NPTH_slots_per_TDK_drawings():
    model=V.build()
    assert model["slot_count"]==12
    assert len(set(s["id"] for s in model["slots"]))==12
    assert {s["device"] for s in model["slots"]}==set(V.REFS)
    for ref,cx in zip(V.REFS,V.CENTERS):
        s=[x for x in model["slots"] if x["device"]==ref]
        assert {x["leg"] for x in s}=={"LEFT","CENTRE","RIGHT"}
        assert [x["center_x_mm"] for x in s]==pytest.approx(
             [cx-14.2875,cx,cx+14.2875])
        assert [x["width_mm"] for x in s]==[5.5,7.8,5.5]
        assert all(x["length_mm"]==22 for x in s)
        assert all(x["corner_radius_mm"]==.6 for x in s)
        assert all(x["center_y_mm"]==20 for x in s)


def test_npth_tooling_and_outer_leg_position_tolerance_not_handwaved():
    max_outer=(V.CORE_X_NOM_MM+V.CORE_X_TOL_MM-
               (V.OUTER_LEG_SPAN_NOM_MM-V.OUTER_SPAN_TOL_MM))/2
    max_center=V.CENTER_LEG_WIDTH_NOM_MM+V.CENTER_LEG_TOL_MM
    max_length=V.CORE_Y_NOM_MM+V.CORE_Y_TOL_MM
    # ±(0.65+0.50)/4 mm movement of outer leg centre from nominal.
    max_outer_center_drift=(V.CORE_X_TOL_MM+V.OUTER_SPAN_TOL_MM)/4
    assert max_outer_center_drift==pytest.approx(.2875)
    assert V.OUTER_SLOT_W_MM-max_outer-2*V.ROUTER_HALF_TOL_MM-2*V.DESIRED_PER_SIDE_FIT_MM >=2*max_outer_center_drift
    assert V.INNER_SLOT_W_MM-max_center-2*V.ROUTER_HALF_TOL_MM-2*V.DESIRED_PER_SIDE_FIT_MM>=0
    assert V.SLOT_LENGTH_MM-max_length-2*V.ROUTER_HALF_TOL_MM-2*V.DESIRED_PER_SIDE_FIT_MM>=0
    assert V.OUTER_SLOT_W_MM>=1.0
    assert V.INNER_SLOT_W_MM>=1.0


def test_native_collision_20_old_pads_7_output_tracks_3_vias_is_stopline():
    report=V.build()
    assert report["actual_native_V11_overlap_counts"]=={
      "PAD":20,"COPPER_TRACK":7,"VIA":3}
    hits=report["actual_native_V11_overlap_details"]
    pad=[x for x in hits if x["kind"]=="PAD"]
    assert len(pad)==20
    assert all(x["pcb_ref"]=="UNLINKED_MAGNETIC_RAW_PAD" for x in pad)
    assert set(x["net"] for x in hits if x["kind"]=="COPPER_TRACK")=={"VOUT"}
    assert set(x["net"] for x in hits if x["kind"]=="VIA")=={"VOUT"}
    assert report["requires_remove_or_rebuild_all_20_old_magnetics_raw_pads"]
    assert report["requires_rewire_output_VOUT_lines_and_vias_around_slots"]
    assert report["native_cutouts_already_applied"] is False


def test_dxf_is_closed_mechanical_not_real_eda_board_or_gerber():
    content=V.dxf(V.build())
    assert content==V.DXF.read_text("utf8")
    assert content.startswith("0\nSECTION\n2\nHEADER")
    assert content.rstrip().endswith("0\nEOF")
    assert content.count("\n8\nV14_NPTH_SLOT_12_PRELIM\n")==12*(
        # one POLYLINE + 4*(8+1) VERTEX + one SEQEND
        1+4*9+1
    )
    assert "\n8\nV14_COPPER_KEEP_OUT_0P5_PRELIM\n" in content
    assert "\n8\nEXISTING_BOARD_155X131_REFERENCE\n" in content
    assert V.build()["fabrication_approved"] is False


def test_svg_layout_has_correct_four_core_and_red_old_pad_marks():
    s=V.SVG.read_text("utf8")
    assert s==V.svg(V.build())
    assert s.count('<circle class="old"')==20
    assert s.count('<rect class="slot"')==12
    assert s.count('<polyline class="winding"')==4
    assert "NOT FOR FAB" in s


def test_usable_Cu_channel_and_centerline_5mm_Uturn_are_geo_feasible_only():
    w=V.winding_screen()
    assert w["channel_between_center_and_outer_slot_mm"]==pytest.approx(7.6375)
    assert w["usable_channel_copper_width_mm"]==pytest.approx(6.6375)
    assert w["screened_copper_trace_width_mm"]==5
    assert w["conductor_U_turn_length_mm"]==pytest.approx(69.8)
    assert w["actual_board_has_12layer_stackup_configured_and_vendor_signed"] is False
    assert w["required_interlayer_anti_pad_microvia_layout_done"] is False
    assert w["primary_3turns_magnetic_dot_and_CTAP_polarity_verified"] is False


def test_hot_copper_layer_sensitivity_no_fake_ac_loss_or_DFM_approval():
    w=V.winding_screen()
    scenario={d["scenario"]:d for d in w["scenarios"]}
    assert scenario["8L_2OZ_secondary2_each"]["four_core_total_dc_copper_loss_100C_W"]==pytest.approx(10.4918)
    assert scenario["12L_2OZ_secondary4_each"]["four_core_total_dc_copper_loss_100C_W"]==pytest.approx(7.6674)
    assert scenario["12L_4OZ_secondary4_each"]["four_core_total_dc_copper_loss_100C_W"]==pytest.approx(3.8337)
    assert scenario["16L_4OZ_secondary6_each"]["four_core_total_dc_copper_loss_100C_W"]==pytest.approx(3.363)
    for x in scenario.values():
        assert x["underestimates_actual_AC_proximity_via_DOT_and_hotspots"]
        assert x["fabricator_can_build_this_stackup_approved"] is False
        assert x["remaining_ideal_layers"]>=0
    assert w["existing_native_component_bottom_count"]==0
    assert w["existing_native_component_top_count"]==149


def test_engineering_EI_nominal_height_is_not_released_full_coldplate():
    w=V.winding_screen()
    assert w["TDK_3p2mm_core_window_mechanical_fit"] is True
    assert w["nominal_E_plus_I_core_total_height_mm"]==9.5
    assert w["nominal_per_side_ferrite_protrusion_with_centered_2mm_board_mm"]==3.75
    assert w["12layer_copper_feasibility_and_16mm_coldplate_full_stackup_verified"] is False


def test_csv_DXF_SVG_json_are_reproducible_from_unchanged_real_native_sources():
    expected=V.deliverables()
    assert set(expected)=={V.OUT,V.CSV,V.DXF,V.SVG}
    for p,body in expected.items():
        assert p.exists()
        assert p.read_text("utf8")==body
    rows=list(csv.DictReader(io.StringIO(V.CSV.read_text("utf8"))))
    assert len(rows)==12
    assert rows[0]["id"]=="T1_LEFT"
    assert rows[-1]["id"]=="T4_RIGHT"
    assert V.OUT.read_text("utf8")==json.dumps(V.build(),ensure_ascii=False,indent=2)+"\n"


def test_tampered_independently_saved_V11_board_fails_closed(monkeypatch,tmp_path):
    bogus=tmp_path/"altered.eprj2"
    bogus.write_bytes(b"not native")
    monkeypatch.setattr(V,"V11",bogus)
    with pytest.raises(ValueError,match="source SHA"):
        V.build()


def test_unjustified_router_wider_than_slot_fails_closed(monkeypatch):
    monkeypatch.setattr(V,"CENTER_LEG_WIDTH_NOM_MM",9.)
    with pytest.raises(ValueError,match="insufficient"):
        V.slot_geometry()


def test_copper_width_closer_to_slot_fails_closed(monkeypatch):
    monkeypatch.setattr(V,"COPPER_WIDTH_MM",7.0)
    with pytest.raises((ValueError,AssertionError)):
        V.winding_screen()


def test_current_report_explicitly_never_claims_actual_12_layer_native_PCB():
    result=json.loads(V.OUT.read_text("utf8"))
    assert result["native_winding_tracks_already_applied"] is False
    assert result["native_cutouts_already_applied"] is False
    assert result["released_copper_stackup"] is False
    assert result["fab_release"]=="NOT_FOR_FAB"

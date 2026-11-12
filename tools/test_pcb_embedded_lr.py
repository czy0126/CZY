"""Engineering regression for an actual 6-layer PCB-embedded Lr concept.

A native KiCad DRC-clean board alone cannot prove a copper winding. These
tests also reject same-layer bypasses/shorts, nonadjacent via contact, missing
core slots and stale source files. There is NO certified magnetic, AC copper,
fault pulse/through-hole plating, 16mm stack or fabrication evidence.
"""
from __future__ import annotations

import copy
import hashlib
import json

import pytest

import pcb_embedded_lr as w


def test_frozen_model_produces_editable_native_board_with_three_series_turns():
    trial,case,paths,slots,points,result=w.design()
    assert case["id"]=="ELP38_Lr_3turn_0920uH"
    assert len(paths)==3 and len(slots)==3 and len(points)==4
    assert len(w.GROUPS)==3 and all(len(pair)==2 for pair in w.GROUPS)
    assert sum(len(path)-1 for path in paths)==21
    assert all(path[0]==points[i] and path[-1]==points[i+1]
               for i,path in enumerate(paths))
    assert result["geometry"]["topological_no_accidental_cross_layer_short_screen_passed"]
    assert len(set(w.LAYER_NUM))==6
    assert result["geometry"]["transition_via_count"]==2
    assert result["geometry"]["through_current_nodes"]==4
    assert not result["main_power_board_modified"]
    assert all(v is False for v in result["qualification"].values())


def test_native_kicad_bom_and_layer_pair_topology_is_source_reproducible():
    board,report,fp,table=w.contents()
    assert w.PCB.read_text(encoding="utf-8")==board
    assert w.REPORT.read_text(encoding="utf-8")==report
    assert w.FPLIB.read_text(encoding="utf-8")==fp
    assert w.FPTABLE.read_text(encoding="utf-8")==table
    assert board.count('(segment (start ')==2*sum(
        len(x)-1 for x in w.design()[2])
    assert board.count('(via (at ')==2
    assert board.count('(pad "1" thru_hole')==2
    assert board.count('(gr_line (start ')==16
    assert 'Lr_Terminal:Embedded_Lr_External_Terminal' in board
    for layer in w.LAYER_NUM:
        assert f'"{layer}"' in board
    assert "NOT_FOR_FAB" in board


def test_actual_native_kicad_drc_did_not_flag_physical_errors_or_opens():
    assert w.DRC.exists(), "Need actual kicad-cli pcb drc before committing"
    body=w.DRC.read_text(encoding="utf-8")
    assert "** Found 0 DRC violations **" in body
    assert "** Found 0 unconnected pads **" in body
    assert "lib_footprint_issues" not in body


def test_load_is_9p45a_rms_not_100a_and_copper_loss_is_not_ac_loss():
    report=w.design()[-1]
    a=report["dc_copper_only_estimate"]
    assert a["not_coil_rms_100a"]
    assert 9.4<a["Lr_coil_rms_a_at_rated_output"]<9.5
    assert 11.2<a["Lr_coil_rms_a_at_120a_output"]<11.3
    assert 0.018<a["r_100c_ohm"]<0.025
    assert 1.5<a["Pdc_100c_100a_output_w"]<2.6
    assert a["r_100c_ohm"]>a["r_20c_ohm"]
    assert a["skin_depth_at_100c_and_clock_mm"]>a["copper_t_per_layer_mm"]
    assert a["fringing_and_AC_Rac_Rdc_omitted"] is True
    assert a["via_and_end_connection_resistance_omitted"] is True
    assert report["magnetic_and_z_screen"]["core_plus_PCB_coldplate_height_verified"] is False
    assert report["qualification"]["real_tdk_n97_100c_nonlin_BH"] is False


def test_all_three_inputs_are_digested_without_copying_source_numbers():
    r=w.design()[-1]
    assert len(r["source_hashes_canonical_lf"])==3
    for name,sha in r["source_hashes_canonical_lf"].items():
        path=w.ROOT/name
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes().replace(b"\r\n",b"\n")).hexdigest()==sha


def test_tighter_fake_6mm_winding_is_rejected_by_core_window(monkeypatch,tmp_path):
    trial=json.loads(w.CONFIG.read_text(encoding="utf-8"))
    trial["board"]["trace_width_mm"]=6.0
    local=tmp_path/"wrong.json"
    local.write_text(json.dumps(trial),encoding="utf-8")
    monkeypatch.setattr(w,"CONFIG",local)
    with pytest.raises(ValueError,match="slot clearance|UNINTENTIONAL SAME-LAYER SHORT"):
        w.design()


def test_original_13mm_short_circuit_through_bridge_is_rejected(monkeypatch,tmp_path):
    trial=json.loads(w.CONFIG.read_text(encoding="utf-8"))
    # This path previously passed KiCad DRC while bypassing a whole turn:
    # both tracks share the same net, so DRC does not know it is a self-short.
    trial["routing"]["turn2_end_turn3_start_via_xy_mm"]=[13,-25]
    trial["routing"]["output_terminal_xy_mm"]=[15,-28]
    local=tmp_path/"shorted.json"
    local.write_text(json.dumps(trial),encoding="utf-8")
    monkeypatch.setattr(w,"CONFIG",local)
    with pytest.raises(ValueError,match="UNINTENTIONAL SAME-LAYER SHORT"):
        w.design()


def test_port_short_to_unrelated_through_layer_is_rejected(monkeypatch,tmp_path):
    trial=json.loads(w.CONFIG.read_text(encoding="utf-8"))
    trial["routing"]["turn1_end_turn2_start_via_xy_mm"]=[18,-25]
    local=tmp_path/"through_short.json"
    local.write_text(json.dumps(trial),encoding="utf-8")
    monkeypatch.setattr(w,"CONFIG",local)
    with pytest.raises(ValueError,match="UNINTENTIONAL SAME-LAYER SHORT|Through via/terminal shorts"):
        w.design()


def test_nonadjacent_track_geometry_distance_is_not_solely_netlist_dependent():
    a=(-6,-22);b=(11,-22)
    c=(13,-16);d=(13,-25)
    assert w._same_layer_segment_gap(a,b,c,d)==2.0
    assert w._same_layer_segment_gap(a,b,c,d)<2.5+0.3

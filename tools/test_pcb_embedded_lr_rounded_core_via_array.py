"""Independent rounded milling slots + four PTH/bridge native KiCad test.

The R0.8 slot is a design-owned, unapproved CNC routing corner radius;
native DRC does not release the TDK ferrite fit or insulated 100C L(I).
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

import pytest

import pcb_embedded_lr as source
import pcb_embedded_lr_4via_trial as old_vias
import pcb_embedded_lr_rounded_core_via_array as r


def test_actual_round_corner_native_board_is_source_reproducible():
    new,receipt=r.contents()
    assert r.PCB.read_text(encoding="utf-8")==new
    assert r.REPORT.read_text(encoding="utf-8")==receipt
    row=json.loads(receipt)
    assert row["schema"]=="D1_ELP38_NATIVE_ROUNDED_SLOT_4VIA_EXPERIMENT_V1"
    assert row["core_slot_routing_corner_radius_mm"]==.8
    assert row["winding_copper_outshift_and_aperture_expansion_mm"]==.8
    assert row["winding_turns"]==3
    assert row["parallel_copper_layers_per_turn"]==2
    assert row["three_actual_rounded_ferrite_cutouts"] is True
    assert row["native_new_12_slot_arcs"] is True
    assert row["new_through_vias"]==6
    assert row["pth_per_bundle"]==4
    assert row["fabrication_approved"] is False
    assert row["slot_mill_tool_radius_vendor_approved"] is False
    assert row["Lr_100C_N97_L_I_and_200kHz_AC_loss_qualified"] is False
    assert hashlib.sha256(new.encode()).hexdigest()==row["native_kicad_sha256_normalized_lf"]
    assert hashlib.sha256(r.CONF.read_bytes().replace(b"\r\n",b"\n")).hexdigest()==row["source_config_lf_sha256"]


def test_independent_ferrite_slots_are_genuinely_rounded_kicad_edges():
    new,_=r.contents()
    assert new.count('(gr_arc (start ')==12
    assert new.count('(gr_line (start ')==16
    assert new.count('(segment (start ')==46
    assert new.count('(via (at ')==8
    assert new.count('(pad "1" thru_hole')==2
    assert new.count('(layer "Edge.Cuts")')==28
    for name in source.LAYER_NUM:
        assert f'"{name}"' in new


def test_native_kicad10_drc_real_run_has_no_violation():
    assert r.DRC.is_file()
    log=r.DRC.read_text(encoding="utf-8")
    assert "** Found 0 DRC violations **" in log
    assert "** Found 0 unconnected pads **" in log


def test_old_rectangle_footprint_remains_inside_new_rounded_cutout():
    data=json.loads(r.REPORT.read_text(encoding="utf-8"))
    for old,new in zip(data["slot_bounding_before"],data["slot_bounding_after"]):
        assert new[0]==pytest.approx(old[0]-.8)
        assert new[1]==pytest.approx(old[1]-.8)
        assert new[2]==pytest.approx(old[2]+.8)
        assert new[3]==pytest.approx(old[3]+.8)
    assert data["original_unchanged_nominal_inner_leg_rectangle_still_fits"]


def test_previous_two_via_and_4via_parent_boards_are_preserved():
    assert source.PCB.read_text(encoding="utf-8")==source.contents()[0]
    assert old_vias.BOARD.read_text(encoding="utf-8")==old_vias.contents()[0]
    assert r.PCB!=source.PCB
    assert r.PCB!=old_vias.BOARD


def test_oversized_rounded_slot_is_rejected_by_core_window(monkeypatch,tmp_path):
    d=json.loads(r.CONF.read_text(encoding="utf-8"))
    d["board"]["slot_tool_corner_radius_mm"]=1.6
    d["board"]["core_slot_extra_each_side_mm"]=1.95
    candidate=tmp_path/"too_large_rounding.json"
    candidate.write_text(json.dumps(d),encoding="utf-8")
    monkeypatch.setattr(r,"CONF",candidate)
    with pytest.raises((ValueError,AssertionError),match="slot|winding|core|short|clearance"):
        r.generate_board()


def test_short_circuited_via_bundle_is_not_automatically_accepted(monkeypatch):
    monkeypatch.setattr(r.V,"PITCH_MM",.2)
    with pytest.raises(ValueError,match="overlap"):
        r.generate_board()

"""Tests for real native-source 100A via-only geometry rejection (NOT FOR FAB)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
import g2_v9_100a_copper_pillar_screen as A


def test_generated_report_exactly_reproduced_from_saved_native_eprj2():
    r=json.loads(A.OUT.read_text("utf8"))
    assert r==json.loads(json.dumps(A.report()))
    assert r["source_native_sha256"]==A.G.V9.sha(A.G.V9.V9)
    assert r["source_counts"]=={"components":149,"pads":443,"lines":407,"vias":93,"nets":65}
    assert r["fabrication_approved"] is False and r["PCB_changed"] is False
    assert r["rated_100A_measured"] is False


def test_no_100a_via_only_shortcut_is_waved_through_at_100C():
    r=A.report()
    assert r["hypothetical_100C_via_only_loss_budget_per_pole_W"]==.2
    v=r["results"]["VOUT"]
    p=r["results"]["PGND"]
    assert v["candidate_count"]==10 and p["candidate_count"]==39
    assert len(v["anchors"])==4 and len(p["anchors"])==8
    assert v["minimum_100C_parallel_vias_per_source_arithmetic"]==15
    assert p["minimum_100C_parallel_vias_per_source_arithmetic"]==8
    assert v["target_contact_sites_for_one_hypothetical_via_strategy"]==60
    assert p["target_contact_sites_for_one_hypothetical_via_strategy"]==64
    assert not v["feasible_via_only_under_current_top_copper"]
    assert not p["feasible_via_only_under_current_top_copper"]
    assert v["missing_candidate_sites"]==50
    assert p["missing_candidate_sites"]==25
    assert r["legacy_bars_2d_only_not_actual_bolted_or_soldered_contacts"]
    assert r["requires_vendor_DFM_for_drill_copper_fill_solder_wicking_insulation"]


def test_every_proposed_hole_is_top_contact_and_clear_of_actual_other_nets():
    native,_=A.native()
    bars=A.G.BUS.outlines(A.G.BUS.load())
    for net,report in A.report()["results"].items():
        obs,top,vias=A.objects(native,net)
        seen=[]
        for a in report["anchors"]:
            for pair in a["potential_via_centers_mm"]:
                p=tuple(pair)
                assert A.BAR.is_inside(p,bars[net])
                assert A.point_to_bar_edge(p,bars[net])>=A.VIA_DIAMETER_MM/2+A.CLEAR_MM
                assert A.clear_native(p,obs,vias)
                assert A.top_overlap(p,top)
                assert all(A.math.dist(p,q)>=A.PITCH_MM-.001 for q in seen)
                seen.append(p)


def test_via_model_at_100C_must_not_be_presented_as_measured_capacity():
    r=A.report()
    for net in ("VOUT","PGND"):
        d=r["results"][net]
        count=d["candidate_count"]
        at100=d[f"ideal_all_{count}_barrels_at_100C"]
        at20=d[f"ideal_all_{count}_barrels_at_20C"]
        assert at100["ohm"]>at20["ohm"]
        assert at100["100a_loss_w"]>at20["100a_loss_w"]
        assert at100["all_sources_share_current_evenly_assumption_only"]
        assert d["actual_pcb_vias_created"]==0
        assert d["actual_bar_to_board_conduction_proven"] is False


def test_source_mutation_rejected(tmp_path,monkeypatch):
    other=tmp_path/"phony.eprj2"
    other.write_bytes(b"This is not a native saved EasyEDA board")
    monkeypatch.setattr(A.G.V9,"V9",other)
    with pytest.raises(ValueError,match="V9 native source changed"):
        A.native()
